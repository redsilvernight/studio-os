"""Repository registration at project initialization (`InitializationProjectSpec
.repository`): same codes as `POST /projects`, nothing created on error."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.isolation

URL = "https://github.com/Studio-OS/Init-Demo.git"
NORMALIZED = "github.com/studio-os/init-demo"
APPLY = "/api/v1/projects/initialization/apply"
PREVIEW = "/api/v1/projects/initialization/preview"


def _slug() -> str:
    return f"init-{uuid.uuid4().hex[:8]}"


def _plan(slug: str, repository: str | None) -> dict[str, Any]:
    project: dict[str, Any] = {"slug": slug, "name": "Init"}
    if repository is not None:
        project["repository"] = repository
    return {"plan": {"project": project}}


async def _post(client: AsyncClient, headers: dict[str, str], path: str, body: Any) -> Any:
    return await client.post(
        path, json=body, headers={**headers, "Idempotency-Key": str(uuid.uuid4())}
    )


async def _slug_exists(client: AsyncClient, headers: dict[str, str], slug: str) -> bool:
    listed = await client.get("/api/v1/projects", headers=headers)
    return any(item["slug"] == slug for item in listed.json())


async def test_apply_with_repository_is_resolved(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    slug = _slug()
    response = await _post(client, auth_headers, APPLY, _plan(slug, URL))
    assert response.status_code == 200, response.text
    resolved = await client.post(
        "/api/v1/projects/resolve-repository",
        headers=auth_headers,
        json={"remotes": ["git@github.com:studio-os/init-demo.git"]},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["slug"] == slug


async def test_apply_without_repository_creates_project(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    slug = _slug()
    response = await _post(client, auth_headers, APPLY, _plan(slug, None))
    assert response.status_code == 200, response.text
    assert await _slug_exists(client, auth_headers, slug)


async def test_apply_with_linked_repository_conflicts_and_creates_nothing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await _post(client, auth_headers, APPLY, _plan(_slug(), URL))
    assert first.status_code == 200, first.text
    slug = _slug()
    body = _plan(slug, URL)
    for path, payload in ((PREVIEW, body["plan"]), (APPLY, body)):
        response = await _post(client, auth_headers, path, payload)
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["error_code"] == "repository_already_linked"
    assert not await _slug_exists(client, auth_headers, slug)


async def test_apply_with_invalid_repository_is_refused_and_creates_nothing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    slug = _slug()
    response = await _post(client, auth_headers, APPLY, _plan(slug, "not-a-url"))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error_code"] == "invalid_repository_url"
    assert not await _slug_exists(client, auth_headers, slug)


async def test_reused_project_never_links_the_repository(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    slug = _slug()
    assert (await _post(client, auth_headers, APPLY, _plan(slug, None))).status_code == 200
    response = await _post(client, auth_headers, APPLY, _plan(slug, URL))
    assert response.status_code == 200, response.text
    project = next(
        item
        for item in (await client.get("/api/v1/projects", headers=auth_headers)).json()
        if item["slug"] == slug
    )
    assert project["repositories"] == []
