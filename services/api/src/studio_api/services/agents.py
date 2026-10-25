from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.agent_identity import (
    AgentIdentityRequest,
    AgentIdentityResult,
    logical_harness,
)
from studio_contracts.auth import Agent, AgentCreate

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


async def resolve_identity(
    session: AsyncSession, principal: Principal, request: AgentIdentityRequest
) -> AgentIdentityResult:
    ensure_can_write(principal, "agent")
    harness = logical_harness(request.harness)
    provider = (request.provider or "").strip().lower()
    model = (request.effective_model or "").strip()
    unknown_model = model.lower() in {"", "unknown", "default", "auto"}
    unknown_provider = provider in {"", "unknown", "default", "auto"}
    if not harness:
        raise HTTPException(422, detail={"error_code": "invalid_argument", "field": "harness"})
    if unknown_model or unknown_provider:
        return AgentIdentityResult(
            state="unknown",
            logical_harness=harness,
            reason="unknown_model" if unknown_model else "unknown_provider",
            selection_alias=request.selection_alias,
        )
    key = (
        "canonical-model-v1:"
        + hashlib.sha256(
            json.dumps(
                [harness, provider, model], ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    statement = (
        insert(AgentModel)
        .values(
            owner_user_id=principal.user.id,
            machine_id=principal.machine.id,
            display_name=model,
            agent_kind="model",
            harness=harness,
            provider=provider,
            model=model,
            stable_key=key,
        )
        .on_conflict_do_nothing(constraint="uq_agents_user_stable_key")
        .returning(AgentModel.id)
    )
    identifier = (await session.execute(statement)).scalar_one_or_none()
    created = identifier is not None
    agent = (
        await session.execute(
            select(AgentModel).where(
                AgentModel.owner_user_id == principal.user.id, AgentModel.stable_key == key
            )
        )
    ).scalar_one()
    await session.commit()
    await session.refresh(agent)
    return AgentIdentityResult(
        state="resolved",
        logical_harness=harness,
        selection_alias=request.selection_alias,
        agent=Agent.model_validate(agent),
        created=created,
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
