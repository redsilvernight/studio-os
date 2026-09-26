from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from studio_api import compat
from studio_api.main import app
from studio_api.settings import Settings


def _headers(client: str, version: str) -> dict[str, str]:
    return {"X-Studio-Client": client, "X-Studio-Client-Version": version}


def test_parse_version_numeric_prefix() -> None:
    assert compat.parse_version("0.1.0") == (0, 1, 0)
    assert compat.parse_version("1.10.2") == (1, 10, 2)
    assert compat.parse_version("2.1.272-rc.1") == (2, 1, 272)
    assert compat.parse_version("1.2.3+build.4") == (1, 2, 3)


def test_parse_version_unreadable_is_none() -> None:
    assert compat.parse_version(None) is None
    assert compat.parse_version("") is None
    assert compat.parse_version("dev") is None
    assert compat.parse_version("1.x.0") is None


def test_is_supported_never_blocks_undeclared() -> None:
    assert compat.is_supported(None, "0.2.0") is True
    assert compat.is_supported("garbage", "0.2.0") is True
    assert compat.is_supported("0.1.9", None) is True
    assert compat.is_supported("0.1.9", "garbage") is True


def test_is_supported_compares_release_lines() -> None:
    assert compat.is_supported("0.1.0", "0.1.0") is True
    assert compat.is_supported("0.2.0", "0.1.0") is True
    assert compat.is_supported("0.0.9", "0.1.0") is False
    assert compat.is_supported("0.1", "0.1.0") is True
    assert compat.is_supported("1.0.0-rc.1", "1.0.0") is True


def test_check_client_ignores_unknown_family() -> None:
    settings = Settings()
    assert compat.check_client(None, "0.0.1", settings) is True
    assert compat.check_client("toaster", "0.0.1", settings) is True
    assert compat.check_client("daemon", "0.1.0", settings) is True
    assert compat.check_client("daemon", "0.0.1", settings) is False


@pytest.mark.asyncio
async def test_version_endpoint_needs_no_credential() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/version")

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "1"
    assert body["server_version"]
    expected = {"desktop": "0.1.0", "daemon": "0.1.0", "dashboard": "0.1.0"}
    assert body["minimum_supported"] == expected
    assert body["latest"] == expected


@pytest.mark.asyncio
async def test_client_without_headers_keeps_working(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/projects", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_supported_client_passes(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get(
        "/api/v1/projects", headers={**auth_headers, **_headers("daemon", "0.1.0")}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_outdated_client_gets_upgrade_invitation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/projects", headers={**auth_headers, **_headers("daemon", "0.0.1")}
    )
    assert response.status_code == 426
    detail = response.json()["detail"]
    assert detail["error_code"] == "client_upgrade_required"
    assert detail["client"] == "daemon"
    assert detail["client_version"] == "0.0.1"
    assert detail["minimum_supported"] == "0.1.0"
    assert detail["latest"] == "0.1.0"
    assert "update" in detail["message"].lower()


@pytest.mark.asyncio
async def test_guard_ignores_unknown_family_and_garbage(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    for headers in (_headers("toaster", "0.0.1"), _headers("daemon", "dev")):
        response = await client.get("/api/v1/projects", headers={**auth_headers, **headers})
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_guard_covers_auth_flow(client: AsyncClient) -> None:
    login = {"email": "nobody@example.test", "password": "wrong"}
    outdated = await client.post(
        "/api/v1/auth/token", json=login, headers=_headers("desktop", "0.0.1")
    )
    assert outdated.status_code == 426
    assert outdated.json()["detail"]["error_code"] == "client_upgrade_required"

    current = await client.post("/api/v1/auth/token", json=login)
    assert current.status_code == 401
