"""Real end-to-end acceptance test for the last open "Tests bout-en-bout"
scenario of `docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/10_TEST_ACCEPTANCE.md`
("deux machines simulees sur reseaux differents") and the matching item in
`docs/ROADMAP_CORRECTIONS_AUDIT.md` step 7 ("deux machines simulees sur des
reseaux distincts").

Two fully independent runtime environments — per machine, its own
`MachineModel`/credential, `ClientConfig`, `StudioApiClient`, `OutboxStore` on
a dedicated SQLite file and `TransferClient` — share nothing locally. The real
Postgres+MinIO backend behind `app_transport` (`tests/client/conftest.py`) is
the only thing both ever touch, exactly like two developers' machines that
never talk to each other directly (`.claude/rules/offline-sync.md`). Machine B
is put offline via a real `httpx.ConnectError` transport (same technique as
`tests/client/test_offline_replay_acceptance.py`) while machine A keeps
working and uploads a file, then B reconnects with brand-new client instances
on its own outbox file — a genuine restart — downloads that same file, and a
final replay of B's already-applied operations proves no duplicate lands in
Postgres."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.services import provisioning as provisioning_service
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.outbox import OutboxReplayer, OutboxStore, OutboxTable, connect, transaction
from studio_client.retry import RetryPolicy
from studio_client.tokens import MemoryTokenStore
from studio_client.transfers import TransferClient
from studio_contracts.claims import ResourceClaimCreate, ResourceType
from studio_contracts.tasks import TaskCreate
from studio_contracts.transfers import TransferCategory, TransferCreate

_RETRY_POLICY = RetryPolicy(max_attempts=1, backoff_initial=0.001, backoff_max=0.002)
_SHARED_RESOURCE_PATH = "scenes/shared_level.tscn"


def _offline_transport() -> httpx.MockTransport:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated offline network", request=request)

    return httpx.MockTransport(_handler)


async def _provision_machine(
    db_session: AsyncSession, name: str
) -> tuple[MachineModel, str, AgentModel]:
    user = await provisioning_service.create_user(
        db_session, f"{name} developer", f"{uuid.uuid4()}@example.test", "developer"
    )
    machine_model, token = await provisioning_service.create_machine(db_session, user.id, name)
    agent_model = AgentModel(
        machine_id=machine_model.id, display_name=name, agent_kind="claude_code"
    )
    db_session.add(agent_model)
    await db_session.flush()
    await db_session.refresh(agent_model)
    return machine_model, token, agent_model


def _client_config(machine_id: uuid.UUID) -> ClientConfig:
    return ClientConfig(
        api_base_url="http://test",
        max_attempts=3,
        backoff_initial=0.001,
        backoff_max=0.002,
        machine_id=machine_id,
    )


async def test_two_independent_machines_never_sharing_local_state_converge_on_server(
    tmp_path: Path,
    app_transport: ASGITransport,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    machine_a, token_a, _agent_a = await _provision_machine(db_session, "machine-a")
    machine_b, token_b, agent_b = await _provision_machine(db_session, "machine-b")

    config_a = _client_config(machine_a.id)
    config_b = _client_config(machine_b.id)
    tokens_a = MemoryTokenStore()
    tokens_a.set_token("http://test", token_a)
    tokens_b = MemoryTokenStore()
    tokens_b.set_token("http://test", token_b)

    outbox_path_a = tmp_path / "machine-a-outbox.sqlite3"
    outbox_path_b = tmp_path / "machine-b-outbox.sqlite3"
    open_stores: list[OutboxStore] = []

    task_key_a = str(uuid.uuid4())
    task_key_b = str(uuid.uuid4())
    claim_key_a = str(uuid.uuid4())
    claim_key_b = str(uuid.uuid4())
    ai_work_key_b = str(uuid.uuid4())

    source_path = tmp_path / "shared-asset.bin"
    dest_path = tmp_path / "downloaded-asset.bin"
    source_path.write_bytes(b"studio-os two-machines acceptance payload" * 100)

    try:
        # --- Machine A stays online throughout: one task, a claim on the
        # shared resource, and a file it shares for machine B to fetch —
        # nothing on this side ever touches machine B's outbox file. ---
        store_a = OutboxStore(connect(outbox_path_a))
        open_stores.append(store_a)
        async with StudioApiClient(config_a, tokens_a, transport=app_transport) as api_a:
            task_a = await api_a.create_task(
                TaskCreate(project_id=project.id, title="machine-a-task"),
                idempotency_key=task_key_a,
            )
            claim_a = await api_a.create_claim(
                ResourceClaimCreate(
                    project_id=project.id,
                    resource_path=_SHARED_RESOURCE_PATH,
                    resource_type=ResourceType.FILE,
                    ttl_seconds=600,
                ),
                idempotency_key=claim_key_a,
            )
            assert claim_a.claimed_by_machine_id == machine_a.id

            transfer = await api_a.create_transfer(
                TransferCreate(
                    project_id=project.id,
                    category=TransferCategory.TEMPORARY,
                    filename="shared-asset.bin",
                    content_type="application/octet-stream",
                    size_bytes=source_path.stat().st_size,
                ),
                idempotency_key=str(uuid.uuid4()),
            )
            transfer_client_a = TransferClient(api_a, store_a)
            transfer = await transfer_client_a.upload(transfer, source_path)
            await transfer_client_a.aclose()

        # --- Machine B starts offline: its own daemon queues a task, a
        # concurrent claim on the same resource, and an AIWorkLog entry —
        # none of it reaches the server yet, and none of it is visible to
        # or shared with machine A's outbox. ---
        store_b = OutboxStore(connect(outbox_path_b))
        open_stores.append(store_b)
        with transaction(store_b.connection):
            store_b.enqueue_mutation(
                task_key_b,
                "task.create",
                "POST",
                "/api/v1/tasks",
                TaskCreate(project_id=project.id, title="machine-b-task").model_dump(mode="json"),
            )
        with transaction(store_b.connection):
            store_b.enqueue_mutation(
                claim_key_b,
                "claim.create",
                "POST",
                "/api/v1/claims",
                ResourceClaimCreate(
                    project_id=project.id,
                    resource_path=_SHARED_RESOURCE_PATH,
                    resource_type=ResourceType.FILE,
                    ttl_seconds=600,
                ).model_dump(mode="json"),
            )
        ai_work_payload_b: dict[str, object] = {
            "project_id": str(project.id),
            "agent_id": str(agent_b.id),
            "machine_id": str(machine_b.id),
            "summary": "machine-b offline work",
        }
        with transaction(store_b.connection):
            store_b.enqueue_mutation(
                ai_work_key_b, "ai_work.create", "POST", "/api/v1/ai-work", ai_work_payload_b
            )

        async with StudioApiClient(
            config_b, tokens_b, transport=_offline_transport()
        ) as offline_api_b:
            offline_outcome = await OutboxReplayer(
                store_b, offline_api_b, _RETRY_POLICY
            ).replay_ready()
        assert offline_outcome.succeeded == 0
        assert offline_outcome.stopped_on_transient_error is True
        assert len(store_b.list_pending(OutboxTable.MUTATIONS, ready_only=False)) == 3

        # --- Machine B reconnects: brand-new StudioApiClient/OutboxStore on
        # the same SQLite file (a real restart), replays its queue, and
        # downloads machine A's file straight from storage — never from
        # machine A, never through the API process. ---
        resumed_store_b = OutboxStore(connect(outbox_path_b))
        open_stores.append(resumed_store_b)
        async with StudioApiClient(config_b, tokens_b, transport=app_transport) as api_b:
            online_outcome = await OutboxReplayer(
                resumed_store_b, api_b, _RETRY_POLICY
            ).replay_ready()
            assert online_outcome.succeeded == 3
            assert online_outcome.dead_lettered == 0
            assert resumed_store_b.list_pending(OutboxTable.MUTATIONS, ready_only=False) == []

            fetched_transfer = await api_b.get_transfer(transfer.id)
            transfer_client_b = TransferClient(api_b, resumed_store_b)
            await transfer_client_b.download(fetched_transfer, dest_path)
            await transfer_client_b.aclose()

        assert dest_path.read_bytes() == source_path.read_bytes()

        # --- Idempotence: re-enqueue and replay machine B's exact same
        # operations again. The server must not duplicate anything already
        # applied above, matching the outbox's own UNIQUE replay key. ---
        replay_store_b = OutboxStore(connect(outbox_path_b))
        open_stores.append(replay_store_b)
        with transaction(replay_store_b.connection):
            replay_store_b.enqueue_mutation(
                task_key_b,
                "task.create",
                "POST",
                "/api/v1/tasks",
                TaskCreate(project_id=project.id, title="machine-b-task").model_dump(mode="json"),
            )
        with transaction(replay_store_b.connection):
            replay_store_b.enqueue_mutation(
                claim_key_b,
                "claim.create",
                "POST",
                "/api/v1/claims",
                ResourceClaimCreate(
                    project_id=project.id,
                    resource_path=_SHARED_RESOURCE_PATH,
                    resource_type=ResourceType.FILE,
                    ttl_seconds=600,
                ).model_dump(mode="json"),
            )
        with transaction(replay_store_b.connection):
            replay_store_b.enqueue_mutation(
                ai_work_key_b, "ai_work.create", "POST", "/api/v1/ai-work", ai_work_payload_b
            )
        async with StudioApiClient(config_b, tokens_b, transport=app_transport) as api_b_again:
            replay_outcome = await OutboxReplayer(
                replay_store_b, api_b_again, _RETRY_POLICY
            ).replay_ready()
        assert replay_outcome.succeeded == 3
        assert replay_outcome.dead_lettered == 0

        # --- Final verification: every operation from both independently
        # run machines landed exactly once in the one place they both ever
        # touched — Postgres — correctly attributed to its own machine. ---
        tasks = (
            (await db_session.execute(select(TaskModel).where(TaskModel.project_id == project.id)))
            .scalars()
            .all()
        )
        assert {t.title for t in tasks} == {"machine-a-task", "machine-b-task"}
        assert len(tasks) == 2

        claims = (
            (
                await db_session.execute(
                    select(ResourceClaimModel).where(
                        ResourceClaimModel.project_id == project.id,
                        ResourceClaimModel.resource_path == _SHARED_RESOURCE_PATH,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {c.claimed_by_machine_id for c in claims} == {machine_a.id, machine_b.id}
        assert len(claims) == 2, (
            "replaying claim.create with the same idempotency key must not duplicate it"
        )
        assert all(c.status == "active" for c in claims), (
            "Resource Claims warn but never block, even across two independent machines"
        )

        assert task_a.title == "machine-a-task"
    finally:
        for open_store in open_stores:
            open_store.connection.close()
        outbox_path_a.unlink(missing_ok=True)
        outbox_path_b.unlink(missing_ok=True)
