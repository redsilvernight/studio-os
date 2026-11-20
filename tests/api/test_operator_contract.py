"""Contract freeze (API_CONTRACT_VERSION stays 6, additive): `/users` needs the
instance-operator flag and answers `403 resource=instance` otherwise; a client
that sends no studio header or claim keeps the default-studio behaviour."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api import admin_cli
from studio_api.services import provisioning as provisioning_service


async def test_global_admin_without_operator_flag_gets_403_instance_until_granted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = f"{uuid.uuid4()}@example.test"
    user = await provisioning_service.create_user(db_session, "Late Admin", email, "admin")
    _, token = await provisioning_service.create_machine(db_session, user.id, "m")
    headers = {"Authorization": f"Bearer {token}"}

    denied = await client.get("/api/v1/users", headers=headers)
    assert denied.status_code == 403
    assert "instance" in denied.text

    await provisioning_service.set_operator(db_session, email, True)
    assert (await client.get("/api/v1/users", headers=headers)).status_code == 200
    # No studio header, no claim: the default-studio directory still answers (N-1 shape).
    assert (await client.get("/api/v1/studio/members", headers=headers)).status_code == 200

    await provisioning_service.set_operator(db_session, email, False)
    assert (await client.get("/api/v1/users", headers=headers)).status_code == 403


async def test_cli_set_operator_grants_and_revokes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.api.test_admin_cli import _bind_session

    _bind_session(monkeypatch, db_session)
    email = f"{uuid.uuid4()}@example.test"
    await provisioning_service.create_user(db_session, "Op", email, "admin")

    await admin_cli._set_operator(email, True)
    user = await provisioning_service.get_user_by_email(db_session, email)
    assert user is not None and user.is_operator is True

    await admin_cli._set_operator(email.upper(), False)
    await db_session.refresh(user)
    assert user.is_operator is False
