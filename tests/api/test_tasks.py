from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.security import generate_machine_token, hash_token


async def test_create_and_get_task(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    create = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Wire up daemon"},
    )
    assert create.status_code == 201
    task = create.json()
    assert task["status"] == "created"
    assert task["version"] == 1

    fetched = await client.get(f"/api/v1/tasks/{task['id']}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Wire up daemon"


async def test_create_task_idempotency_key_replays_same_task(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    payload = {"project_id": str(project.id), "title": "Idempotent task"}

    first = await client.post("/api/v1/tasks", headers=headers, json=payload)
    second = await client.post("/api/v1/tasks", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listing = await client.get(
        "/api/v1/tasks", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert len(listing.json()) == 1


async def test_update_task_stale_version_returns_409_with_server_version(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    create = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Original"},
    )
    task_id = create.json()["id"]

    ok = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers={**auth_headers, "If-Match-Version": "1"},
        json={"title": "Updated once"},
    )
    assert ok.status_code == 200
    assert ok.json()["version"] == 2

    stale = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers={**auth_headers, "If-Match-Version": "1"},
        json={"title": "Stale write"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["error_code"] == "version_conflict"
    assert stale.json()["detail"]["server_version"] == 2


async def test_claim_by_second_machine_conflicts(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    create = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Contested task"},
    )
    task_id = create.json()["id"]

    claimed = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "in_progress"

    other_user = UserModel(
        display_name="Other", email=f"{uuid.uuid4()}@example.test", role="developer"
    )
    db_session.add(other_user)
    await db_session.flush()
    other_token = generate_machine_token()
    other_machine = MachineModel(
        owner_user_id=other_user.id,
        display_name="other-machine",
        credential_hash=hash_token(other_token),
    )
    db_session.add(other_machine)
    await db_session.flush()

    other_headers = {"Authorization": f"Bearer {other_token}"}
    conflict = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=other_headers)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error_code"] == "already_claimed"

    released = await client.post(f"/api/v1/tasks/{task_id}/release", headers=auth_headers)
    assert released.status_code == 200
    assert released.json()["claimed_by_machine_id"] is None


async def _task_event_types(
    client: AsyncClient, auth_headers: dict[str, str], task_id: str
) -> list[str]:
    response = await client.get("/api/v1/events", headers=auth_headers, params={"task": task_id})
    assert response.status_code == 200
    events = sorted(response.json(), key=lambda event: event["server_timestamp"])
    return [event["event_type"] for event in events]


async def test_task_lifecycle_emits_events(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    create = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Observable task"},
    )
    task_id = create.json()["id"]
    assert await _task_event_types(client, auth_headers, task_id) == ["task.created"]

    claimed = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    assert claimed.status_code == 200
    released = await client.post(f"/api/v1/tasks/{task_id}/release", headers=auth_headers)
    assert released.status_code == 200
    completed = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers={**auth_headers, "If-Match-Version": str(released.json()["version"])},
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    renamed = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers={**auth_headers, "If-Match-Version": str(completed.json()["version"])},
        json={"title": "Renamed"},
    )
    assert renamed.status_code == 200

    assert await _task_event_types(client, auth_headers, task_id) == [
        "task.created",
        "task.started",
        "task.updated",
        "task.completed",
        "task.updated",
    ]

    response = await client.get("/api/v1/events", headers=auth_headers, params={"task": task_id})
    started = next(e for e in response.json() if e["event_type"] == "task.started")
    assert started["project_id"] == str(project.id)
    assert started["payload"]["status"] == "in_progress"
    assert started["payload"]["transition"] == "claimed"
    assert started["payload"]["previous_status"] == "created"


async def test_rejected_claim_emits_no_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    create = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Held task"},
    )
    task_id = create.json()["id"]
    await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)

    other_user = UserModel(
        display_name="Other", email=f"{uuid.uuid4()}@example.test", role="developer"
    )
    db_session.add(other_user)
    await db_session.flush()
    other_token = generate_machine_token()
    db_session.add(
        MachineModel(
            owner_user_id=other_user.id,
            display_name="other-machine",
            credential_hash=hash_token(other_token),
        )
    )
    await db_session.flush()

    conflict = await client.post(
        f"/api/v1/tasks/{task_id}/claim", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert conflict.status_code == 409
    assert await _task_event_types(client, auth_headers, task_id) == [
        "task.created",
        "task.started",
    ]
