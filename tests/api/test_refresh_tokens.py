"""Rotating refresh tokens for the desktop session (DEC-0142)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.refresh_token import RefreshTokenModel
from studio_api.db.models.user import UserModel
from studio_api.security import hash_token
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import Settings

_PASSWORD = "secret123"
_REFUSED = {"detail": "invalid or expired refresh token"}


async def _user(db_session: AsyncSession) -> UserModel:
    user = await provisioning_service.create_user(
        db_session, "Refresh User", f"{uuid.uuid4()}@example.test", "developer"
    )
    return await provisioning_service.set_user_password(db_session, user.email, _PASSWORD)


async def _login(client: AsyncClient, email: str, persistent: bool = True) -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/token",
        json={"email": email, "password": _PASSWORD, "persistent": persistent},
    )
    assert response.status_code == 200
    return response.json()


async def _refresh(client: AsyncClient, token: object) -> tuple[int, dict[str, object]]:
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    return response.status_code, response.json()


async def _me_status(client: AsyncClient, access_token: object) -> int:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    return response.status_code


async def test_login_without_persistent_issues_no_refresh_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)

    body = await _login(client, user.email, persistent=False)

    assert body["refresh_token"] is None
    assert body["refresh_expires_at"] is None
    count = await db_session.execute(
        select(RefreshTokenModel).where(RefreshTokenModel.user_id == user.id)
    )
    assert count.scalars().all() == []


async def test_persistent_login_stores_only_the_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)

    body = await _login(client, user.email)

    secret = body["refresh_token"]
    assert isinstance(secret, str) and len(secret) >= 43
    rows = (
        (
            await db_session.execute(
                select(RefreshTokenModel).where(RefreshTokenModel.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].token_hash == hash_token(secret)
    assert rows[0].token_hash != secret
    assert rows[0].auth_version == user.auth_version


async def test_refresh_rotates_and_issues_working_access_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    first = await _login(client, user.email)

    status, second = await _refresh(client, first["refresh_token"])

    assert status == 200
    assert second["refresh_token"] not in (None, first["refresh_token"])
    assert second["expires_in"] == 15 * 60
    assert await _me_status(client, second["access_token"]) == 200
    status, third = await _refresh(client, second["refresh_token"])
    assert status == 200
    assert await _me_status(client, third["access_token"]) == 200


async def test_reused_refresh_token_revokes_the_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    first = await _login(client, user.email)
    _, second = await _refresh(client, first["refresh_token"])

    assert await _refresh(client, first["refresh_token"]) == (401, _REFUSED)

    # The legitimate successor is dead too: the session must sign in again.
    assert await _refresh(client, second["refresh_token"]) == (401, _REFUSED)


async def test_other_families_survive_a_reuse(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    laptop = await _login(client, user.email)
    desktop = await _login(client, user.email)
    await _refresh(client, laptop["refresh_token"])

    await _refresh(client, laptop["refresh_token"])

    status, _ = await _refresh(client, desktop["refresh_token"])
    assert status == 200


@pytest.mark.parametrize(
    "revoke",
    [
        lambda s, u: provisioning_service.revoke_user_sessions(s, u.email),
        lambda s, u: provisioning_service.set_user_password(s, u.email, _PASSWORD),
        lambda s, u: provisioning_service.disable_user(s, u.email),
    ],
    ids=["revoke-sessions", "password", "disable"],
)
async def test_auth_version_change_ends_the_session(
    client: AsyncClient, db_session: AsyncSession, revoke: object
) -> None:
    user = await _user(db_session)
    body = await _login(client, user.email)

    await revoke(db_session, user)  # type: ignore[operator]

    assert await _refresh(client, body["refresh_token"]) == (401, _REFUSED)


async def test_enable_does_not_revive_a_disabled_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    body = await _login(client, user.email)
    await provisioning_service.disable_user(db_session, user.email)
    await provisioning_service.enable_user(db_session, user.email)

    assert await _refresh(client, body["refresh_token"]) == (401, _REFUSED)


async def test_revoked_dashboard_machine_ends_the_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    body = await _login(client, user.email)
    dashboard = await provisioning_service.get_or_create_dashboard_machine(db_session, user)
    dashboard.credential_revoked_at = datetime.now(UTC)
    await db_session.flush()

    assert await _refresh(client, body["refresh_token"]) == (401, _REFUSED)


async def test_expired_refresh_token_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    body = await _login(client, user.email)
    await db_session.execute(
        update(RefreshTokenModel)
        .where(RefreshTokenModel.token_hash == hash_token(str(body["refresh_token"])))
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    assert await _refresh(client, body["refresh_token"]) == (401, _REFUSED)


async def test_sliding_expiry_never_passes_the_absolute_lifetime(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    body = await _login(client, user.email)
    absolute = datetime.now(UTC) + timedelta(days=2)
    await db_session.execute(
        update(RefreshTokenModel)
        .where(RefreshTokenModel.token_hash == hash_token(str(body["refresh_token"])))
        .values(absolute_expires_at=absolute)
    )

    status, refreshed = await _refresh(client, body["refresh_token"])

    assert status == 200
    successor = (
        await db_session.execute(
            select(RefreshTokenModel).where(
                RefreshTokenModel.token_hash == hash_token(str(refreshed["refresh_token"]))
            )
        )
    ).scalar_one()
    assert successor.absolute_expires_at == absolute
    assert successor.expires_at == absolute


async def test_unknown_refresh_token_is_refused(client: AsyncClient) -> None:
    assert await _refresh(client, "not-a-real-token") == (401, _REFUSED)


async def test_logout_revokes_the_family_and_is_always_204(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session)
    first = await _login(client, user.email)
    _, second = await _refresh(client, first["refresh_token"])

    # Logout with a rotated (consumed) token still ends its family.
    response = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": first["refresh_token"]}
    )
    assert response.status_code == 204
    assert await _refresh(client, second["refresh_token"]) == (401, _REFUSED)

    unknown = await client.post("/api/v1/auth/logout", json={"refresh_token": "unknown"})
    assert unknown.status_code == 204


def test_refresh_lifetimes_out_of_range_refuse_to_start() -> None:
    with pytest.raises(ValidationError):
        Settings(refresh_token_sliding_days=0)
    with pytest.raises(ValidationError):
        Settings(refresh_token_absolute_days=365)
