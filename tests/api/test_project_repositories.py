"""Project linked repositories (Bloc A): `POST/DELETE
/projects/{id}/repositories`, global URL uniqueness, role gates and
`ProjectRead.repositories`."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_contracts.projects import ProjectRead

pytestmark = pytest.mark.isolation

UNKNOWN = "00000000-0000-4000-8000-000000000000"
URL = "https://github.com/studio-os/demo"


async def _grant(
    client: AsyncClient, admin_headers: dict[str, str], project_id: object, user_id: object
) -> None:
    granted = await client.put(
        f"/api/v1/projects/{project_id}/members/{user_id}", headers=admin_headers
    )
    assert granted.status_code in (200, 201), granted.text


async def _member_link(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    url: str = URL,
) -> str:
    await _grant(client, admin_auth_headers, project.id, machine[0].owner_user_id)
    response = await client.post(
        f"/api/v1/projects/{project.id}/repositories", headers=auth_headers, json={"url": url}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["url"])


async def test_link_lists_and_unlinks(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    normalized = await _member_link(
        client,
        auth_headers,
        admin_auth_headers,
        machine,
        project,
        "https://github.com/Org/Repo.git",
    )
    assert normalized == "github.com/org/repo"

    fetched = await client.get(f"/api/v1/projects/{project.id}", headers=auth_headers)
    assert fetched.status_code == 200
    read = ProjectRead.model_validate(fetched.json())
    assert read.repositories == ["github.com/org/repo"]

    listed = await client.get("/api/v1/projects", headers=auth_headers)
    assert listed.status_code == 200
    by_id = {item["id"]: item for item in listed.json()}
    assert by_id[str(project.id)]["repositories"] == ["github.com/org/repo"]

    # Re-linking the same remote (any spelling) is a no-op, not a duplicate.
    for spelling in ("https://github.com/Org/Repo", "https://github.com/Org/Repo/"):
        replay = await client.post(
            f"/api/v1/projects/{project.id}/repositories",
            headers=auth_headers,
            json={"url": spelling},
        )
        assert replay.status_code == 200, replay.text
    assert (await client.get(f"/api/v1/projects/{project.id}", headers=auth_headers)).json()[
        "repositories"
    ] == ["github.com/org/repo"]

    removed = await client.delete(
        f"/api/v1/projects/{project.id}/repositories/github.com/org/repo",
        headers=auth_headers,
    )
    assert removed.status_code == 204
    assert (await client.get(f"/api/v1/projects/{project.id}", headers=auth_headers)).json()[
        "repositories"
    ] == []

    again = await client.delete(
        f"/api/v1/projects/{project.id}/repositories/github.com/org/repo",
        headers=auth_headers,
    )
    assert again.status_code == 404


async def test_same_url_cannot_link_two_projects(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    admin_machine: tuple[MachineModel, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    from studio_api.services import projects as projects_service

    other = await projects_service.create_project(
        db_session,
        f"other-{uuid.uuid4().hex[:8]}",
        "Other",
        None,
        creator=None,
    )
    await _grant(client, admin_auth_headers, project.id, machine[0].owner_user_id)
    await _grant(client, admin_auth_headers, other.id, machine[0].owner_user_id)
    first = await client.post(
        f"/api/v1/projects/{project.id}/repositories",
        headers=auth_headers,
        json={"url": URL},
    )
    assert first.status_code == 201, first.text

    conflict = await client.post(
        f"/api/v1/projects/{other.id}/repositories",
        headers=auth_headers,
        json={"url": URL + "/"},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["error_code"] == "repository_already_linked"
    assert (await client.get(f"/api/v1/projects/{other.id}", headers=admin_auth_headers)).json()[
        "repositories"
    ] == []


async def test_non_writer_roles_are_forbidden(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    readonly_auth_headers: dict[str, str],
    agent_auth_headers: dict[str, str],
) -> None:
    for headers in (readonly_auth_headers, agent_auth_headers):
        me = await client.get("/api/v1/machines/me", headers=headers)
        await _grant(client, admin_auth_headers, project.id, me.json()["owner_user_id"])

        linked = await client.post(
            f"/api/v1/projects/{project.id}/repositories", headers=headers, json={"url": URL}
        )
        assert linked.status_code == 403, linked.text
        assert linked.json()["detail"]["error_code"] == "forbidden"

        unlinked = await client.delete(
            f"/api/v1/projects/{project.id}/repositories/{URL}", headers=headers
        )
        assert unlinked.status_code == 403, unlinked.text


async def test_unknown_project_is_404_for_admin_and_403_for_outsider(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
) -> None:
    linked = await client.post(
        f"/api/v1/projects/{UNKNOWN}/repositories",
        headers=admin_auth_headers,
        json={"url": URL},
    )
    assert linked.status_code == 404
    unlinked = await client.delete(
        f"/api/v1/projects/{UNKNOWN}/repositories/{URL}", headers=admin_auth_headers
    )
    assert unlinked.status_code == 404

    # No existence oracle for a caller without access (DEC-0103 §3).
    forbidden = await client.post(
        f"/api/v1/projects/{UNKNOWN}/repositories", headers=auth_headers, json={"url": URL}
    )
    assert forbidden.status_code == 403


@pytest.mark.parametrize("bad_url", ["not-a-url", "", "ftp://github.com/org/repo", "https://"])
async def test_invalid_url_is_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    bad_url: str,
) -> None:
    await _grant(client, admin_auth_headers, project.id, machine[0].owner_user_id)
    response = await client.post(
        f"/api/v1/projects/{project.id}/repositories",
        headers=auth_headers,
        json={"url": bad_url},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error_code"] == "invalid_repository_url"


async def test_project_read_defaults_to_no_repositories(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    await _grant(client, admin_auth_headers, project.id, machine[0].owner_user_id)
    fetched = await client.get(f"/api/v1/projects/{project.id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert ProjectRead.model_validate(fetched.json()).repositories == []
