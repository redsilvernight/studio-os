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
    AgentIdentityLink,
    AgentIdentityReconciliationPlan,
    AgentIdentityRequest,
    AgentIdentityResult,
    logical_harness,
)
from studio_contracts.auth import Agent, AgentCreate, Role

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.services.authz import Principal, ensure_can_write, forbidden

_METADATA_FIELDS = (
    "display_name",
    "agent_kind",
    "agent_profile",
    "harness",
    "provider",
    "model",
)


def _canonical_identity_key(harness: str, provider: str, model: str) -> str:
    """The DEC-0237 identity key: logical harness + normalized provider +
    exact effective model, hashed so the colons/slashes of a model reference
    never matter. Aliases do not participate."""
    return (
        "canonical-model-v1:"
        + hashlib.sha256(
            json.dumps(
                [harness, provider, model], ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
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
    key = _canonical_identity_key(harness, provider, model)
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


def _identity_tuple(agent: AgentModel) -> tuple[str, str, str] | None:
    if agent.harness is None or agent.provider is None or agent.model is None:
        return None
    harness = logical_harness(agent.harness)
    provider = agent.provider.strip().lower()
    model = agent.model.strip()
    if not harness or not provider or not model:
        return None
    return (harness, provider, model)


async def plan_identity_reconciliation(
    session: AsyncSession, owner_user_id: uuid.UUID | None = None
) -> AgentIdentityReconciliationPlan:
    """Report the legacy rows an explicit reconciliation would link to their
    canonical identity (DEC-0237). Read-only: nothing is written, nothing is
    merged, and a legacy row's machine, metadata and history stay untouched.
    `owner_user_id` narrows the report to one user; `admin` reports everyone."""
    canonical_rows = (
        (
            await session.execute(
                select(AgentModel).where(
                    AgentModel.owner_user_id.is_not(None),
                    AgentModel.superseded_by_agent_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    canonical: dict[tuple[uuid.UUID, str, str, str], AgentModel] = {}
    for row in sorted(canonical_rows, key=lambda item: (item.created_at, str(item.id))):
        identity = _identity_tuple(row)
        if identity is not None and row.owner_user_id is not None:
            canonical.setdefault((row.owner_user_id, *identity), row)

    legacy_rows = (
        (
            await session.execute(
                select(AgentModel).where(
                    AgentModel.owner_user_id.is_(None),
                    AgentModel.superseded_by_agent_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    machine_ids = {row.machine_id for row in legacy_rows if row.machine_id is not None}
    owners: dict[uuid.UUID, uuid.UUID] = {}
    if machine_ids:
        machines = (
            (await session.execute(select(MachineModel).where(MachineModel.id.in_(machine_ids))))
            .scalars()
            .all()
        )
        owners = {item.id: item.owner_user_id for item in machines}

    links: list[AgentIdentityLink] = []
    unmatched = 0
    for row in legacy_rows:
        identity = _identity_tuple(row)
        owner = owners.get(row.machine_id) if row.machine_id is not None else None
        if identity is None or owner is None:
            continue
        if owner_user_id is not None and owner != owner_user_id:
            continue
        match = canonical.get((owner, *identity))
        if match is None:
            unmatched += 1
            continue
        links.append(
            AgentIdentityLink(
                legacy_agent_id=row.id,
                canonical_agent_id=match.id,
                owner_user_id=owner,
                logical_harness=identity[0],
                provider=identity[1],
                model=identity[2],
            )
        )
    already_linked = (
        await session.execute(
            select(AgentModel.id).where(
                AgentModel.superseded_by_agent_id.is_not(None),
                AgentModel.owner_user_id.is_(None),
            )
        )
    ).scalars()
    return AgentIdentityReconciliationPlan(
        links=links, already_linked=len(already_linked.all()), unmatched_legacy=unmatched
    )


async def apply_identity_reconciliation(
    session: AsyncSession, plan: AgentIdentityReconciliationPlan
) -> int:
    """Write the explicit links of a reviewed plan. The former row only gains
    the pointer: no field is rewritten and no row is deleted, so clearing the
    pointer restores the previous state exactly."""
    linked = 0
    for link in plan.links:
        legacy = await session.get(AgentModel, link.legacy_agent_id)
        if legacy is None or legacy.superseded_by_agent_id is not None:
            continue
        legacy.superseded_by_agent_id = link.canonical_agent_id
        legacy.version += 1
        linked += 1
    return linked


async def supersede_identity(
    session: AsyncSession,
    principal: Principal,
    agent_id: uuid.UUID,
    canonical_agent_id: uuid.UUID,
) -> AgentModel:
    ensure_can_write(principal, "agent")
    if agent_id == canonical_agent_id:
        raise HTTPException(409, detail={"error_code": "invalid_identity_link"})
    legacy = await session.get(AgentModel, agent_id)
    canonical = await session.get(AgentModel, canonical_agent_id)
    if legacy is None or canonical is None:
        raise HTTPException(404, detail={"error_code": "not_found"})
    if canonical.owner_user_id is None or canonical.superseded_by_agent_id is not None:
        raise HTTPException(
            409, detail={"error_code": "invalid_identity_link", "field": "canonical_agent_id"}
        )
    if principal.role != Role.ADMIN:
        legacy_owner = await _legacy_owner_user_id(session, legacy)
        if legacy_owner != principal.user.id or canonical.owner_user_id != principal.user.id:
            raise forbidden("agent", "supersede")
    if legacy.superseded_by_agent_id is not None:
        raise HTTPException(
            409,
            detail={
                "error_code": "already_superseded",
                "superseded_by_agent_id": str(legacy.superseded_by_agent_id),
            },
        )
    legacy.superseded_by_agent_id = canonical.id
    legacy.version += 1
    await session.commit()
    await session.refresh(legacy)
    return legacy


async def _legacy_owner_user_id(session: AsyncSession, agent: AgentModel) -> uuid.UUID | None:
    if agent.owner_user_id is not None:
        return agent.owner_user_id
    if agent.machine_id is None:
        return None
    machine = await session.get(MachineModel, agent.machine_id)
    return None if machine is None else machine.owner_user_id
