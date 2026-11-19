"""Cross-studio project isolation (DEC-0382, lot 2): a project of another
studio is unreadable and unwritable. It answers like an unknown project to a
studio `owner`/`admin` (404 on a single resource, empty collection) and like an
inaccessible project to a `member` (403). Deny by default (`isolation` marker).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.services import provisioning as provisioning_service

pytestmark = pytest.mark.isolation

UNKNOWN = "00000000-0000-0000-0000-000000000000"
FORBIDDEN_READ = {"error_code": "forbidden", "resource": "project", "action": "read"}
FORBIDDEN_WRITE = {"error_code": "forbidden", "resource": "project", "action": "write"}


@dataclass(frozen=True)
class Actor:
    """One User acting in one studio, with its own machine and active-studio
    headers."""

    studio: StudioModel
    user_id: uuid.UUID
    machine: MachineModel
    headers: dict[str, str]


async def _actor(db_session: AsyncSession, studio_role: str) -> Actor:
    studio = StudioModel(slug=f"studio-{uuid.uuid4().hex[:8]}", name="Isolated studio")
    db_session.add(studio)
    await db_session.flush()
    user = await provisioning_service.create_user(
        db_session, "Studio User", f"{uuid.uuid4()}@example.test", "developer"
    )
    db_session.add(StudioMembershipModel(studio_id=studio.id, user_id=user.id, role=studio_role))
    await db_session.flush()
    machine, token = await provisioning_service.create_machine(
        db_session, user.id, f"machine-{uuid.uuid4().hex[:8]}"
    )
    return Actor(
        studio=studio,
        user_id=user.id,
        machine=machine,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Studio-Id": str(studio.id),
        },
    )


async def _create_project(client: AsyncClient, actor: Actor) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={"slug": f"iso-{uuid.uuid4().hex[:8]}", "name": "Isolated"},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _create_task(client: AsyncClient, actor: Actor, project_id: str) -> dict[str, object]:
    response = await client.post(
        "/api/v1/tasks",
        json={"project_id": project_id, "title": "foreign task"},
        headers={**actor.headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _create_claim(client: AsyncClient, actor: Actor, project_id: str) -> dict[str, object]:
    response = await client.post(
        "/api/v1/claims",
        json={
            "project_id": project_id,
            "resource_path": "src/foreign.py",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
        headers={**actor.headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _create_event(client: AsyncClient, actor: Actor, project_id: str) -> str:
    event_id = uuid.uuid4()
    response = await client.post(
        "/api/v1/events",
        json={
            "event_id": str(event_id),
            "event_type": "task.updated",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": str(actor.user_id),
            "client_timestamp": "2026-01-01T00:00:00Z",
            "payload": {},
        },
        headers=actor.headers,
    )
    assert response.status_code == 200, response.text
    return str(event_id)


async def test_listing_only_shows_the_active_studio_projects(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _actor(db_session, "owner")
    foreign = await _actor(db_session, "owner")
    mine = await _create_project(client, owner)
    theirs = await _create_project(client, foreign)

    listed = await client.get("/api/v1/projects", headers=owner.headers)
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [mine]
    assert theirs not in {p["id"] for p in listed.json()}

    foreign_listed = await client.get("/api/v1/projects", headers=foreign.headers)
    assert [p["id"] for p in foreign_listed.json()] == [theirs]


async def test_creation_lands_in_the_active_studio(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _actor(db_session, "owner")
    foreign = await _actor(db_session, "owner")

    created = await _create_project(client, owner)
    project = await db_session.get(ProjectModel, uuid.UUID(created))
    assert project is not None
    assert project.studio_id == owner.studio.id

    foreign_listed = await client.get("/api/v1/projects", headers=foreign.headers)
    assert created not in {p["id"] for p in foreign_listed.json()}


@pytest.mark.parametrize("suffix", ["", "/state"])
async def test_foreign_project_is_404_for_a_manager_and_403_for_a_member(
    client: AsyncClient, db_session: AsyncSession, suffix: str
) -> None:
    owner = await _actor(db_session, "owner")
    member = await _actor(db_session, "member")
    foreign = await _actor(db_session, "owner")
    foreign_project = await _create_project(client, foreign)

    manager = await client.get(f"/api/v1/projects/{foreign_project}{suffix}", headers=owner.headers)
    unknown = await client.get(f"/api/v1/projects/{UNKNOWN}{suffix}", headers=owner.headers)
    assert manager.status_code == unknown.status_code == 404
    assert manager.json()["detail"]["error_code"] == "not_found"

    denied = await client.get(f"/api/v1/projects/{foreign_project}{suffix}", headers=member.headers)
    assert denied.status_code == 403
    assert denied.json()["detail"] == FORBIDDEN_READ


async def test_foreign_project_tasks_are_neither_listed_nor_written(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _actor(db_session, "owner")
    member = await _actor(db_session, "member")
    foreign = await _actor(db_session, "owner")
    foreign_project = await _create_project(client, foreign)
    task = await _create_task(client, foreign, foreign_project)

    listed = await client.get(f"/api/v1/tasks?project_id={foreign_project}", headers=owner.headers)
    assert listed.status_code == 200
    assert task["id"] not in {t["id"] for t in listed.json()}

    created = await client.post(
        "/api/v1/tasks",
        json={"project_id": foreign_project, "title": "leak"},
        headers={**owner.headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 404, created.text

    patched = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "hijacked"},
        headers={**owner.headers, "If-Match-Version": str(task["version"])},
    )
    assert patched.status_code == 404, patched.text

    denied = await client.post(
        "/api/v1/tasks",
        json={"project_id": foreign_project, "title": "leak"},
        headers={**member.headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == FORBIDDEN_WRITE


async def test_foreign_project_events_are_not_listed_or_streamed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _actor(db_session, "owner")
    member = await _actor(db_session, "member")
    foreign = await _actor(db_session, "owner")
    foreign_project = await _create_project(client, foreign)
    event_id = await _create_event(client, foreign, foreign_project)

    listed = await client.get(f"/api/v1/events?project={foreign_project}", headers=owner.headers)
    assert listed.status_code == 200
    assert event_id not in {e["event_id"] for e in listed.json()}

    stream = await client.get(
        f"/api/v1/events/stream?project={foreign_project}", headers=owner.headers
    )
    assert stream.status_code == 404

    denied = await client.get(
        f"/api/v1/events/stream?project={foreign_project}", headers=member.headers
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == FORBIDDEN_READ


async def test_foreign_project_claims_are_neither_listed_nor_released(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _actor(db_session, "owner")
    member = await _actor(db_session, "member")
    foreign = await _actor(db_session, "owner")
    foreign_project = await _create_project(client, foreign)
    claim = await _create_claim(client, foreign, foreign_project)

    listed = await client.get(f"/api/v1/claims?project_id={foreign_project}", headers=owner.headers)
    assert listed.status_code == 200
    assert claim["id"] not in {c["id"] for c in listed.json()}

    released = await client.delete(f"/api/v1/claims/{claim['id']}", headers=owner.headers)
    assert released.status_code == 404, released.text

    created = await client.post(
        "/api/v1/claims",
        json={
            "project_id": foreign_project,
            "resource_path": "src/leak.py",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
        headers={**member.headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 403
    assert created.json()["detail"] == FORBIDDEN_WRITE


async def test_foreign_project_sessions_are_neither_listed_nor_started(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _actor(db_session, "owner")
    member = await _actor(db_session, "member")
    foreign = await _actor(db_session, "owner")
    foreign_project = await _create_project(client, foreign)
    task = await _create_task(client, foreign, foreign_project)

    listed = await client.get(
        f"/api/v1/sessions?project_id={foreign_project}", headers=owner.headers
    )
    assert listed.status_code == 200
    assert listed.json() == []

    started = await client.post(
        "/api/v1/sessions",
        json={"task_id": task["id"], "machine_id": str(owner.machine.id)},
        headers={**owner.headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert started.status_code == 404, started.text

    denied = await client.post(
        "/api/v1/sessions",
        json={"task_id": task["id"], "machine_id": str(member.machine.id)},
        headers={**member.headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == FORBIDDEN_WRITE
