"""Project isolation, lot 2 (DEC-0100 / server DEC-0103): every project-scoped
surface refuses a non-member with the same 403 as a nonexistent project, and
collections are silently filtered. Deny by default (`isolation` marker)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.services.authz import ensure_shared_access, load_principal

from tests.e2e.test_roadmaps_p10_e2e import _plan

pytestmark = pytest.mark.isolation

UNKNOWN = "00000000-0000-0000-0000-000000000000"


def _forbidden(action: str) -> dict[str, str]:
    return {"error_code": "forbidden", "resource": "project", "action": action}


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={"slug": f"iso-{uuid.uuid4().hex[:8]}", "name": "Iso"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _post(
    client: AsyncClient, headers: dict[str, str], path: str, body: dict[str, Any]
) -> Any:
    return await client.post(
        path, json=body, headers={**headers, "Idempotency-Key": str(uuid.uuid4())}
    )


PROJECT_READS = [
    "/api/v1/tasks?project_id={pid}",
    "/api/v1/claims?project_id={pid}",
    "/api/v1/decisions?project_id={pid}",
    "/api/v1/ai-work?project_id={pid}",
    "/api/v1/review-queue?project_id={pid}",
    "/api/v1/timeline?project_id={pid}",
    "/api/v1/builds?project_id={pid}",
    "/api/v1/producer-jobs?project_id={pid}",
    "/api/v1/events?project={pid}",
    "/api/v1/transfers?project_id={pid}",
    "/api/v1/library?project_id={pid}",
    "/api/v1/projects/{pid}/roadmaps",
]


@pytest.mark.parametrize("template", PROJECT_READS)
async def test_project_reads_refuse_a_non_member_like_a_nonexistent_project(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    template: str,
) -> None:
    pid = await _project(client, auth_headers)
    await _project(client, other_auth_headers)  # the outsider is a member elsewhere

    member = await client.get(template.format(pid=pid), headers=auth_headers)
    assert member.status_code == 200, member.text

    inaccessible = await client.get(template.format(pid=pid), headers=other_auth_headers)
    nonexistent = await client.get(template.format(pid=UNKNOWN), headers=other_auth_headers)
    assert inaccessible.status_code == nonexistent.status_code == 403, inaccessible.text
    assert inaccessible.json()["detail"] == nonexistent.json()["detail"] == _forbidden("read")


async def test_unfiltered_collections_hide_other_projects(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    pid = await _project(client, auth_headers)
    await _project(client, other_auth_headers)
    created = await _post(client, auth_headers, "/api/v1/tasks", {"project_id": pid, "title": "t"})
    assert created.status_code == 201, created.text

    listed = await client.get("/api/v1/tasks", headers=other_auth_headers)
    assert listed.status_code == 200
    assert created.json()["id"] not in {t["id"] for t in listed.json()}


async def test_resources_by_id_refuse_a_non_member(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    pid = await _project(client, auth_headers)
    task = await _post(client, auth_headers, "/api/v1/tasks", {"project_id": pid, "title": "t"})
    roadmap = await _post(
        client, auth_headers, "/api/v1/roadmaps", {"project_id": pid, "title": "Plan"}
    )
    assert task.status_code == 201 and roadmap.status_code == 201, roadmap.text

    for path in (
        f"/api/v1/tasks/{task.json()['id']}",
        f"/api/v1/sessions?task_id={task.json()['id']}",
        f"/api/v1/roadmaps/{roadmap.json()['id']}",
        f"/api/v1/roadmaps/{roadmap.json()['id']}/revisions",
    ):
        response = await client.get(path, headers=other_auth_headers)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["detail"] == _forbidden("read")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/tasks", {"title": "t"}),
        ("/api/v1/roadmaps", {"title": "Plan"}),
    ],
)
async def test_writes_refuse_a_non_member_before_idempotency(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    path: str,
    body: dict[str, Any],
) -> None:
    pid = await _project(client, auth_headers)
    response = await _post(client, other_auth_headers, path, {**body, "project_id": pid})
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == _forbidden("write")


async def test_roadmap_writes_refuse_a_non_member(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    pid = await _project(client, auth_headers)
    roadmap = await _post(
        client, auth_headers, "/api/v1/roadmaps", {"project_id": pid, "title": "Plan"}
    )
    response = await _post(
        client,
        other_auth_headers,
        f"/api/v1/roadmaps/{roadmap.json()['id']}/phases",
        {"key": "p1", "title": "Phase", "expected_roadmap_version": 1},
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == _forbidden("write")


async def test_shared_data_needs_at_least_one_project(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    """Project-less shared data (Studio Library): admin, or a member of any
    project; collections are filtered, direct access refused."""
    with pytest.raises(HTTPException) as refused:
        ensure_shared_access(await load_principal(db_session, other_machine[0]))
    assert refused.value.status_code == 403
    assert refused.value.detail == _forbidden("read")

    await _project(client, auth_headers)
    assert (await client.get("/api/v1/library", headers=auth_headers)).status_code == 200


async def test_initialization_sees_the_project_it_creates(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """The Principal is loaded before the project exists; the creator's own
    grant must still cover the roadmap and tasks created in the same request."""
    plan = _plan(f"init-{uuid.uuid4().hex[:8]}")
    response = await _post(
        client, auth_headers, "/api/v1/projects/initialization/apply", {"plan": plan}
    )
    assert response.status_code == 200, response.text
