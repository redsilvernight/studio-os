"""Repository registration at project creation (`POST /projects`, optional
`repository` field of its request model).

Criteria: a project created with a remote is found by
`POST /projects/resolve-repository`; without a remote the creation succeeds and
a remote can be linked later; a remote already owned by another project is an
explicit `409 repository_already_linked` and leaves no project behind.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from studio_api.db.models.project import ProjectModel

pytestmark = pytest.mark.isolation

URL = "https://github.com/Studio-OS/Demo.git"
NORMALIZED = "github.com/studio-os/demo"


def _slug(prefix: str = "created") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create(
    client: AsyncClient, headers: dict[str, str], slug: str, repository: str | None
) -> tuple[int, dict[str, Any]]:
    body: dict[str, Any] = {"slug": slug, "name": "Created"}
    if repository is not None:
        body["repository"] = repository
    response = await client.post(
        "/api/v1/projects", headers={**headers, "Idempotency-Key": str(uuid.uuid4())}, json=body
    )
    return response.status_code, response.json()


async def _slug_exists(client: AsyncClient, headers: dict[str, str], slug: str) -> bool:
    listed = await client.get("/api/v1/projects", headers=headers)
    assert listed.status_code == 200, listed.text
    return any(item["slug"] == slug for item in listed.json())


async def _resolve(client: AsyncClient, headers: dict[str, str], remote: str) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/projects/resolve-repository", headers=headers, json={"remotes": [remote]}
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_created_with_repository_is_resolved(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    slug = _slug()
    status, created = await _create(client, auth_headers, slug, URL)
    assert status == 201, created
    assert created["repositories"] == [NORMALIZED]

    # Another spelling of the same remote (scp form, `.git`) resolves too.
    resolved = await _resolve(client, auth_headers, "git@github.com:studio-os/demo.git")
    assert resolved["status"] == "resolved"
    assert resolved["project_id"] == created["id"]
    assert resolved["slug"] == slug


async def test_created_without_repository_accepts_a_later_link(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    slug = _slug("no-remote")
    status, created = await _create(client, auth_headers, slug, None)
    assert status == 201, created
    assert created["repositories"] == []
    assert (await _resolve(client, auth_headers, URL))["status"] == "not_found"

    linked = await client.post(
        f"/api/v1/projects/{created['id']}/repositories", headers=auth_headers, json={"url": URL}
    )
    assert linked.status_code == 201, linked.text
    assert (await _resolve(client, auth_headers, URL))["project_id"] == created["id"]


async def test_create_refuses_a_remote_linked_to_another_project(
    client: AsyncClient, admin_auth_headers: dict[str, str], auth_headers: dict[str, str]
) -> None:
    first_slug = _slug("owner")
    status, owner = await _create(client, admin_auth_headers, first_slug, URL)
    assert status == 201, owner

    # Different spelling of an owned remote: still the same conflict.
    slug = _slug("conflict")
    status, body = await _create(client, auth_headers, slug, "ssh://git@github.com/studio-os/demo")
    assert status == 409, body
    assert body["detail"]["error_code"] == "repository_already_linked"
    assert body["detail"]["url"] == NORMALIZED
    # Nothing was written: the slug is still free for a creation without a remote.
    assert not await _slug_exists(client, auth_headers, slug)
    assert (await _create(client, auth_headers, slug, None))[0] == 201


@pytest.mark.parametrize("bad_url", ["not-a-url", "ftp://github.com/studio-os/demo", "https://"])
async def test_create_refuses_an_invalid_remote_before_writing(
    client: AsyncClient, auth_headers: dict[str, str], bad_url: str
) -> None:
    slug = _slug("invalid")
    status, body = await _create(client, auth_headers, slug, bad_url)
    assert status == 422, body
    assert body["detail"]["error_code"] == "invalid_repository_url"
    assert not await _slug_exists(client, auth_headers, slug)


async def test_replay_with_the_same_key_does_not_link_twice(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    slug = _slug("replay")
    key = str(uuid.uuid4())
    body = {"slug": slug, "name": "Created", "repository": URL}
    first = await client.post(
        "/api/v1/projects", headers={**auth_headers, "Idempotency-Key": key}, json=body
    )
    assert first.status_code == 201, first.text
    replay = await client.post(
        "/api/v1/projects", headers={**auth_headers, "Idempotency-Key": key}, json=body
    )
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    fetched = await client.get(f"/api/v1/projects/{first.json()['id']}", headers=auth_headers)
    assert fetched.json()["repositories"] == [NORMALIZED]


async def test_agent_cannot_create_a_project_with_a_repository(
    client: AsyncClient, agent_auth_headers: dict[str, str]
) -> None:
    status, body = await _create(client, agent_auth_headers, _slug("agent"), URL)
    assert status == 403, body
    assert body["detail"] == "insufficient role"


async def test_openapi_advertises_the_optional_repository_field(client: AsyncClient) -> None:
    """The additive input field is part of the published surface, next to the
    canonical `ProjectCreate` fields it extends."""
    doc = (await client.get("/openapi.json")).json()
    schema = doc["components"]["schemas"]["ProjectCreateRequest"]
    assert set(schema["properties"]) == {"slug", "name", "description", "repository"}
    assert schema["required"] == ["slug", "name"]
    assert schema["additionalProperties"] is False
