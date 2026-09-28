from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
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
        display_name="Other",
        email=f"{uuid.uuid4()}@example.test",
        role="developer",
        email_verified_at=datetime.now(UTC),
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


async def test_release_task_honours_optional_if_match_version(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    created = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Versioned release"},
    )
    task_id = created.json()["id"]
    claimed = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    version = claimed.json()["version"]

    stale = await client.post(
        f"/api/v1/tasks/{task_id}/release",
        headers={**auth_headers, "If-Match-Version": str(version - 1)},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {"error_code": "version_conflict", "server_version": version}
    still_held = await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert still_held.json()["claimed_by_machine_id"] is not None

    released = await client.post(
        f"/api/v1/tasks/{task_id}/release",
        headers={**auth_headers, "If-Match-Version": str(version)},
    )
    assert released.status_code == 200
    assert released.json()["claimed_by_machine_id"] is None
    assert released.json()["version"] == version + 1


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
        display_name="Other",
        email=f"{uuid.uuid4()}@example.test",
        role="developer",
        email_verified_at=datetime.now(UTC),
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


async def test_list_tasks_most_recently_updated_first(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    """A task touched last (e.g. just claimed) must lead the first page, not
    drift past it in Postgres physical order."""
    ids = []
    for title in ("old", "claimed", "middle"):
        created = await client.post(
            "/api/v1/tasks",
            headers=auth_headers,
            json={"project_id": str(project.id), "title": title},
        )
        ids.append(uuid.UUID(created.json()["id"]))
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for offset_min, task_id in zip((0, 20, 10), ids, strict=True):
        await db_session.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id)
            .values(updated_at=base + timedelta(minutes=offset_min))
        )
    await db_session.flush()

    params = {"project_id": str(project.id)}
    listing = await client.get("/api/v1/tasks", headers=auth_headers, params=params)
    assert [t["title"] for t in listing.json()] == ["claimed", "middle", "old"]

    first = await client.get("/api/v1/tasks", headers=auth_headers, params={**params, "limit": 1})
    assert [t["title"] for t in first.json()] == ["claimed"]


async def test_claim_same_machine_is_a_noop(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    """Re-claiming a task this machine already holds with the same agent
    changes nothing: no version bump, no duplicate `task.started`. That is
    what makes a replayed start safe without an Idempotency-Key."""
    create = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Idempotent claim"},
    )
    task_id = create.json()["id"]

    first = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    second = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["version"] == first.json()["version"]
    assert second.json()["claimed_by_machine_id"] == first.json()["claimed_by_machine_id"]
    assert await _task_event_types(client, auth_headers, task_id) == [
        "task.created",
        "task.started",
    ]


async def test_claim_idempotency_key_replays_the_original(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    create = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Replayable claim"},
    )
    task_id = create.json()["id"]
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}

    first = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=headers)
    second = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert await _task_event_types(client, auth_headers, task_id) == [
        "task.created",
        "task.started",
    ]


async def test_claim_idempotency_key_is_scoped_to_the_task(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    """The same key on two different tasks is not a payload mismatch: the
    reservation is scoped by endpoint, which carries the task id."""
    task_ids = []
    for title in ("first", "second"):
        created = await client.post(
            "/api/v1/tasks",
            headers=auth_headers,
            json={"project_id": str(project.id), "title": title},
        )
        task_ids.append(created.json()["id"])
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}

    for task_id in task_ids:
        response = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == "in_progress"


async def test_reclaim_after_completion_is_a_real_claim(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    """The no-op only covers a task still `in_progress`. Completing keeps the
    claim recorded, so re-claiming afterwards is a real (re)claim: status
    back to `in_progress`, version bump, and a second `task.started`."""
    create = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Resumed after done"},
    )
    task_id = create.json()["id"]
    claimed = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    completed = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers={**auth_headers, "If-Match-Version": str(claimed.json()["version"])},
        json={"status": "completed"},
    )
    assert completed.status_code == 200

    reclaimed = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    assert reclaimed.status_code == 200
    assert reclaimed.json()["status"] == "in_progress"
    assert reclaimed.json()["version"] > completed.json()["version"]
    assert await _task_event_types(client, auth_headers, task_id) == [
        "task.created",
        "task.started",
        "task.completed",
        "task.started",
    ]
