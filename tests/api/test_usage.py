from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.idempotency import IdempotencyKeyModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.usage import UsageLedgerEntryModel
from studio_api.db.models.user import UserModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import idempotency as idempotency_service
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_contracts.usage import UsageLedgerEntry

from tests.api.test_launch_credentials import _accepted_launch, _credential

START = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)


def _entry(
    project_id: uuid.UUID | str, machine_id: uuid.UUID | str, **changes: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project_id": str(project_id),
        "machine_id": str(machine_id),
        "source_event_id": f"evt-{uuid.uuid4().hex}",
        "provenance": {"collector": "runtime", "collector_version": "v1"},
        "period_start": START.isoformat(),
        "period_end": (START + timedelta(seconds=5)).isoformat(),
    }
    body.update(changes)
    return body


def _correction(entry: dict[str, Any], **changes: Any) -> dict[str, Any]:
    body = {
        name: entry[name]
        for name in ("machine_id", "source_event_id", "provenance", "period_start", "period_end")
    }
    body["expected_version"] = entry.get("version", 1)
    body.update(changes)
    return body


async def _post(
    client: AsyncClient,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    key: str | None = None,
    correction: bool = False,
) -> Response:
    return await client.post(
        "/api/v1/usage/corrections" if correction else "/api/v1/usage",
        headers={**headers, **({"Idempotency-Key": key} if key else {})},
        json=body,
    )


async def _linked_body(
    session: AsyncSession, project: ProjectModel, machine: MachineModel, agent: AgentModel
) -> dict[str, Any]:
    task = TaskModel(project_id=project.id, title="Usage task")
    session.add(task)
    await session.flush()
    work_session = WorkSessionModel(task_id=task.id, machine_id=machine.id, started_at=START)
    session.add(work_session)
    await session.flush()
    launch = TaskLaunchModel(
        project_id=project.id,
        task_id=task.id,
        machine_id=machine.id,
        requested_by_user_id=machine.owner_user_id,
        harness_id="claude-code",
        session_id=work_session.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    work = AIWorkLogModel(
        project_id=project.id,
        task_id=task.id,
        machine_id=machine.id,
        agent_id=agent.id,
        session_id=work_session.id,
        summary="Usage work",
        started_at=START,
    )
    session.add_all([launch, work])
    await session.flush()
    return _entry(
        project.id,
        machine.id,
        task_id=str(task.id),
        session_id=str(work_session.id),
        task_launch_id=str(launch.id),
        ai_work_id=str(work.id),
    )


async def test_replay_by_key_and_source_never_adds_or_overwrites(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    body = _entry(project.id, machine[0].id, tokens_in={"value": 100, "coverage": "measured"})
    key = str(uuid.uuid4())
    first = await _post(client, auth_headers, body, key=key)
    assert first.status_code == 201, first.text
    replay = await _post(client, auth_headers, body, key=key)
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    changed = {**body, "tokens_in": {"value": 900, "coverage": "measured"}}
    replay_source = await _post(client, auth_headers, changed, key=str(uuid.uuid4()))
    assert replay_source.status_code == 201, replay_source.text
    assert replay_source.json() == first.json()
    mismatch = await _post(client, auth_headers, changed, key=key)
    assert mismatch.status_code == 409, mismatch.text
    assert mismatch.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"
    assert await db_session.scalar(select(func.count(UsageLedgerEntryModel.id))) == 1
    assert await db_session.scalar(select(func.sum(UsageLedgerEntryModel.tokens_in))) == 100


async def test_final_corrects_snapshot_atomically_and_exact_replay_ignores_stale_version(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    body = _entry(
        project.id,
        machine[0].id,
        tokens_in={"value": 100, "coverage": "measured"},
        tokens_out={"value": 20, "coverage": "measured"},
        cost={"value": "0.25", "coverage": "estimated", "currency": "EUR"},
        pricing={"price_list_id": "prices-v1", "effective_from": START.isoformat()},
    )
    first = await _post(client, auth_headers, body)
    assert first.status_code == 201, first.text
    correction = _correction(
        first.json(),
        tokens_in={"value": 125, "coverage": "measured"},
        tokens_out={"value": 45, "coverage": "measured"},
        tokens_cached={"value": 50, "coverage": "measured"},
        duration={"value": "12.125", "coverage": "measured"},
        period_end=(START + timedelta(seconds=12)).isoformat(),
        provenance={"collector": "runtime", "collector_version": "v2", "model": "vendor/model"},
    )
    key = str(uuid.uuid4())
    final = await _post(client, auth_headers, correction, key=key, correction=True)
    assert final.status_code == 200, final.text
    final_entry = UsageLedgerEntry.model_validate(final.json())
    assert final_entry.id == uuid.UUID(first.json()["id"])
    assert final_entry.version == 2
    assert final_entry.total_tokens == 170
    assert final_entry.cost.value is None and final_entry.pricing is None
    assert final_entry.provenance.collector_version == "v2"
    assert final_entry.duration.value == Decimal("12.125")
    replay = await _post(client, auth_headers, correction, key=key, correction=True)
    assert replay.status_code == 200, replay.text
    assert replay.json() == final.json()
    stale = await _post(client, auth_headers, correction, key=str(uuid.uuid4()), correction=True)
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"] == {"error_code": "version_conflict", "server_version": 2}
    replay_source = await _post(client, auth_headers, body, key=str(uuid.uuid4()))
    assert replay_source.status_code == 201, replay_source.text
    assert replay_source.json() == final.json()
    assert await db_session.scalar(select(func.count(UsageLedgerEntryModel.id))) == 1
    assert await db_session.scalar(select(func.sum(UsageLedgerEntryModel.tokens_in))) == 125
    assert await db_session.scalar(select(func.sum(UsageLedgerEntryModel.tokens_out))) == 45


async def test_unknown_values_and_separate_cache_currency_pricing_roundtrip(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    unknown = await _post(client, auth_headers, _entry(project.id, machine[0].id))
    assert unknown.status_code == 201, unknown.text
    entry = UsageLedgerEntry.model_validate(unknown.json())
    assert all(c.value == "unknown" for c in entry.coverage_by_metric.values())
    assert entry.total_tokens is None
    measured = await _post(
        client,
        auth_headers,
        _entry(
            project.id,
            machine[0].id,
            tokens_in={"value": 100, "coverage": "measured"},
            tokens_out={"value": 20, "coverage": "measured"},
            tokens_cached={"value": 150, "coverage": "estimated"},
            cached_tokens_scope="additional_to_input",
            cost={"value": "0.01234567", "coverage": "estimated", "currency": "USD"},
            pricing={"price_list_id": "prices-v2", "effective_from": START.isoformat()},
        ),
    )
    assert measured.status_code == 201, measured.text
    entry = UsageLedgerEntry.model_validate(measured.json())
    assert entry.total_tokens == 270
    assert entry.cost.value == Decimal("0.01234567") and entry.cost.currency == "USD"
    assert entry.pricing is not None and entry.pricing.price_list_id == "prices-v2"


async def test_storage_maxima_roundtrip_without_replacing_unknown_metrics(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    body = _entry(
        project.id,
        machine[0].id,
        tokens_in={"value": 2**63 - 1, "coverage": "measured"},
        tokens_out={"value": 2**63 - 1, "coverage": "measured"},
        tokens_cached={"value": 2**63 - 1, "coverage": "measured"},
        cost={"value": "9999999999.99999999", "coverage": "measured", "currency": "EUR"},
        duration={"value": "99999999999.999", "coverage": "measured"},
    )
    created = await _post(client, auth_headers, body, key=str(uuid.uuid4()))
    assert created.status_code == 201, created.text
    entry = UsageLedgerEntry.model_validate(created.json())
    assert entry.tokens_in.value == entry.tokens_out.value == entry.tokens_cached.value == 2**63 - 1
    assert entry.cost.value == Decimal("9999999999.99999999")
    assert entry.duration.value == Decimal("99999999999.999")
    correction = _correction(created.json(), cost=body["cost"], duration=body["duration"])
    corrected = await _post(
        client, auth_headers, correction, key=str(uuid.uuid4()), correction=True
    )
    assert corrected.status_code == 200, corrected.text
    entry = UsageLedgerEntry.model_validate(corrected.json())
    assert entry.tokens_in.value is None and entry.tokens_in.coverage.value == "unknown"
    assert entry.cost.value == Decimal("9999999999.99999999")
    assert entry.duration.value == Decimal("99999999999.999")


@pytest.mark.parametrize(
    "metric,value",
    [
        ("tokens_in", 2**63),
        ("tokens_out", 2**63),
        ("tokens_cached", 2**63),
        ("cost", "10000000000"),
        ("duration", "100000000000"),
    ],
)
@pytest.mark.parametrize("correction", [False, True])
async def test_storage_overflow_is_a_terminal_422_before_reservation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
    metric: str,
    value: int | str,
    correction: bool,
) -> None:
    body = _entry(project.id, machine[0].id)
    if correction:
        created = await _post(client, auth_headers, body)
        assert created.status_code == 201, created.text
        body = _correction(created.json())
    body[metric] = {"value": value, "coverage": "measured"}
    if metric == "cost":
        body[metric]["currency"] = "EUR"
    if metric == "tokens_cached":
        body["cached_tokens_scope"] = "additional_to_input"
    key = str(uuid.uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as http:
        response = await _post(http, auth_headers, body, key=key, correction=correction)
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {
        "error_code": "invalid_usage_measurement",
        "metric": metric,
    }
    assert (
        await db_session.scalar(
            select(IdempotencyKeyModel).where(IdempotencyKeyModel.idempotency_key == key)
        )
        is None
    )
    if correction:
        row = await db_session.get(UsageLedgerEntryModel, uuid.UUID(created.json()["id"]))
        assert row is not None and row.version == 1


@pytest.mark.parametrize(
    "invalid",
    [
        {"tokens_in": {"value": 0, "coverage": "unknown"}},
        {"tokens_in": {"coverage": "measured"}},
        {"cost": {"value": "1", "coverage": "measured"}},
        {"cost": {"value": "1", "coverage": "estimated", "currency": "EUR"}},
        {"pricing": {"price_list_id": "p", "effective_from": START.isoformat()}},
        {
            "tokens_in": {"value": 10, "coverage": "measured"},
            "tokens_cached": {"value": 11, "coverage": "measured"},
        },
        {"period_end": (START - timedelta(seconds=1)).isoformat()},
    ],
)
async def test_invalid_measures_are_rejected_without_storing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
    invalid: dict[str, Any],
) -> None:
    response = await _post(client, auth_headers, _entry(project.id, machine[0].id, **invalid))
    assert response.status_code == 422, response.text
    assert await db_session.scalar(select(func.count(UsageLedgerEntryModel.id))) == 0


async def test_machine_identity_and_readonly_are_checked_before_cached_response(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    body = _entry(project.id, machine[0].id)
    key = str(uuid.uuid4())
    first = await _post(client, auth_headers, body, key=key)
    assert first.status_code == 201, first.text
    for headers in (other_auth_headers, admin_auth_headers):
        denied = await _post(client, headers, body, key=key)
        assert denied.status_code == 409, denied.text
        assert denied.json()["detail"]["error_code"] == "actor_not_owned"
        denied = await _post(client, headers, _correction(first.json()), correction=True)
        assert denied.status_code == 409, denied.text
    readonly = await _post(client, readonly_auth_headers, body, key=key)
    assert readonly.status_code == 403, readonly.text


@pytest.mark.isolation
async def test_project_scope_filters_and_revocation_apply_before_replay(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    membership = ProjectMembershipModel(project_id=project.id, user_id=machine[0].owner_user_id)
    db_session.add(membership)
    await db_session.flush()
    foreign = await projects_service.create_project(
        db_session, f"foreign-{uuid.uuid4().hex[:8]}", "Foreign", None, creator=None
    )
    body = _entry(project.id, machine[0].id)
    key = str(uuid.uuid4())
    first = await _post(client, auth_headers, body, key=key)
    assert first.status_code == 201, first.text
    hidden = UsageLedgerEntryModel(
        project_id=foreign.id,
        machine_id=machine[0].id,
        source_event_id="foreign-event",
        collector="runtime",
        period_start=START,
        period_end=START,
    )
    db_session.add(hidden)
    await db_session.flush()
    listed = await client.get("/api/v1/usage", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [entry["id"] for entry in listed.json()] == [first.json()["id"]]
    denied = await client.get(
        "/api/v1/usage", params={"project_id": str(foreign.id)}, headers=auth_headers
    )
    assert denied.status_code == 403, denied.text
    denied = await _post(client, auth_headers, _entry(foreign.id, machine[0].id))
    assert denied.status_code == 403, denied.text
    correction_key = str(uuid.uuid4())
    correction = _correction(first.json())
    accepted = await _post(client, auth_headers, correction, key=correction_key, correction=True)
    assert accepted.status_code == 200, accepted.text
    await db_session.delete(membership)
    await db_session.commit()
    denied = await _post(client, auth_headers, body, key=key)
    assert denied.status_code == 403, denied.text
    denied = await _post(client, auth_headers, correction, key=correction_key, correction=True)
    assert denied.status_code == 403, denied.text


@pytest.mark.parametrize(
    "field", ["project_id", "task_id", "session_id", "task_launch_id", "ai_work_id", "collector"]
)
async def test_source_identity_cannot_move_to_other_links_or_collector(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    db_session: AsyncSession,
    field: str,
) -> None:
    body = await _linked_body(db_session, project, machine[0], agent)
    first = await _post(client, auth_headers, body)
    assert first.status_code == 201, first.text
    moved = {**body}
    if field == "collector":
        moved["provenance"] = {"collector": "another"}
    elif field == "project_id":
        other = await projects_service.create_project(
            db_session, f"other-{uuid.uuid4().hex[:8]}", "Other", None, creator=None
        )
        moved = _entry(other.id, machine[0].id, source_event_id=body["source_event_id"])
    else:
        moved[field] = None
    denied = await _post(client, auth_headers, moved, key=str(uuid.uuid4()))
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["error_code"] == "usage_identity_conflict"


@pytest.mark.parametrize("resource", ["session", "launch", "ai_work"])
async def test_foreign_machine_links_are_refused_even_for_admin(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    db_session: AsyncSession,
    resource: str,
) -> None:
    body = await _linked_body(db_session, project, machine[0], agent)
    admin_user = await db_session.scalar(select(UserModel).where(UserModel.role == "admin"))
    assert admin_user is not None
    admin_machine = await db_session.scalar(
        select(MachineModel).where(MachineModel.owner_user_id == admin_user.id)
    )
    assert admin_machine is not None
    body["machine_id"] = str(admin_machine.id)
    fields = {"session": "session_id", "launch": "task_launch_id", "ai_work": "ai_work_id"}
    body = {k: v for k, v in body.items() if k not in fields.values() or k == fields[resource]}
    denied = await _post(client, admin_auth_headers, body)
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["error_code"] == "forbidden"


@pytest.mark.parametrize("resource", ["task", "session", "launch", "ai_work"])
async def test_inconsistent_task_and_session_links_are_refused(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    db_session: AsyncSession,
    resource: str,
) -> None:
    first = await _linked_body(db_session, project, machine[0], agent)
    other = await _linked_body(db_session, project, machine[0], agent)
    field = {
        "task": "task_id",
        "session": "session_id",
        "launch": "task_launch_id",
        "ai_work": "ai_work_id",
    }[resource]
    first[field] = other[field]
    denied = await _post(client, auth_headers, first)
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["error_code"] == "invalid_usage_link"


async def test_cached_replay_revalidates_link_ownership(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    agent: AgentModel,
    db_session: AsyncSession,
) -> None:
    body = await _linked_body(db_session, project, machine[0], agent)
    key = str(uuid.uuid4())
    created = await _post(client, auth_headers, body, key=key)
    assert created.status_code == 201, created.text
    linked = await db_session.get(WorkSessionModel, uuid.UUID(body["session_id"]))
    assert linked is not None
    linked.machine_id = other_machine[0].id
    await db_session.commit()
    replay = await _post(client, auth_headers, body, key=key)
    assert replay.status_code == 403, replay.text


async def test_listing_filters_limits_and_updated_since(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    db_session: AsyncSession,
) -> None:
    body = await _linked_body(db_session, project, machine[0], agent)
    created = await _post(client, auth_headers, body)
    assert created.status_code == 201, created.text
    other = await _post(client, auth_headers, _entry(project.id, machine[0].id))
    assert other.status_code == 201, other.text
    for field in ("task_id", "session_id", "task_launch_id"):
        response = await client.get(
            "/api/v1/usage", params={field: body[field]}, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert [entry["id"] for entry in response.json()] == [created.json()["id"]]
    response = await client.get("/api/v1/usage", params={"limit": 1}, headers=auth_headers)
    assert response.status_code == 200 and len(response.json()) == 1
    response = await client.get("/api/v1/usage", params={"limit": 501}, headers=auth_headers)
    assert response.status_code == 422
    future = datetime.now(UTC) + timedelta(days=1)
    row = await db_session.get(UsageLedgerEntryModel, uuid.UUID(created.json()["id"]))
    assert row is not None
    row.updated_at = future
    await db_session.commit()
    response = await client.get(
        "/api/v1/usage", params={"since": future.isoformat()}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert [entry["id"] for entry in response.json()] == [created.json()["id"]]
    response = await client.get(
        "/api/v1/usage", params={"since": "2026-10-11T00:00:00"}, headers=auth_headers
    )
    assert response.status_code == 422


async def test_launch_credential_usage_is_bound_to_exact_task_and_launch_before_replay(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, launch_id, _ = await _accepted_launch(client, auth_headers, machine)
    ephemeral = await _credential(client, auth_headers, launch_id)
    launch = await db_session.get(TaskLaunchModel, uuid.UUID(launch_id))
    assert launch is not None
    body = _entry(project_id, machine[0].id, task_id=str(launch.task_id), task_launch_id=launch_id)
    created = await _post(client, ephemeral, body, key=str(uuid.uuid4()))
    assert created.status_code == 201, created.text
    correction = _correction(created.json())
    corrected = await _post(client, ephemeral, correction, key=str(uuid.uuid4()), correction=True)
    assert corrected.status_code == 200, corrected.text
    assert (await client.get("/api/v1/usage", headers=ephemeral)).status_code == 403
    for field in ("task_id", "task_launch_id"):
        unbound = _entry(
            project_id, machine[0].id, task_id=str(launch.task_id), task_launch_id=launch_id
        )
        unbound[field] = None
        key = str(uuid.uuid4())
        durable = await _post(client, auth_headers, unbound, key=key)
        assert durable.status_code == 201, durable.text
        denied = await _post(client, ephemeral, unbound, key=key)
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"]["error_code"] == "launch_credential_scope"
        correction = _correction(durable.json())
        key = str(uuid.uuid4())
        corrected = await _post(client, auth_headers, correction, key=key, correction=True)
        assert corrected.status_code == 200, corrected.text
        denied = await _post(client, ephemeral, correction, key=key, correction=True)
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"]["error_code"] == "launch_credential_scope"


@dataclass
class ConcurrentUsage:
    client: AsyncClient
    factory: async_sessionmaker[AsyncSession]
    headers: dict[str, str]
    body: dict[str, Any]
    keys: list[str]


@pytest_asyncio.fixture
async def concurrent_usage(engine: AsyncEngine) -> AsyncIterator[ConcurrentUsage]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        user = await provisioning_service.create_user(
            setup, "Usage concurrency", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(setup, user.id, "usage-race")
        project = await projects_service.create_project(
            setup, f"usage-race-{uuid.uuid4().hex[:8]}", "Usage race", None, creator=None
        )

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def _warm() -> None:
        async with factory() as session:
            await session.execute(text("SELECT 1"))

    keys = [str(uuid.uuid4()) for _ in range(8)]
    previous = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = _session
    try:
        await asyncio.gather(*(_warm() for _ in range(4)))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield ConcurrentUsage(
                client,
                factory,
                {"Authorization": f"Bearer {token}"},
                _entry(project.id, machine.id, tokens_in={"value": 100, "coverage": "measured"}),
                keys,
            )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = previous
        async with factory() as cleanup:
            await cleanup.execute(
                delete(UsageLedgerEntryModel).where(UsageLedgerEntryModel.project_id == project.id)
            )
            await cleanup.execute(
                delete(IdempotencyKeyModel).where(IdempotencyKeyModel.idempotency_key.in_(keys))
            )
            await cleanup.execute(delete(EventModel).where(EventModel.project_id == project.id))
            await cleanup.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup.commit()


@pytest.mark.parametrize("same_key", [False, True])
async def test_concurrent_creation_uses_independent_transactions_and_one_row(
    concurrent_usage: ConcurrentUsage,
    same_key: bool,
) -> None:
    ctx = concurrent_usage
    responses = await asyncio.gather(
        *(
            _post(ctx.client, ctx.headers, ctx.body, key=ctx.keys[0 if same_key else i])
            for i in range(4)
        )
    )
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    async with ctx.factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(UsageLedgerEntryModel).where(
                        UsageLedgerEntryModel.machine_id == uuid.UUID(ctx.body["machine_id"])
                    )
                )
            ).all()
        )
        assert len(rows) == 1 and rows[0].tokens_in == 100


@pytest.mark.parametrize("same_key", [False, True])
async def test_concurrent_corrections_increment_once_and_never_sum_snapshots(
    concurrent_usage: ConcurrentUsage,
    same_key: bool,
) -> None:
    ctx = concurrent_usage
    created = await _post(ctx.client, ctx.headers, ctx.body, key=ctx.keys[0])
    assert created.status_code == 201, created.text
    correction = _correction(created.json(), tokens_in={"value": 125, "coverage": "measured"})
    responses = await asyncio.gather(
        *(
            _post(
                ctx.client,
                ctx.headers,
                correction,
                key=ctx.keys[1 if same_key else i + 1],
                correction=True,
            )
            for i in range(4)
        )
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == ([200] * 4 if same_key else [200, 409, 409, 409]), [
        r.text for r in responses
    ]
    for response in responses:
        if response.status_code == 409:
            assert response.json()["detail"] == {
                "error_code": "version_conflict",
                "server_version": 2,
            }
    async with ctx.factory() as session:
        row = await session.get(UsageLedgerEntryModel, uuid.UUID(created.json()["id"]))
        assert row is not None and row.version == 2 and row.tokens_in == 125


@pytest.mark.parametrize("correction", [False, True])
async def test_crash_before_idempotency_completion_can_be_replayed_without_lost_correction(
    concurrent_usage: ConcurrentUsage,
    monkeypatch: pytest.MonkeyPatch,
    correction: bool,
) -> None:
    ctx = concurrent_usage
    body = ctx.body
    if correction:
        created = await _post(ctx.client, ctx.headers, body, key=ctx.keys[0])
        assert created.status_code == 201, created.text
        body = _correction(created.json(), tokens_in={"value": 125, "coverage": "measured"})

    async def _crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("crash before idempotency completion")

    with monkeypatch.context() as patch:
        patch.setattr(idempotency_service, "_complete", _crash)
        with pytest.raises(RuntimeError, match="crash before idempotency completion"):
            await _post(ctx.client, ctx.headers, body, key=ctx.keys[1], correction=correction)
    async with ctx.factory() as session:
        row = await session.scalar(
            select(UsageLedgerEntryModel).where(
                UsageLedgerEntryModel.machine_id == uuid.UUID(ctx.body["machine_id"])
            )
        )
        if correction:
            assert row is not None and row.version == 1 and row.tokens_in == 100
        else:
            assert row is None
        reservation = await session.scalar(
            select(IdempotencyKeyModel).where(IdempotencyKeyModel.idempotency_key == ctx.keys[1])
        )
        assert reservation is not None
        reservation.created_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    replay = await _post(ctx.client, ctx.headers, body, key=ctx.keys[1], correction=correction)
    assert replay.status_code == (200 if correction else 201), replay.text
    assert replay.json()["version"] == (2 if correction else 1)
    assert replay.json()["tokens_in"]["value"] == (125 if correction else 100)
    duplicate = await _post(ctx.client, ctx.headers, body, key=ctx.keys[1], correction=correction)
    assert duplicate.json() == replay.json()
