"""Session cycle and revocation (A2, DEC-0110 / DEC-0121)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api import admin_cli
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.deps import resolve_machine
from studio_api.jwt_auth import ALGORITHM
from studio_api.services import events as events_service
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import Settings, get_settings

_PASSWORD = "secret123"


class _SessionContext:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


async def _user_with_password(db_session: AsyncSession, role: str = "developer") -> UserModel:
    user = await provisioning_service.create_user(
        db_session, "Session User", f"{uuid.uuid4()}@example.test", role
    )
    return await provisioning_service.set_user_password(db_session, user.email, _PASSWORD)


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/token", json={"email": email, "password": _PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _me_status(client: AsyncClient, headers: dict[str, str]) -> int:
    return (await client.get("/api/v1/auth/me", headers=headers)).status_code


async def test_login_issues_short_token_without_email_or_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user_with_password(db_session)

    response = await client.post(
        "/api/v1/auth/token", json={"email": user.email, "password": _PASSWORD}
    )

    body = response.json()
    assert body["expires_in"] == 15 * 60
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert set(claims) == {"sub", "machine_id", "session_id", "auth_version", "iat", "exp", "type"}
    assert claims["sub"] == str(user.id)
    assert claims["auth_version"] == user.auth_version
    assert claims["exp"] - claims["iat"] == 15 * 60


async def test_auth_me_returns_identity_for_jwt_and_machine_token(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_headers: dict[str, str],
) -> None:
    user = await _user_with_password(db_session)
    jwt_headers = await _login(client, user.email)

    me = (await client.get("/api/v1/auth/me", headers=jwt_headers)).json()
    assert me["user_id"] == str(user.id)
    assert me["email"] == user.email
    assert me["role"] == "developer"

    machine_me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    assert machine_me["machine_id"] == str(machine[0].id)


async def test_password_change_revokes_existing_jwt(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user_with_password(db_session)
    headers = await _login(client, user.email)
    assert await _me_status(client, headers) == 200

    await provisioning_service.set_user_password(db_session, user.email, _PASSWORD)

    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid or revoked machine token"}
    assert await _me_status(client, await _login(client, user.email)) == 200


async def test_revoke_sessions_invalidates_jwt(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user_with_password(db_session)
    headers = await _login(client, user.email)

    await provisioning_service.revoke_user_sessions(db_session, user.email)

    assert await _me_status(client, headers) == 401


async def test_disable_blocks_jwt_machines_and_login_until_enabled(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user_with_password(db_session)
    _machine, token = await provisioning_service.create_machine(db_session, user.id, "laptop")
    machine_headers = {"Authorization": f"Bearer {token}"}
    jwt_headers = await _login(client, user.email)

    await provisioning_service.disable_user(db_session, user.email)

    assert await _me_status(client, jwt_headers) == 401
    assert await _me_status(client, machine_headers) == 401
    assert await resolve_machine(db_session, token) is None
    login = await client.post(
        "/api/v1/auth/token", json={"email": user.email, "password": _PASSWORD}
    )
    assert login.status_code == 401
    assert login.json() == {"detail": "invalid email or password"}

    await provisioning_service.enable_user(db_session, user.email)

    assert await _me_status(client, machine_headers) == 200
    assert await _me_status(client, jwt_headers) == 401
    assert await _me_status(client, await _login(client, user.email)) == 200


async def test_pending_user_has_no_principal(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _user_with_password(db_session)
    _machine, token = await provisioning_service.create_machine(db_session, user.id, "laptop")
    user.email_verified_at = None
    await db_session.flush()

    assert await _me_status(client, {"Authorization": f"Bearer {token}"}) == 401
    login = await client.post(
        "/api/v1/auth/token", json={"email": user.email, "password": _PASSWORD}
    )
    assert login.status_code == 401


def _forge(payload: dict[str, object]) -> dict[str, str]:
    now = datetime.now(UTC)
    claims = {"iat": now, "exp": now + timedelta(minutes=5), "type": "access", **payload}
    token = jwt.encode(claims, get_settings().jwt_secret, algorithm=ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


async def test_rejects_pre_cutover_and_mismatched_tokens(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user_with_password(db_session)
    dashboard = await provisioning_service.get_or_create_dashboard_machine(db_session, user)
    other = await _user_with_password(db_session)
    base = {"sub": str(user.id), "machine_id": str(dashboard.id)}
    current = user.auth_version

    assert await _me_status(client, _forge({**base, "auth_version": current})) == 200
    legacy = {**base, "email": user.email, "role": user.role}
    assert await _me_status(client, _forge(legacy)) == 401
    assert (
        await _me_status(client, _forge({**base, "sub": str(other.id), "auth_version": current}))
        == 401
    )
    assert (
        await _me_status(client, _forge({**base, "auth_version": current, "type": "refresh"}))
        == 401
    )
    assert await _me_status(client, _forge({**base, "auth_version": str(current)})) == 401


async def test_stream_revalidation_fails_after_revocation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        events_service, "get_session_factory", lambda: lambda: _SessionContext(db_session)
    )
    user = await _user_with_password(db_session, "admin")
    project = await _project(db_session)
    dashboard = await provisioning_service.get_or_create_dashboard_machine(db_session, user)

    version = user.auth_version
    assert await events_service.stream_access_still_valid(dashboard.id, project, version)

    await provisioning_service.revoke_user_sessions(db_session, user.email)
    assert not await events_service.stream_access_still_valid(dashboard.id, project, version)
    assert await events_service.stream_access_still_valid(dashboard.id, project, None)

    await provisioning_service.disable_user(db_session, user.email)
    assert not await events_service.stream_access_still_valid(dashboard.id, project, None)


async def _project(db_session: AsyncSession) -> uuid.UUID:
    project = ProjectModel(slug=f"p-{uuid.uuid4().hex[:12]}", name="Session project")
    db_session.add(project)
    await db_session.flush()
    return project.id


async def test_cli_user_state_commands(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        admin_cli, "get_session_factory", lambda: lambda: _SessionContext(db_session)
    )
    user = await _user_with_password(db_session)
    start = user.auth_version

    await admin_cli._update_user_state("revoke-sessions", user.email.upper())
    assert user.auth_version == start + 1

    await admin_cli._update_user_state("disable", user.email)
    assert user.disabled_at is not None
    assert user.auth_version == start + 2

    await admin_cli._update_user_state("enable", user.email)
    assert user.disabled_at is None
    assert user.auth_version == start + 2


def test_jwt_lifetime_out_of_range_refuses_to_start() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_access_token_expire_minutes=480)
    with pytest.raises(ValidationError):
        Settings(jwt_access_token_expire_minutes=0)
