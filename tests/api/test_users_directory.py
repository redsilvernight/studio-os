"""Admin user directory `GET /api/v1/users` (task ac1b9a28): lets the
dashboard pick a member by name or email instead of a raw user id."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import provisioning as provisioning_service


async def test_admin_searches_by_name_or_email(
    client: AsyncClient, admin_auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    tag = uuid.uuid4().hex[:8]
    alice = await provisioning_service.create_user(
        db_session, f"Alice {tag}", f"alice-{tag}@example.test", "developer"
    )
    bob = await provisioning_service.create_user(
        db_session, f"Bob {tag}", f"bob-{tag}@example.test", "readonly"
    )

    by_name = await client.get(
        "/api/v1/users", params={"q": f"ALICE {tag}"}, headers=admin_auth_headers
    )
    assert by_name.status_code == 200, by_name.text
    assert [u["id"] for u in by_name.json()] == [str(alice.id)]
    assert by_name.json()[0]["email"] == alice.email
    assert "password_hash" not in by_name.json()[0]

    by_email = await client.get(
        "/api/v1/users", params={"q": f"bob-{tag}@"}, headers=admin_auth_headers
    )
    assert [u["id"] for u in by_email.json()] == [str(bob.id)]

    both = await client.get("/api/v1/users", params={"q": tag}, headers=admin_auth_headers)
    assert [u["id"] for u in both.json()] == [str(alice.id), str(bob.id)]

    capped = await client.get(
        "/api/v1/users", params={"q": tag, "limit": 1}, headers=admin_auth_headers
    )
    assert len(capped.json()) == 1


async def test_like_wildcards_are_literal(
    client: AsyncClient, admin_auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    tag = uuid.uuid4().hex[:8]
    await provisioning_service.create_user(
        db_session, f"Plain {tag}", f"plain-{tag}@example.test", "developer"
    )
    for q in (f"%{tag}", f"_lain {tag}"):
        response = await client.get("/api/v1/users", params={"q": q}, headers=admin_auth_headers)
        assert response.status_code == 200
        assert response.json() == []


async def test_no_query_lists_users(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/users", headers=admin_auth_headers)
    assert response.status_code == 200
    assert len(response.json()) >= 1


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"q": "x" * 201}])
async def test_invalid_params_are_rejected(
    client: AsyncClient, admin_auth_headers: dict[str, str], params: dict[str, object]
) -> None:
    response = await client.get("/api/v1/users", params=params, headers=admin_auth_headers)
    assert response.status_code == 422


async def test_non_admin_is_forbidden(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/api/v1/users", params={"q": "a"}, headers=auth_headers)
    assert response.status_code == 403, response.text
    assert not isinstance(response.json(), list)


async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/users")).status_code == 401
