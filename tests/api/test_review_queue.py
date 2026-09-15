from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel


async def test_empty_review_queue(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    response = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "generated_at": response.json()["generated_at"]}


async def test_review_queue_aggregates_all_three_kinds(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
    machine: tuple[MachineModel, str],
) -> None:
    ai_work = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": str(agent.id),
            "summary": "Needs review",
        },
    )
    work_id = ai_work.json()["id"]
    await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "review_requested"}
    )

    machine_model, _ = machine
    await client.post(
        "/api/v1/decisions",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "title": "Use SSE for /stream",
            "body": "Server-Sent Events over WebSocket.",
            "proposed_by_type": "agent",
            "proposed_by_id": str(machine_model.id),
        },
    )

    await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "src/conflict.py",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "src/conflict.py",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )

    response = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    kinds = {item["kind"] for item in items}
    assert kinds == {"ai_work_review", "decision_proposal", "resource_conflict"}
    assert len(items) == 3

    conflict_item = next(item for item in items if item["kind"] == "resource_conflict")
    assert conflict_item["resource_path"] == "src/conflict.py"


async def test_review_queue_sorted_by_requested_at_descending(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={"project_id": str(project.id), "agent_id": str(agent.id), "summary": "First"},
    )
    ai_work = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={"project_id": str(project.id), "agent_id": str(agent.id), "summary": "Second"},
    )
    first_id = (
        await client.get(
            "/api/v1/ai-work", headers=auth_headers, params={"project_id": str(project.id)}
        )
    ).json()[0]["id"]
    second_id = ai_work.json()["id"]
    await client.patch(
        f"/api/v1/ai-work/{first_id}", headers=auth_headers, json={"status": "review_requested"}
    )
    await client.patch(
        f"/api/v1/ai-work/{second_id}", headers=auth_headers, json={"status": "review_requested"}
    )

    response = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    items = response.json()["items"]
    assert len(items) == 2
    requested_at_values = [item["requested_at"] for item in items]
    assert requested_at_values == sorted(requested_at_values, reverse=True)


async def test_review_queue_filters_by_project(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
    db_session: AsyncSession,
) -> None:
    from studio_api.services import projects as projects_service

    other_project = await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Other Project", None
    )

    ai_work = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={"project_id": str(project.id), "agent_id": str(agent.id), "summary": "In scope"},
    )
    work_id = ai_work.json()["id"]
    await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "review_requested"}
    )

    response = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(other_project.id)}
    )
    assert response.json()["items"] == []


async def test_review_queue_conflict_window_excludes_old_events(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    old_event = EventModel(
        id=uuid.uuid4(),
        event_type="resource.conflict",
        project_id=project.id,
        actor_type="system",
        actor_id=uuid.uuid4(),
        client_timestamp=datetime.now(UTC) - timedelta(hours=48),
        server_timestamp=datetime.now(UTC) - timedelta(hours=48),
        payload={"resource_path": "old/stale.py"},
    )
    db_session.add(old_event)
    await db_session.flush()

    within_window = await client.get(
        "/api/v1/review-queue",
        headers=auth_headers,
        params={"project_id": str(project.id), "conflict_window_hours": 72},
    )
    assert len(within_window.json()["items"]) == 1

    outside_window = await client.get(
        "/api/v1/review-queue",
        headers=auth_headers,
        params={"project_id": str(project.id), "conflict_window_hours": 24},
    )
    assert outside_window.json()["items"] == []


async def test_ai_work_leaves_review_queue_once_resolved(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    ai_work = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={"project_id": str(project.id), "agent_id": str(agent.id), "summary": "Resolve me"},
    )
    work_id = ai_work.json()["id"]
    await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "review_requested"}
    )

    before = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len(before.json()["items"]) == 1

    await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=admin_auth_headers, json={"status": "approved"}
    )

    after = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert after.json()["items"] == []


async def test_proposed_decision_stays_in_queue_indefinitely(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    """No transition endpoint exists for decisions (DEC-0041's review scope is
    AI work only) — a proposed decision never leaves the queue via this API,
    which is expected, not a bug."""
    machine_model, _ = machine
    await client.post(
        "/api/v1/decisions",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "title": "Never resolved",
            "body": "Body",
            "proposed_by_type": "agent",
            "proposed_by_id": str(machine_model.id),
        },
    )

    response = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "decision_proposal"
