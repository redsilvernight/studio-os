"""Candidate tasks (AIB-G, L2): the roadmap's current-step linked tasks
first, then other unclaimed project tasks — bounded and explained. Consumed
by `studio_start_work` (9dff9368); exercised here at the service level. Real
Postgres."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.services.authz import Principal
from studio_api.services.candidates import list_candidate_tasks
from studio_contracts.auth import Role

Headers = dict[str, str]

DOCUMENT: dict[str, Any] = {
    "format": "studio.roadmap/v1",
    "title": "Plan",
    "phases": [
        {
            "key": "P1",
            "title": "Phase one",
            "steps": [
                {
                    "key": "S1",
                    "title": "Step one",
                    "tasks": [{"hydration_key": "t1", "title": "Roadmap task"}],
                },
                {"key": "S2", "title": "Step two", "depends_on": ["S1"]},
            ],
        }
    ],
}


async def _principal(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> Principal:
    machine_model, _ = machine
    user = await db_session.get(UserModel, machine_model.owner_user_id)
    assert user is not None
    return Principal(
        machine=machine_model,
        user=user,
        role=Role(user.role),
        project_scope=frozenset({project.id}),
    )


async def _task(
    client: AsyncClient, headers: Headers, project: ProjectModel, title: str
) -> dict[str, Any]:
    created = await client.post(
        "/api/v1/tasks", headers=headers, json={"project_id": str(project.id), "title": title}
    )
    assert created.status_code == 201, created.text
    return created.json()  # type: ignore[no-any-return]


async def test_project_tier_lists_unclaimed_unfinished_tasks(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    principal = await _principal(db_session, machine, project)
    free = await _task(client, auth_headers, project, "free")
    await _task(client, auth_headers, project, "claimed")

    claimed = await client.post(f"/api/v1/tasks/{free['id']}/claim", headers=auth_headers)
    assert claimed.status_code == 200
    done = await _task(client, auth_headers, project, "done")
    completed = await client.patch(
        f"/api/v1/tasks/{done['id']}",
        headers={**auth_headers, "If-Match-Version": str(done["version"])},
        json={"status": "completed"},
    )
    assert completed.status_code == 200

    candidates = await list_candidate_tasks(db_session, principal, project.id)
    titles = {c.task.title for c in candidates}
    assert titles == {"claimed"}  # free is claimed now, done is finished
    assert all(c.why.reason == "project_scope" for c in candidates)


async def test_roadmap_tier_comes_first_and_is_explained(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    principal = await _principal(db_session, machine, project)
    created = await client.post(
        "/api/v1/roadmaps/import",
        headers=auth_headers,
        json={"project_id": str(project.id), "document": DOCUMENT},
    )
    assert created.status_code == 201, created.text
    activated = await client.post(
        f"/api/v1/roadmaps/{created.json()['id']}/transitions",
        headers=auth_headers,
        json={"transition": "activate", "expected_version": created.json()["version"]},
    )
    assert activated.status_code == 200, activated.text
    hydrated = await client.post(
        f"/api/v1/roadmaps/{created.json()['id']}/hydration/apply",
        headers=auth_headers,
        json={"expected_version": activated.json()["version"]},
    )
    assert hydrated.status_code == 200, hydrated.text

    await _task(client, auth_headers, project, "ad hoc")

    candidates = await list_candidate_tasks(db_session, principal, project.id)
    assert [c.task.title for c in candidates] == ["Roadmap task", "ad hoc"]
    assert [c.why.reason for c in candidates] == ["active_roadmap", "project_scope"]


async def test_limit_bounds_and_suppresses(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple(MachineModel, str),
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    principal = await _principal(db_session, machine, project)
    for title in ("a", "b", "c"):
        await _task(client, auth_headers, project, title)

    assert await list_candidate_tasks(db_session, principal, project.id, limit=0) == []
    bounded = await list_candidate_tasks(db_session, principal, project.id, limit=2)
    assert len(bounded) == 2
    assert len({c.task.id for c in bounded}) == 2
