from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import AgentCreate

from studio_api.db.models.agent import AgentModel
from studio_api.services.authz import Principal, ensure_can_write

_METADATA_FIELDS = (
    "display_name",
    "agent_kind",
    "agent_profile",
    "harness",
    "provider",
    "model",
)


async def _find_by_stable_key(
    session: AsyncSession, machine_id: uuid.UUID | None, stable_key: str
) -> AgentModel | None:
    result = await session.execute(
        select(AgentModel).where(
            AgentModel.machine_id == machine_id,
            AgentModel.stable_key == stable_key,
        )
    )
    return result.scalars().first()


def _metadata_matches(agent: AgentModel, agent_in: AgentCreate) -> bool:
    return all(getattr(agent, field) == getattr(agent_in, field) for field in _METADATA_FIELDS)


async def create_agent(
    session: AsyncSession, principal: Principal, agent_in: AgentCreate
) -> AgentModel:
    """Registers an operational provenance identity for the authenticated
    machine (CC-1). `machine_id` is derived from `principal`, never from
    client input — the same shape as `events.resolve_event_identity`
    (DEC-0035). Grants no permission: authorization stays `auth_role` +
    ownership (`authz.py`). A `stable_key` that already exists for this
    machine is an explicit `409 duplicate_stable_key`, never a silent
    duplicate — the idempotent path is `ensure_agent`."""
    ensure_can_write(principal, "agent")
    if agent_in.stable_key is not None:
        existing = await _find_by_stable_key(session, principal.machine.id, agent_in.stable_key)
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail={"error_code": "duplicate_stable_key"}
            )
    agent = AgentModel(
        machine_id=principal.machine.id,
        display_name=agent_in.display_name,
        agent_kind=agent_in.agent_kind,
        agent_profile=agent_in.agent_profile,
        harness=agent_in.harness,
        provider=agent_in.provider,
        model=agent_in.model,
        stable_key=agent_in.stable_key,
    )
    session.add(agent)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"error_code": "duplicate_stable_key"}
        ) from exc
    await session.refresh(agent)
    return agent


async def ensure_agent(
    session: AsyncSession, principal: Principal, agent_in: AgentCreate
) -> tuple[AgentModel, bool]:
    """Find-or-create this machine's agent for `agent_in.stable_key`
    (AIB-I): the server-side `agents ensure` behind `POST /agents/ensure`,
    so a retried session-start hook never registers a duplicate — even
    after the idempotency table forgot the original call. Same key + same
    metadata returns the existing agent (`created=False`); same key +
    different metadata is an explicit `409
    idempotency_key_payload_mismatch` (same condition as an
    `Idempotency-Key` replay with a different body). Without a
    `stable_key` this is a plain registration (`created=True`). A lost
    commit race resolves through the `(machine_id, stable_key)` unique
    constraint: the loser re-reads the winner's row instead of failing."""
    ensure_can_write(principal, "agent")
    if agent_in.stable_key is not None:
        existing = await _find_by_stable_key(session, principal.machine.id, agent_in.stable_key)
        if existing is not None:
            if not _metadata_matches(existing, agent_in):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={"error_code": "idempotency_key_payload_mismatch"},
                )
            return existing, False
    agent = AgentModel(
        machine_id=principal.machine.id,
        display_name=agent_in.display_name,
        agent_kind=agent_in.agent_kind,
        agent_profile=agent_in.agent_profile,
        harness=agent_in.harness,
        provider=agent_in.provider,
        model=agent_in.model,
        stable_key=agent_in.stable_key,
    )
    session.add(agent)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raced = await _find_by_stable_key(session, principal.machine.id, agent_in.stable_key or "")
        if raced is None:
            raise
        if not _metadata_matches(raced, agent_in):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"error_code": "idempotency_key_payload_mismatch"},
            ) from exc
        return raced, False
    await session.refresh(agent)
    return agent, True
