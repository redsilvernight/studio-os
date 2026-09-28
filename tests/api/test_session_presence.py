"""Session presence (C1, DEC-0157): `last_activity_at` is written by
session-attached activity, `status` and `expires_at` are derived at read
with configurable thresholds — never stored, never a heartbeat. Needs the
real Postgres test DB (migration 0020)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import sessions as sessions_service
from studio_api.settings import get_settings

SESSIONS = "/api/v1/sessions"


async def _task_id(client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel) -> str:
    created = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "presence task"},
    )
    assert created.status_code == 201
    return str(created.json()["id"])


async def _start(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    task_id: str,
) -> dict:
    machine_model, _ = machine
    response = await client.post(
        SESSIONS,
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"task_id": task_id, "machine_id": str(machine_model.id), "agent_id": None},
    )
    assert response.status_code == 201
    return response.json()


async def _backdate(db_session: AsyncSession, session_id: str, age: timedelta) -> None:
    await db_session.execute(
        update(WorkSessionModel)
        .where(WorkSessionModel.id == uuid.UUID(session_id))
        .values(last_activity_at=datetime.now(UTC) - age)
    )
    await db_session.commit()


async def test_start_sets_activity_and_active_status(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    settings = get_settings()
    task_id = await _task_id(client, auth_headers, project)
    body = await _start(client, auth_headers, machine, task_id)
    assert body["last_activity_at"] == body["started_at"]
    assert body["status"] == "active"
    started = datetime.fromisoformat(body["started_at"])
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires - started == timedelta(seconds=settings.session_expire_after_seconds)


async def test_idle_and_expired_are_derived_at_read(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    settings = get_settings()
    task_id = await _task_id(client, auth_headers, project)
    body = await _start(client, auth_headers, machine, task_id)

    await _backdate(
        db_session, body["id"], timedelta(seconds=settings.session_idle_after_seconds + 60)
    )
    listing = await client.get(SESSIONS, headers=auth_headers, params={"task_id": task_id})
    assert listing.status_code == 200
    assert listing.json()[0]["status"] == "idle"

    await _backdate(
        db_session, body["id"], timedelta(seconds=settings.session_expire_after_seconds + 60)
    )
    listing = await client.get(SESSIONS, headers=auth_headers, params={"task_id": task_id})
    row = listing.json()[0]
    assert row["status"] == "expired"
    # Still present, not closed: effective closing is L2 (l2-resume).
    activity = datetime.fromisoformat(row["last_activity_at"])
    assert datetime.fromisoformat(row["expires_at"]) - activity == timedelta(
        seconds=settings.session_expire_after_seconds
    )


async def test_end_marks_ended_with_no_expiry(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    task_id = await _task_id(client, auth_headers, project)
    body = await _start(client, auth_headers, machine, task_id)
    await _backdate(db_session, body["id"], timedelta(hours=1))

    ended = await client.patch(f"{SESSIONS}/{body['id']}/end", headers=auth_headers)
    assert ended.status_code == 200
    row = ended.json()
    assert row["status"] == "ended"
    assert row["expires_at"] is None
    assert row["ended_at"] is not None
    # Ending is activity: the touch landed on the end, not the backdate.
    assert datetime.fromisoformat(row["last_activity_at"]) >= datetime.fromisoformat(
        row["ended_at"]
    ) - timedelta(seconds=5)


async def test_touch_session_updates_activity(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    task_id = await _task_id(client, auth_headers, project)
    body = await _start(client, auth_headers, machine, task_id)
    await _backdate(db_session, body["id"], timedelta(hours=2))

    touched = await sessions_service.touch_session(db_session, uuid.UUID(body["id"]))
    assert touched is not None
    assert datetime.now(UTC) - touched.last_activity_at < timedelta(seconds=60)
    assert await sessions_service.touch_session(db_session, uuid.uuid4()) is None
