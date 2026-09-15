from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel

# UC-1 conformance: an unknown consumer (unknown-harness /
# unknown-provider / unknown-model, no agent_profile, no Agent row)
# authenticates and is authorized by auth_role + ownership only.
#
# Deliberately never uses the `agent` fixture and never sends any
# harness/provider/model/profile metadata: the protocol has no field for
# them, and the server must not require any.

FORBIDDEN_METADATA_KEYS = {
    "harness",
    "provider",
    "model",
    "agent_profile",
}
# NOTE: `agent_kind` is intentionally absent from the set above: it is a
# pre-existing free-form metadata field of the `Agent` contract (TECH/05,
# never an authorization input), not consumer-recognition data.


async def _assert_no_agent_rows(db_session: AsyncSession) -> None:
    count = (await db_session.execute(select(func.count()).select_from(AgentModel))).scalar()
    assert count == 0


async def test_unknown_consumer_full_path_without_agent_row(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    await _assert_no_agent_rows(db_session)

    heartbeat = await client.post(
        "/api/v1/heartbeats",
        headers=auth_headers,
        json={
            "machine_id": str(machine_model.id),
            "client_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert heartbeat.status_code == 200

    created = await client.post(
        "/api/v1/tasks",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"project_id": str(project.id), "title": "Unknown consumer task"},
    )
    assert created.status_code == 201
    task = created.json()
    assert FORBIDDEN_METADATA_KEYS.isdisjoint(task)

    claimed = await client.post(f"/api/v1/tasks/{task['id']}/claim", headers=auth_headers)
    assert claimed.status_code == 200

    released = await client.post(f"/api/v1/tasks/{task['id']}/release", headers=auth_headers)
    assert released.status_code == 200

    event_id = uuid.uuid4()
    posted = await client.post(
        "/api/v1/events",
        headers=auth_headers,
        json={
            "event_id": str(event_id),
            "event_type": "task.updated",
            "project_id": str(project.id),
            "task_id": task["id"],
            "actor_type": "user",
            "actor_id": str(machine_model.owner_user_id),
            "client_timestamp": datetime.now(UTC).isoformat(),
            "payload": {"note": "unknown harness at work"},
        },
    )
    assert posted.status_code == 200
    envelope = posted.json()
    assert FORBIDDEN_METADATA_KEYS.isdisjoint(envelope)

    replayed = await client.post(
        "/api/v1/events",
        headers=auth_headers,
        json={
            "event_id": str(event_id),
            "event_type": "task.updated",
            "project_id": str(project.id),
            "task_id": task["id"],
            "actor_type": "user",
            "actor_id": str(machine_model.owner_user_id),
            "client_timestamp": datetime.now(UTC).isoformat(),
            "payload": {"note": "replay, same event_id"},
        },
    )
    assert replayed.status_code == 200
    assert replayed.json()["server_timestamp"] == envelope["server_timestamp"]

    system_event = await client.post(
        "/api/v1/events",
        headers=auth_headers,
        json={
            "event_id": str(uuid.uuid4()),
            "event_type": "agent.started",
            "project_id": str(project.id),
            "actor_type": "system",
            "actor_id": str(machine_model.id),
            "client_timestamp": datetime.now(UTC).isoformat(),
            "payload": {},
        },
    )
    assert system_event.status_code == 200

    claim = await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "scripts/uc1_probe.py",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    assert claim.status_code == 201

    decision = await client.post(
        "/api/v1/decisions",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "title": "UC-1 needs no Agent row",
            "body": "auth_role + ownership suffice.",
            "proposed_by_type": "user",
            "proposed_by_id": str(machine_model.owner_user_id),
        },
    )
    assert decision.status_code == 201

    session = await client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={"task_id": task["id"], "machine_id": str(machine_model.id)},
    )
    assert session.status_code == 201
    ended = await client.patch(f"/api/v1/sessions/{session.json()['id']}/end", headers=auth_headers)
    assert ended.status_code == 200

    await _assert_no_agent_rows(db_session)


async def test_unknown_consumer_authorization_is_role_plus_ownership(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _assert_no_agent_rows(db_session)

    denied = await client.post(
        "/api/v1/tasks",
        headers=readonly_auth_headers,
        json={"project_id": str(project.id), "title": "readonly write"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["error_code"] == "forbidden"

    allowed_read = await client.get("/api/v1/tasks", headers=readonly_auth_headers)
    assert allowed_read.status_code == 200

    created = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "ownership probe"},
    )
    task_id = created.json()["id"]
    await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)

    foreign_release = await client.post(
        f"/api/v1/tasks/{task_id}/release", headers=other_auth_headers
    )
    assert foreign_release.status_code == 403
    assert foreign_release.json()["detail"]["error_code"] == "forbidden"

    await _assert_no_agent_rows(db_session)


async def test_unknown_consumer_registers_agent_then_logs_work(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    """CC-1: a consumer with no Agent row materializes its operational
    provenance identity (machine_id server-derived), then uses it for the
    one MUST capability that requires it — worklogs — through the preserved
    DEC-0041 review flow. No harness/provider/model/profile anywhere."""
    machine_model, _ = machine
    await _assert_no_agent_rows(db_session)

    registered = await client.post(
        "/api/v1/agents",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"display_name": "unknown-harness worker"},
    )
    assert registered.status_code == 201
    agent = registered.json()
    assert agent["machine_id"] == str(machine_model.id)
    assert agent["display_name"] == "unknown-harness worker"
    # UC-5 turns these into optional additive metadata: a consumer that
    # sends none gets them null, and the server neither requires nor
    # invents any value.
    for key in FORBIDDEN_METADATA_KEYS:
        assert agent.get(key) is None, f"unexpected {key}: {agent.get(key)!r}"

    spoofed_machine = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={"display_name": "spoof", "machine_id": str(uuid.uuid4())},
    )
    assert spoofed_machine.status_code == 422

    work = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": agent["id"],
            "summary": "Unknown consumer work",
        },
    )
    assert work.status_code == 201
    work_id = work.json()["id"]

    updated = await client.patch(
        f"/api/v1/ai-work/{work_id}",
        headers=auth_headers,
        json={"status": "completed", "tests_run": ["tests/api/test_uc1_unknown_consumer.py"]},
    )
    assert updated.status_code == 200

    requested = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "review_requested"}
    )
    assert requested.status_code == 200

    self_approved = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "approved"}
    )
    assert self_approved.status_code == 403

    approved = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=admin_auth_headers, json={"status": "approved"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


async def test_agent_registration_is_idempotent_replayable_and_role_gated(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    key = str(uuid.uuid4())
    payload = {"display_name": "retry-safe worker", "agent_kind": "free-form"}

    first = await client.post(
        "/api/v1/agents", headers={**auth_headers, "Idempotency-Key": key}, json=payload
    )
    second = await client.post(
        "/api/v1/agents", headers={**auth_headers, "Idempotency-Key": key}, json=payload
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    count = (await db_session.execute(select(func.count()).select_from(AgentModel))).scalar()
    assert count == 1

    mismatch = await client.post(
        "/api/v1/agents",
        headers={**auth_headers, "Idempotency-Key": key},
        json={"display_name": "other"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"

    readonly = await client.post(
        "/api/v1/agents", headers=readonly_auth_headers, json={"display_name": "ro"}
    )
    assert readonly.status_code == 403
    assert readonly.json()["detail"]["error_code"] == "forbidden"


async def test_worklog_provenance_is_machine_owned(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    """An agent_id attached to another machine (or to no row at all) cannot
    produce worklogs as the caller: 409 actor_not_owned (DEC-0035 shape),
    never a silent cross-machine attribution — and registration grants the
    caller no additional right over others' resources."""
    machine_model, _ = machine
    own = await client.post("/api/v1/agents", headers=auth_headers, json={"display_name": "mine"})
    own_agent_id = own.json()["id"]

    foreign = await client.post(
        "/api/v1/ai-work",
        headers=other_auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": own_agent_id,
            "summary": "cross-machine spoof",
        },
    )
    assert foreign.status_code == 409
    assert foreign.json()["detail"]["error_code"] == "actor_not_owned"

    orphan = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": str(uuid.uuid4()),
            "summary": "dangling reference",
        },
    )
    assert orphan.status_code == 409
    assert orphan.json()["detail"]["error_code"] == "actor_not_owned"

    own_work = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": own_agent_id,
            "summary": "legitimate work",
        },
    )
    assert own_work.status_code == 201
