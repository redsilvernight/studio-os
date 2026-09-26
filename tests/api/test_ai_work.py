from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel


async def test_create_update_and_list_ai_work(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    created = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": str(agent.id),
            "summary": "Investigate claim TTL bug",
        },
    )
    assert created.status_code == 201
    entry = created.json()
    assert entry["status"] == "started"
    assert entry["changed_files"] == []

    updated = await client.patch(
        f"/api/v1/ai-work/{entry['id']}",
        headers=auth_headers,
        json={
            "status": "completed",
            "changed_files": ["services/api/src/studio_api/services/claims.py"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"
    assert updated.json()["changed_files"] == ["services/api/src/studio_api/services/claims.py"]

    listing = await client.get(
        "/api/v1/ai-work", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len(listing.json()) == 1


async def test_update_unknown_ai_work_returns_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.patch(
        f"/api/v1/ai-work/{uuid.uuid4()}", headers=auth_headers, json={"status": "failed"}
    )
    assert response.status_code == 404


async def test_create_ai_work_emits_started_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    created = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": str(agent.id),
            "summary": "Emit started event",
        },
    )
    assert created.status_code == 201
    work_id = created.json()["id"]

    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    started = [e for e in events.json() if e["event_type"] == "ai_work.started"]
    assert len(started) == 1
    assert started[0]["payload"]["ai_work_id"] == work_id
    assert started[0]["actor_type"] == "agent"
    assert started[0]["actor_id"] == str(agent.id)


async def test_idempotent_replay_of_create_ai_work_does_not_duplicate_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    body = {
        "project_id": str(project.id),
        "agent_id": str(agent.id),
        "summary": "Replay me",
    }
    headers = {**auth_headers, "Idempotency-Key": "ai-work-replay-1"}
    first = await client.post("/api/v1/ai-work", headers=headers, json=body)
    second = await client.post("/api/v1/ai-work", headers=headers, json=body)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    started = [e for e in events.json() if e["event_type"] == "ai_work.started"]
    assert len(started) == 1


async def test_update_ai_work_completed_emits_event_once(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    created = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": str(agent.id),
            "summary": "Complete me",
        },
    )
    work_id = created.json()["id"]

    first_patch = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "completed"}
    )
    assert first_patch.status_code == 200

    second_patch = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "completed"}
    )
    assert second_patch.status_code == 200

    summary_only_patch = await client.patch(
        f"/api/v1/ai-work/{work_id}",
        headers=auth_headers,
        json={"summary": "Complete me (edited)"},
    )
    assert summary_only_patch.status_code == 200

    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    completed = [e for e in events.json() if e["event_type"] == "ai_work.completed"]
    assert len(completed) == 1


async def test_review_resolution_requires_admin_and_review_requested_status(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    created = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": str(agent.id),
            "summary": "Needs review",
        },
    )
    work_id = created.json()["id"]

    premature = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=admin_auth_headers, json={"status": "approved"}
    )
    assert premature.status_code == 409
    assert premature.json()["detail"]["error_code"] == "invalid_status_transition"

    review = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "review_requested"}
    )
    assert review.status_code == 200

    self_approve = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "approved"}
    )
    assert self_approve.status_code == 403
    assert self_approve.json()["detail"]["error_code"] == "forbidden"

    approved = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=admin_auth_headers, json={"status": "approved"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    approved_events = [e for e in events.json() if e["event_type"] == "ai_work.approved"]
    assert len(approved_events) == 1
    assert approved_events[0]["actor_type"] == "user"


async def test_changes_requested_resolution_symmetric_to_approved(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    created = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": str(agent.id),
            "summary": "Needs changes",
        },
    )
    work_id = created.json()["id"]

    review = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "review_requested"}
    )
    assert review.status_code == 200

    changes_requested = await client.patch(
        f"/api/v1/ai-work/{work_id}",
        headers=admin_auth_headers,
        json={"status": "changes_requested"},
    )
    assert changes_requested.status_code == 200
    assert changes_requested.json()["status"] == "changes_requested"

    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    changes_events = [e for e in events.json() if e["event_type"] == "ai_work.changes_requested"]
    assert len(changes_events) == 1
    assert changes_events[0]["actor_type"] == "user"


async def test_create_ai_work_completed_in_one_call_with_idempotent_replay(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    """Additive create fields: finished work is logged in one POST, and an
    idempotent replay returns the same entry without duplicating events."""
    body = {
        "project_id": str(project.id),
        "agent_id": str(agent.id),
        "summary": "Finished work",
        "status": "completed",
        "changed_files": ["services/api/src/studio_api/services/ai_work.py"],
        "tests_run": ["tests/api/test_ai_work.py"],
    }
    headers = {**auth_headers, "Idempotency-Key": "ai-work-completed-1"}
    first = await client.post("/api/v1/ai-work", headers=headers, json=body)
    second = await client.post("/api/v1/ai-work", headers=headers, json=body)
    assert first.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    entry = first.json()
    assert entry["status"] == "completed"
    assert entry["ended_at"] is not None
    assert entry["changed_files"] == body["changed_files"]
    assert entry["tests_run"] == body["tests_run"]

    mismatch = await client.post(
        "/api/v1/ai-work", headers=headers, json={**body, "status": "failed"}
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"

    events = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    types = [e["event_type"] for e in events.json()]
    assert types.count("ai_work.started") == 1
    assert types.count("ai_work.completed") == 1


async def test_create_ai_work_refuses_review_resolution_status(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    for target in ("approved", "changes_requested"):
        response = await client.post(
            "/api/v1/ai-work",
            headers=auth_headers,
            json={
                "project_id": str(project.id),
                "agent_id": str(agent.id),
                "summary": "Self-approve",
                "status": target,
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == "invalid_status_transition"
