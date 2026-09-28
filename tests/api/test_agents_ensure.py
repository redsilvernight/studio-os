"""`POST /agents/ensure` (AIB-I): server-side find-or-create on the local
stable key, scoped to the calling machine — a retried session-start hook
never registers a duplicate, even after the idempotency table forgot the
original call. Needs the real Postgres test DB (unique-constraint race
resolution is a database behavior)."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel

ENSURE = "/api/v1/agents/ensure"
REGISTER = "/api/v1/agents"


def _body(display_name: str = "studio-opencode", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "display_name": display_name,
        "agent_kind": "",
        "agent_profile": None,
        "harness": "opencode",
        "provider": None,
        "model": None,
        "stable_key": "agents-ensure-opencode",
    }
    payload.update(overrides)
    return payload


async def _agent_count(db_session: AsyncSession) -> int:
    return (await db_session.execute(select(func.count()).select_from(AgentModel))).scalar_one()


async def test_ensure_creates_then_finds(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    first = await client.post(ENSURE, headers=auth_headers, json=_body())
    assert first.status_code == 201
    assert first.json()["created"] is True
    agent_id = first.json()["agent"]["id"]
    assert first.json()["agent"]["stable_key"] == "agents-ensure-opencode"

    second = await client.post(ENSURE, headers=auth_headers, json=_body())
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["agent"]["id"] == agent_id
    assert await _agent_count(db_session) == 1


async def test_ensure_mismatch_is_an_explicit_409(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    created = await client.post(ENSURE, headers=auth_headers, json=_body())
    assert created.status_code == 201

    renamed = await client.post(ENSURE, headers=auth_headers, json=_body(display_name="renamed"))
    assert renamed.status_code == 409
    assert renamed.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"
    assert await _agent_count(db_session) == 1


async def test_stable_key_is_scoped_to_the_calling_machine(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    mine = await client.post(ENSURE, headers=auth_headers, json=_body())
    other = await client.post(ENSURE, headers=other_auth_headers, json=_body())
    assert mine.status_code == 201
    assert other.status_code == 201
    assert mine.json()["agent"]["id"] != other.json()["agent"]["id"]
    assert await _agent_count(db_session) == 2


async def test_register_colliding_stable_key_is_an_explicit_409(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    ensured = await client.post(ENSURE, headers=auth_headers, json=_body())
    assert ensured.status_code == 201

    replay = await client.post(
        REGISTER,
        headers={**auth_headers, "Idempotency-Key": "another-key"},
        json=_body(),
    )
    assert replay.status_code == 409
    assert replay.json()["detail"]["error_code"] == "duplicate_stable_key"
    assert await _agent_count(db_session) == 1


async def test_ensure_requires_a_writer_role(
    client: AsyncClient, readonly_auth_headers: dict[str, str]
) -> None:
    response = await client.post(ENSURE, headers=readonly_auth_headers, json=_body())
    assert response.status_code == 403


async def test_ensure_without_stable_key_registers(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    payload = _body()
    del payload["stable_key"]
    first = await client.post(ENSURE, headers=auth_headers, json=payload)
    assert first.status_code == 201
    assert first.json()["created"] is True
    assert first.json()["agent"]["stable_key"] is None


async def test_machine_id_stays_server_derived(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    response = await client.post(
        ENSURE, headers=auth_headers, json={**_body(), "machine_id": str(machine_model.id)}
    )
    assert response.status_code == 422
