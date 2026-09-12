from __future__ import annotations

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel


async def test_missing_bearer_token_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects")
    assert response.status_code == 401


async def test_invalid_bearer_token_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/projects", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_valid_token_accepted(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/api/v1/projects", headers=auth_headers)
    assert response.status_code == 200


async def test_revoked_token_rejected(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    machine_model, token = machine
    machine_model.credential_revoked_at = datetime.now(UTC)
    await db_session.flush()

    response = await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
