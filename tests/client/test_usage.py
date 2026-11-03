from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.usage import UsageLedgerEntryModel
from studio_api.services import provisioning as provisioning_service
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.outbox import OutboxReplayer, OutboxStore, OutboxTable, connect, transaction
from studio_client.retry import RetryPolicy
from studio_client.tokens import MemoryTokenStore
from studio_client.usage import USAGE_CORRECTIONS_PATH, USAGE_PATH, UsageWriteQueue
from studio_contracts.usage import (
    MeasurementCoverage,
    TokenMeasurement,
    UsageLedgerCorrection,
    UsageLedgerEntry,
    UsageLedgerEntryCreate,
    UsageProvenance,
)


def _entry(project_id: UUID, machine_id: UUID) -> UsageLedgerEntryCreate:
    start = datetime.now(UTC)
    return UsageLedgerEntryCreate(
        project_id=project_id,
        machine_id=machine_id,
        source_event_id=f"usage-{uuid4()}",
        provenance=UsageProvenance(collector="client-test", harness="codex"),
        period_start=start,
        period_end=start + timedelta(seconds=1),
        tokens_in=TokenMeasurement(value=10, coverage=MeasurementCoverage.MEASURED),
    )


def _correction(entry: UsageLedgerEntryCreate) -> UsageLedgerCorrection:
    return UsageLedgerCorrection(
        machine_id=entry.machine_id,
        source_event_id=entry.source_event_id,
        expected_version=1,
        provenance=entry.provenance,
        period_start=entry.period_start,
        period_end=entry.period_end + timedelta(seconds=1),
        tokens_in=TokenMeasurement(value=25, coverage=MeasurementCoverage.MEASURED),
    )


def _enqueue(
    queue: UsageWriteQueue,
    observation: UsageLedgerEntryCreate | UsageLedgerCorrection,
    key: UUID,
) -> bool:
    if isinstance(observation, UsageLedgerEntryCreate):
        return queue.enqueue_entry(observation, idempotency_key=key)
    return queue.enqueue_correction(observation, idempotency_key=key)


def _retry_policy() -> RetryPolicy:
    return RetryPolicy(max_attempts=1, backoff_initial=0.001, backoff_max=0.002)


def _make_ready(store: OutboxStore) -> None:
    with transaction(store.connection):
        store.connection.execute(
            "UPDATE pending_mutations SET next_attempt_at = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )


async def _assert_ledger(
    session: AsyncSession, entry: UsageLedgerEntryCreate, *, tokens: int, version: int
) -> UUID:
    rows = (
        await session.execute(
            select(
                UsageLedgerEntryModel.id,
                UsageLedgerEntryModel.tokens_in,
                UsageLedgerEntryModel.version,
            ).where(UsageLedgerEntryModel.project_id == entry.project_id)
        )
    ).all()
    assert len(rows) == 1
    ledger_id, stored_tokens, stored_version = rows[0]
    assert stored_tokens == tokens
    assert stored_version == version
    return ledger_id


@pytest.mark.parametrize("kind", ["entry", "correction"])
def test_usage_enqueue_shares_local_write_commit_and_rollback(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "usage.sqlite3"
    store = OutboxStore(connect(path))
    queue = UsageWriteQueue(store)
    entry = _entry(uuid4(), uuid4())
    observation = entry if kind == "entry" else _correction(entry)
    key = uuid4()
    try:
        with transaction(store.connection):
            store.connection.execute("CREATE TABLE observations (source_event_id TEXT PRIMARY KEY)")
        reader = connect(path)
        try:
            with transaction(store.connection):
                store.connection.execute(
                    "INSERT INTO observations VALUES (?)", (entry.source_event_id,)
                )
                assert _enqueue(queue, observation, key) is True
                assert reader.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
                assert reader.execute("SELECT COUNT(*) FROM pending_mutations").fetchone()[0] == 0
            assert reader.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
            assert reader.execute("SELECT COUNT(*) FROM pending_mutations").fetchone()[0] == 1
            with pytest.raises(RuntimeError, match="abort local write"):
                with transaction(store.connection):
                    store.connection.execute("INSERT INTO observations VALUES ('rollback')")
                    assert _enqueue(queue, observation, uuid4()) is True
                    raise RuntimeError("abort local write")
            assert reader.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
            assert reader.execute("SELECT COUNT(*) FROM pending_mutations").fetchone()[0] == 1
            pending = store.list_pending(OutboxTable.MUTATIONS, ready_only=False)
            assert pending[0].id == str(key)
            assert pending[0].payload == observation.model_dump(mode="json")
        finally:
            reader.close()
    finally:
        store.connection.close()


@pytest.mark.parametrize("kind", ["entry", "correction"])
def test_usage_duplicate_key_is_unique_and_payload_conflict_is_visible(
    tmp_path: Path, kind: str
) -> None:
    store = OutboxStore(connect(tmp_path / "usage.sqlite3"))
    queue = UsageWriteQueue(store)
    entry = _entry(uuid4(), uuid4())
    observation = entry if kind == "entry" else _correction(entry)
    key = uuid4()
    try:
        with transaction(store.connection):
            assert _enqueue(queue, observation, key) is True
            assert _enqueue(queue, observation, key) is False
        changed = observation.model_copy(
            update={"tokens_in": TokenMeasurement(value=30, coverage=MeasurementCoverage.MEASURED)}
        )
        with pytest.raises(ValueError, match="^idempotency_key_payload_mismatch$"):
            with transaction(store.connection):
                _enqueue(queue, changed, key)
        pending = store.list_pending(OutboxTable.MUTATIONS, ready_only=False)
        assert len(pending) == 1
        assert pending[0].id == str(key)
        assert pending[0].payload == observation.model_dump(mode="json")
    finally:
        store.connection.close()


async def test_usage_restart_and_network_recovery_preserve_order_and_keys(
    tmp_path: Path,
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, token = machine
    entry = _entry(project.id, machine_model.id)
    correction = _correction(entry)
    keys = [uuid4(), uuid4()]
    path = tmp_path / "usage.sqlite3"
    store = OutboxStore(connect(path))
    with transaction(store.connection):
        queue = UsageWriteQueue(store)
        assert queue.enqueue_entry(entry, idempotency_key=keys[0]) is True
        assert queue.enqueue_correction(correction, idempotency_key=keys[1]) is True
    store.connection.close()
    store = OutboxStore(connect(path))
    sent: list[tuple[str, str]] = []

    def offline(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, request.headers["Idempotency-Key"]))
        raise httpx.ConnectError("network down", request=request)

    try:
        async with StudioApiClient(
            client_config, token_store, transport=httpx.MockTransport(offline)
        ) as api:
            outcome = await OutboxReplayer(store, api, _retry_policy()).replay_ready()
        assert outcome.succeeded == 0
        assert outcome.dead_lettered == 0
        assert outcome.stopped_on_transient_error is True
        assert sent == [(USAGE_PATH, str(keys[0]))] * client_config.max_attempts
        pending = store.list_pending(OutboxTable.MUTATIONS, ready_only=False)
        assert [row.id for row in pending] == [str(key) for key in keys]
        assert [row.payload for row in pending] == [
            entry.model_dump(mode="json"),
            correction.model_dump(mode="json"),
        ]
        store.connection.close()
        store = OutboxStore(connect(path))
        _make_ready(store)
        sent.clear()

        async def online(request: httpx.Request) -> httpx.Response:
            sent.append((request.url.path, request.headers["Idempotency-Key"]))
            return await app_transport.handle_async_request(request)

        async with StudioApiClient(
            client_config, token_store, transport=httpx.MockTransport(online)
        ) as api:
            outcome = await OutboxReplayer(store, api, _retry_policy()).replay_ready()
        assert outcome.succeeded == 2
        assert outcome.dead_lettered == 0
        assert outcome.stopped_on_transient_error is False
        assert sent == [(USAGE_PATH, str(keys[0])), (USAGE_CORRECTIONS_PATH, str(keys[1]))]
        assert store.pending_count() == 0
        ledger_id = await _assert_ledger(db_session, entry, tokens=25, version=2)
        async with httpx.AsyncClient(transport=app_transport, base_url="http://test") as api:
            response = await api.get(
                USAGE_PATH,
                params={"project_id": str(project.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        assert len(response.json()) == 1
        stored = UsageLedgerEntry.model_validate(response.json()[0])
        assert stored.id == ledger_id
        assert stored.tokens_in.value == 25
        assert stored.version == 2
    finally:
        store.connection.close()


@pytest.mark.parametrize("lost_operation", ["entry", "correction"])
async def test_usage_lost_ack_replays_without_duplicate_or_extra_version(
    tmp_path: Path,
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
    lost_operation: str,
) -> None:
    machine_model, _ = machine
    entry = _entry(project.id, machine_model.id)
    observation = entry if lost_operation == "entry" else _correction(entry)
    mutation_path = USAGE_PATH if lost_operation == "entry" else USAGE_CORRECTIONS_PATH
    tokens, version = (10, 1) if lost_operation == "entry" else (25, 2)
    if lost_operation == "correction":
        async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
            response = await api.send_mutation(
                "POST", USAGE_PATH, entry.model_dump(mode="json"), idempotency_key=str(uuid4())
            )
        assert response.status_code == 201
    key = uuid4()
    path = tmp_path / "usage.sqlite3"
    store = OutboxStore(connect(path))
    with transaction(store.connection):
        assert _enqueue(UsageWriteQueue(store), observation, key) is True
    responses: list[dict[str, object]] = []
    sent: list[tuple[str, str, bytes]] = []

    async def lose_ack(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, request.headers["Idempotency-Key"], request.content))
        response = await app_transport.handle_async_request(request)
        await response.aread()
        assert response.status_code == (201 if lost_operation == "entry" else 200)
        responses.append(response.json())
        raise httpx.ReadError("response lost after server write", request=request)

    try:
        async with StudioApiClient(
            client_config.model_copy(update={"max_attempts": 1}),
            token_store,
            transport=httpx.MockTransport(lose_ack),
        ) as api:
            outcome = await OutboxReplayer(store, api, _retry_policy()).replay_ready()
        assert outcome.stopped_on_transient_error is True
        assert outcome.succeeded == 0
        assert outcome.dead_lettered == 0
        ledger_id = await _assert_ledger(db_session, entry, tokens=tokens, version=version)
        assert [row.id for row in store.list_pending(OutboxTable.MUTATIONS, ready_only=False)] == [
            str(key)
        ]
        store.connection.close()
        store = OutboxStore(connect(path))
        _make_ready(store)

        async def resend(request: httpx.Request) -> httpx.Response:
            sent.append((request.url.path, request.headers["Idempotency-Key"], request.content))
            response = await app_transport.handle_async_request(request)
            await response.aread()
            responses.append(response.json())
            return response

        async with StudioApiClient(
            client_config, token_store, transport=httpx.MockTransport(resend)
        ) as api:
            outcome = await OutboxReplayer(store, api, _retry_policy()).replay_ready()
        assert outcome.succeeded == 1
        assert outcome.dead_lettered == 0
        assert outcome.stopped_on_transient_error is False
        assert store.pending_count() == 0
        assert len(sent) == 2
        assert sent[0] == sent[1]
        assert sent[0][:2] == (mutation_path, str(key))
        assert responses[0] == responses[1]
        assert await _assert_ledger(db_session, entry, tokens=tokens, version=version) == ledger_id
    finally:
        store.connection.close()


async def test_usage_foreign_machine_and_stale_correction_remain_inspectable(
    tmp_path: Path,
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    foreign_machine, _ = await provisioning_service.create_machine(
        db_session, machine_model.owner_user_id, "other-usage-machine"
    )
    entry = _entry(project.id, machine_model.id)
    correction = _correction(entry)
    path = tmp_path / "usage.sqlite3"
    store = OutboxStore(connect(path))
    try:
        with transaction(store.connection):
            queue = UsageWriteQueue(store)
            queue.enqueue_entry(entry, idempotency_key=uuid4())
            queue.enqueue_correction(correction, idempotency_key=uuid4())
        async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
            seeded = await OutboxReplayer(store, api, _retry_policy()).replay_ready()
        assert seeded.succeeded == 2
        assert seeded.dead_lettered == 0
        foreign = _entry(project.id, foreign_machine.id)
        stale = correction.model_copy(
            update={"tokens_in": TokenMeasurement(value=99, coverage=MeasurementCoverage.MEASURED)}
        )
        foreign_key, stale_key = uuid4(), uuid4()
        with transaction(store.connection):
            queue.enqueue_entry(foreign, idempotency_key=foreign_key)
            queue.enqueue_correction(stale, idempotency_key=stale_key)
        async with StudioApiClient(client_config, token_store, transport=app_transport) as api:
            outcome = await OutboxReplayer(store, api, _retry_policy()).replay_ready()
        assert outcome.succeeded == 0
        assert outcome.dead_lettered == 2
        assert outcome.stopped_on_transient_error is False
        assert store.pending_count() == 0
        store.connection.close()
        store = OutboxStore(connect(path))
        dead = {
            row["id"]: row
            for row in store.connection.execute("SELECT * FROM dead_letter").fetchall()
        }
        assert set(dead) == {str(foreign_key), str(stale_key)}
        for key, payload, error in (
            (foreign_key, foreign, "409 actor_not_owned"),
            (stale_key, stale, "409 version_conflict"),
        ):
            row = dead[str(key)]
            assert row["source_table"] == OutboxTable.MUTATIONS.value
            assert row["error"] == error
            saved = json.loads(row["payload_json"])
            assert saved["idempotency_key"] == str(key)
            assert json.loads(saved["payload_json"]) == payload.model_dump(mode="json")
        await _assert_ledger(db_session, entry, tokens=25, version=2)
    finally:
        store.connection.close()
