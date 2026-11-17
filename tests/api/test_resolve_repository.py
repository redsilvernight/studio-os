"""`POST /projects/resolve-repository` (Bloc A): resolution by normalized
remote, membership scoping, no existence oracle, ambiguity and validation."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import projects as projects_service
from studio_contracts.projects import ResolveRepositoryResponse

pytestmark = pytest.mark.isolation

PATH = "/api/v1/projects/resolve-repository"
URL = "https://github.com/Studio-OS/Demo.git"


@pytest_asyncio.fixture
async def other_project(db_session: AsyncSession) -> ProjectModel:
    return await projects_service.create_project(
        db_session, f"other-{uuid.uuid4().hex[:8]}", "Other Project", None, creator=None
    )


async def _link(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    url: str = URL,
) -> None:
    response = await client.post(
        f"/api/v1/projects/{project.id}/repositories",
        headers=admin_auth_headers,
        json={"url": url},
    )
    assert response.status_code in (200, 201), response.text


async def _member(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    granted = await client.put(
        f"/api/v1/projects/{project.id}/members/{machine[0].owner_user_id}",
        headers=admin_auth_headers,
    )
    assert granted.status_code in (200, 201), granted.text


@pytest.mark.parametrize(
    "remote",
    [
        "git@github.com:studio-os/demo.git",
        "ssh://git@github.com/Studio-OS/Demo",
        "https://github.com/studio-os/demo",
        "HTTPS://GitHub.com/STUDIO-OS/demo.git/",
    ],
)
async def test_member_resolves_every_remote_form(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    remote: str,
) -> None:
    await _link(client, admin_auth_headers, project)
    await _member(client, admin_auth_headers, project, machine)
    response = await client.post(PATH, headers=auth_headers, json={"remotes": [remote]})
    assert response.status_code == 200, response.text
    body = ResolveRepositoryResponse.model_validate(response.json())
    assert body.status == "resolved"
    assert body.project_id == project.id
    assert body.slug == project.slug


async def test_one_known_remote_among_unknown_and_invalid(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    await _link(client, admin_auth_headers, project)
    await _member(client, admin_auth_headers, project, machine)
    response = await client.post(
        PATH,
        headers=auth_headers,
        json={"remotes": ["not a url", "https://github.com/other/x", URL]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


async def test_non_member_and_unknown_are_indistinguishable(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    await _link(client, admin_auth_headers, project)
    known = await client.post(PATH, headers=auth_headers, json={"remotes": [URL]})
    unknown = await client.post(
        PATH, headers=auth_headers, json={"remotes": ["https://github.com/nobody/nothing"]}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert known.json()["status"] == "not_found"


async def test_admin_non_member_is_not_found(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    await _link(client, admin_auth_headers, project)
    response = await client.post(PATH, headers=admin_auth_headers, json={"remotes": [URL]})
    assert response.status_code == 200
    assert response.json()["status"] == "not_found"


async def test_remotes_matching_two_projects_conflict(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    other_project: ProjectModel,
) -> None:
    await _link(client, admin_auth_headers, project)
    await _link(client, admin_auth_headers, other_project, "https://github.com/studio-os/other")
    await _member(client, admin_auth_headers, project, machine)
    await _member(client, admin_auth_headers, other_project, machine)
    response = await client.post(
        PATH,
        headers=auth_headers,
        json={"remotes": [URL, "https://github.com/studio-os/other"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "ambiguous"


@pytest.mark.parametrize(
    "remotes",
    [[], ["https://github.com/a/b"] * 11, ["x" * 513], ["not a url"]],
)
async def test_invalid_payload_is_422(
    client: AsyncClient, auth_headers: dict[str, str], remotes: list[str]
) -> None:
    response = await client.post(PATH, headers=auth_headers, json={"remotes": remotes})
    assert response.status_code == 422


async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    response = await client.post(PATH, json={"remotes": [URL]})
    assert response.status_code == 401
