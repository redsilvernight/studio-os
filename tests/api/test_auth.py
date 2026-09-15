from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import provisioning as provisioning_service

from tests.api.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="no test database configured",
)

_ADMIN_EMAIL = "dash-auth@example.test"
_ADMIN_PASSWORD = "secret123"


async def _create_admin_with_password(db_session: AsyncSession) -> None:
    user = await provisioning_service.create_user(db_session, "Dash Admin", _ADMIN_EMAIL, "admin")
    await provisioning_service.set_user_password(db_session, user.email, _ADMIN_PASSWORD)


@pytest.mark.asyncio
async def test_login_returns_jwt(client: AsyncClient, db_session: AsyncSession) -> None:
    await _create_admin_with_password(db_session)

    response = await client.post(
        "/api/v1/auth/token", json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert "access_token" in data
    assert data["access_token"].count(".") == 2


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/token", json={"email": "nobody@example.test", "password": "wrong"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_jwt_can_access_api(client: AsyncClient, db_session: AsyncSession) -> None:
    await _create_admin_with_password(db_session)

    login = await client.post(
        "/api/v1/auth/token", json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD}
    )
    token = login.json()["access_token"]

    response = await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
