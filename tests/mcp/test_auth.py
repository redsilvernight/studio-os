from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.services import provisioning as provisioning_service
from studio_mcp.auth import McpAuthError, authenticate

from tests.mcp.conftest import FakeContext


async def test_authenticate_succeeds_with_bearer_header(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    machine_model, token = machine
    ctx = FakeContext(headers={"authorization": f"Bearer {token}"})
    resolved = await authenticate(ctx, db_session)
    assert resolved.id == machine_model.id


async def test_authenticate_falls_back_to_env_token_on_stdio(
    db_session: AsyncSession, machine: tuple[MachineModel, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    machine_model, token = machine
    monkeypatch.setenv("STUDIO_MCP_MACHINE_TOKEN", token)
    ctx = FakeContext(headers=None)
    resolved = await authenticate(ctx, db_session)
    assert resolved.id == machine_model.id


async def test_authenticate_rejects_missing_token(db_session: AsyncSession) -> None:
    ctx = FakeContext(headers=None)
    with pytest.raises(McpAuthError):
        await authenticate(ctx, db_session)


async def test_authenticate_rejects_unknown_token(db_session: AsyncSession) -> None:
    ctx = FakeContext(headers={"authorization": "Bearer not-a-real-token"})
    with pytest.raises(McpAuthError):
        await authenticate(ctx, db_session)


async def test_authenticate_rejects_revoked_machine(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    machine_model, token = machine
    await provisioning_service.revoke_machine(db_session, machine_model)
    ctx = FakeContext(headers={"authorization": f"Bearer {token}"})
    with pytest.raises(McpAuthError):
        await authenticate(ctx, db_session)
