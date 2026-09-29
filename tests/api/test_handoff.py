"""L3 handoff remediation (DEC-0163): closing in one call releases every
claim with its `resource.released` event, links `ai_work` to the session,
converges on retry, and authorizes before the idempotency short-circuit.
Needs the real Postgres test DB."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.work_session import WorkSessionModel


async def _task(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> dict[str, object]:
    created = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "handoff task"},
    )
    assert created.status_code == 201
    return created.json()  # type: ignore[no-any-return]


async def _claim_task(client: AsyncClient, auth_headers: dict[str, str], task_id: str) -> None:
    claimed = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    assert claimed.status_code == 200


async def _task_version(client: AsyncClient, auth_headers: dict[str, str], task_id: str) -> int:
    """Fresh optimistic-concurrency version: claiming bumps it, so the
    creation payload's version is stale by handoff time."""
    response = await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert response.status_code == 200
    return response.json()["version"]  # type: ignore[no-any-return]


async def _resource_claim(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel, task_id: str
) -> str:
    created = await client.post(
        "/api/v1/claims",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "task_id": task_id,
            "resource_path": "scenes/level_01.tscn",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    assert created.status_code == 201
    return created.json()["id"]  # type: ignore[no-any-return]


async def _session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    task_id: str,
) -> str:
    machine_model, _ = machine
    created = await client.post(
        "/api/v1/sessions",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "task_id": task_id,
            "machine_id": str(machine_model.id),
            "agent_id": str(agent.id),
        },
    )
    assert created.status_code == 201
    return created.json()["id"]  # type: ignore[no-any-return]


async def _events(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> list[dict[str, object]]:
    response = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


async def test_handoff_releases_claims_logs_ai_work_and_ends_session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    await _claim_task(client, auth_headers, str(task["id"]))
    claim_id = await _resource_claim(client, auth_headers, project, str(task["id"]))
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))
    version = await _task_version(client, auth_headers, str(task["id"]))

    handoff = await client.post(
        "/api/v1/handoff",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "session_id": session_id,
            "expected_version": version,
            "task_status": {"status": "completed"},
            "agent_id": str(agent.id),
            "summary": "Close it",
        },
    )
    assert handoff.status_code == 200
    result = handoff.json()
    assert result["task_status"] == "completed"
    assert result["released_claims"] == [claim_id]
    assert result["ai_work_id"] is not None

    claims = await client.get(
        "/api/v1/claims", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert next(c for c in claims.json() if c["id"] == claim_id)["status"] == "released"

    work = await client.get(
        "/api/v1/ai-work", headers=auth_headers, params={"project_id": str(project.id)}
    )
    entry = next(w for w in work.json() if w["id"] == result["ai_work_id"])
    assert entry["session_id"] == session_id

    sessions = await client.get(
        "/api/v1/sessions",
        headers=auth_headers,
        params={"task_id": str(task["id"]), "open": "true"},
    )
    assert sessions.json() == []

    released = [
        e
        for e in await _events(client, auth_headers, project)
        if e["event_type"] == "resource.released"
    ]
    assert {e["payload"]["claim_id"] for e in released} >= {claim_id}


async def test_handoff_replay_same_key_returns_original_without_duplicate_work(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    await _claim_task(client, auth_headers, str(task["id"]))
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))
    version = await _task_version(client, auth_headers, str(task["id"]))
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {
        "project_id": str(project.id),
        "session_id": session_id,
        "expected_version": version,
        "task_status": {"status": "completed"},
        "agent_id": str(agent.id),
        "summary": "Replay me",
    }
    first = await client.post("/api/v1/handoff", headers={**auth_headers, **key}, json=body)
    second = await client.post("/api/v1/handoff", headers={**auth_headers, **key}, json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    work = await client.get(
        "/api/v1/ai-work", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len(work.json()) == 1


async def test_handoff_replay_different_body_conflicts(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    await _claim_task(client, auth_headers, str(task["id"]))
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {
        "project_id": str(project.id),
        "session_id": session_id,
        "expected_version": task["version"],
        "agent_id": str(agent.id),
        "summary": "First body",
    }
    first = await client.post("/api/v1/handoff", headers={**auth_headers, **key}, json=body)
    assert first.status_code == 200

    conflict = await client.post(
        "/api/v1/handoff",
        headers={**auth_headers, **key},
        json={**body, "summary": "Other body"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"


async def test_handoff_authorizes_before_idempotency_replay(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    await _claim_task(client, auth_headers, str(task["id"]))
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {"project_id": str(project.id), "session_id": session_id}
    first = await client.post("/api/v1/handoff", headers={**auth_headers, **key}, json=body)
    assert first.status_code == 200

    replay = await client.post(
        "/api/v1/handoff", headers={**readonly_auth_headers, **key}, json=body
    )
    assert replay.status_code == 403


async def test_handoff_requires_version_with_status_and_types_ai_work_status(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    await _claim_task(client, auth_headers, str(task["id"]))
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))
    version = await _task_version(client, auth_headers, str(task["id"]))

    missing_version = await client.post(
        "/api/v1/handoff",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "session_id": session_id,
            "task_status": {"status": "completed"},
        },
    )
    assert missing_version.status_code == 422

    bad_status = await client.post(
        "/api/v1/handoff",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "session_id": session_id,
            "task_status": {"status": "completed"},
            "expected_version": version,
            "agent_id": str(agent.id),
            "summary": "Bad status",
            "ai_work_status": "shipped",
        },
    )
    assert bad_status.status_code == 422


async def test_handoff_retry_without_key_converges_after_partial_success(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    await _claim_task(client, auth_headers, str(task["id"]))
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))
    version = await _task_version(client, auth_headers, str(task["id"]))
    body = {
        "project_id": str(project.id),
        "session_id": session_id,
        "expected_version": version,
        "task_status": {"status": "completed"},
        "agent_id": str(agent.id),
        "summary": "Converge me",
    }
    first = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert first.status_code == 200

    retry = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert retry.status_code == 200
    assert retry.json()["ai_work_id"] == first.json()["ai_work_id"]
    assert retry.json()["released_claims"] == []


async def test_ai_work_rejects_session_from_another_task(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    other = await _task(client, auth_headers, project)
    session_id = await _session(client, auth_headers, machine, agent, str(other["id"]))

    response = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "task_id": str(task["id"]),
            "agent_id": str(agent.id),
            "session_id": session_id,
            "summary": "Foreign session",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "invalid_session"


async def test_end_session_releases_claims_and_emits_events(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    await _claim_task(client, auth_headers, str(task["id"]))
    claim_id = await _resource_claim(client, auth_headers, project, str(task["id"]))
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))

    ended = await client.patch(f"/api/v1/sessions/{session_id}/end", headers=auth_headers)
    assert ended.status_code == 200

    claims = await client.get(
        "/api/v1/claims", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert next(c for c in claims.json() if c["id"] == claim_id)["status"] == "released"

    released = [
        e
        for e in await _events(client, auth_headers, project)
        if e["event_type"] == "resource.released"
    ]
    assert {e["payload"]["claim_id"] for e in released} >= {claim_id}


async def test_handoff_updates_preexisting_started_ai_work(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    """R1: a `started` entry already linked to the session is updated with
    the handoff's summary, final status and files — never silently reused,
    never duplicated."""
    task = await _task(client, auth_headers, project)
    await _claim_task(client, auth_headers, str(task["id"]))
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))
    started = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "task_id": str(task["id"]),
            "agent_id": str(agent.id),
            "session_id": session_id,
            "summary": "Work in progress",
        },
    )
    assert started.status_code == 201
    assert started.json()["status"] == "started"

    version = await _task_version(client, auth_headers, str(task["id"]))
    handoff = await client.post(
        "/api/v1/handoff",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "session_id": session_id,
            "expected_version": version,
            "task_status": {"status": "completed"},
            "agent_id": str(agent.id),
            "summary": "Close it",
            "changed_files": ["a.py"],
            "tests_run": ["pytest"],
        },
    )
    assert handoff.status_code == 200
    assert handoff.json()["ai_work_id"] == started.json()["id"]

    work = await client.get(
        "/api/v1/ai-work", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len(work.json()) == 1
    entry = work.json()[0]
    assert entry["summary"] == "Close it"
    assert entry["status"] == "completed"
    assert entry["changed_files"] == ["a.py"]
    assert entry["tests_run"] == ["pytest"]
    assert entry["session_id"] == session_id


async def test_end_already_ended_session_still_releases_claims(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    """R2: the L3 fallback converges even when a previous partial failure
    left the session ended with claims still active."""
    task = await _task(client, auth_headers, project)
    await _claim_task(client, auth_headers, str(task["id"]))
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))
    ended = await client.patch(f"/api/v1/sessions/{session_id}/end", headers=auth_headers)
    assert ended.status_code == 200

    claim_id = await _resource_claim(client, auth_headers, project, str(task["id"]))
    retry = await client.patch(f"/api/v1/sessions/{session_id}/end", headers=auth_headers)
    assert retry.status_code == 200

    claims = await client.get(
        "/api/v1/claims", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert next(c for c in claims.json() if c["id"] == claim_id)["status"] == "released"


async def test_update_ai_work_rejects_unknown_and_foreign_session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    other = await _task(client, auth_headers, project)
    foreign_session = await _session(client, auth_headers, machine, agent, str(other["id"]))
    created = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "task_id": str(task["id"]),
            "agent_id": str(agent.id),
            "summary": "Patch me",
        },
    )
    work_id = created.json()["id"]

    unknown = await client.patch(
        f"/api/v1/ai-work/{work_id}",
        headers=auth_headers,
        json={"session_id": str(uuid.uuid4())},
    )
    assert unknown.status_code == 404

    foreign = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"session_id": foreign_session}
    )
    assert foreign.status_code == 409
    assert foreign.json()["detail"]["error_code"] == "invalid_session"


async def test_session_delete_nulls_linked_ai_work_session_id(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    """Migration 0022: the FK `ondelete=SET NULL` keeps the work entry when
    its session row disappears."""
    task = await _task(client, auth_headers, project)
    session_id = await _session(client, auth_headers, machine, agent, str(task["id"]))
    created = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "task_id": str(task["id"]),
            "agent_id": str(agent.id),
            "session_id": session_id,
            "summary": "Survives",
        },
    )
    work_id = created.json()["id"]

    work_session = await db_session.get(WorkSessionModel, uuid.UUID(session_id))
    assert work_session is not None
    await db_session.delete(work_session)
    await db_session.commit()

    work = await db_session.get(AIWorkLogModel, uuid.UUID(work_id))
    assert work is not None
    assert work.session_id is None
