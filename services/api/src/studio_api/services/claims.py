from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.claims import ResourceClaimCreate
from studio_contracts.events import EventCreate, EventType

from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.task import TaskModel
from studio_api.services import events as events_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_machine_owned,
    ensure_project_access,
    project_visibility_clause,
)


async def _active_claims(session: AsyncSession, project_id: uuid.UUID) -> list[ResourceClaimModel]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(ResourceClaimModel).where(
            ResourceClaimModel.project_id == project_id,
            ResourceClaimModel.status == "active",
            ResourceClaimModel.expires_at > now,
        )
    )
    return list(result.scalars().all())


def _conflicts(a_path: str, a_type: str, b_path: str, b_type: str) -> bool:
    """A folder claim conflicts with a descendant file claim
    (.claude/rules/database.md) — same path always conflicts too."""
    if a_path == b_path:
        return True
    if a_type == "folder" and b_path.startswith(a_path.rstrip("/") + "/"):
        return True
    if b_type == "folder" and a_path.startswith(b_path.rstrip("/") + "/"):
        return True
    return False


def paths_conflict(a_path: str, a_type: str, b_path: str, b_type: str) -> bool:
    """Public face of the claim overlap rule, for read-only consumers (e.g.
    project context selection) that must apply exactly the same semantics."""
    return _conflicts(a_path, a_type, b_path, b_type)


async def list_claims(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID | None = None
) -> list[ResourceClaimModel]:
    stmt = select(ResourceClaimModel)
    if project_id is not None:
        ensure_project_access(principal, project_id)
        stmt = stmt.where(ResourceClaimModel.project_id == project_id)
    elif (
        visible := project_visibility_clause(principal, ResourceClaimModel.project_id)
    ) is not None:
        stmt = stmt.where(visible)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _commit_with_event(
    session: AsyncSession,
    principal: Principal,
    claim: ResourceClaimModel,
    event_type: EventType,
    extra: dict[str, Any] | None = None,
) -> ResourceClaimModel:
    """Commits the claim write and its `resource.*` event atomically, then fans
    the event out (TECH/03_EVENT_CONTRACT.md, emission serveur Claims)."""
    actor_type, actor_id = await tasks_service.event_actor(
        session, principal, claim.claimed_by_agent_id
    )
    await session.flush()
    event = await events_service.stage_event(
        session,
        EventCreate(
            event_id=uuid.uuid4(),
            event_type=event_type,
            project_id=claim.project_id,
            task_id=claim.task_id,
            machine_id=principal.machine.id,
            actor_type=actor_type,
            actor_id=actor_id,
            client_timestamp=datetime.now(UTC),
            payload={
                "claim_id": str(claim.id),
                "resource_path": claim.resource_path,
                "resource_type": claim.resource_type,
                "status": claim.status,
                "claimed_by_machine_id": str(claim.claimed_by_machine_id),
                "expires_at": claim.expires_at.isoformat(),
                **(extra or {}),
            },
        ),
    )
    await session.commit()
    await session.refresh(claim)
    await session.refresh(event)
    events_service.publish_event(event)
    return claim


def authorize_create(principal: Principal, project_id: uuid.UUID) -> None:
    """Project then role check of a claim creation. Callers run it ahead of
    the idempotency replay short-circuit (DEC-0036, DEC-0103 §12)."""
    ensure_project_access(principal, project_id, "write")
    ensure_can_write(principal, "claim")


async def create_claim(
    session: AsyncSession,
    principal: Principal,
    claim_in: ResourceClaimCreate,
    machine_id: uuid.UUID,
    agent_id: uuid.UUID | None,
) -> ResourceClaimModel:
    """Soft lock: a conflict is surfaced (`resource.conflict` event, left to the
    router) but never blocks the write here — see AI/01_AI_OPERATING_REFERENCE.md
    interdiction on blocking locks."""
    authorize_create(principal, claim_in.project_id)
    now = datetime.now(UTC)
    claim = ResourceClaimModel(
        project_id=claim_in.project_id,
        task_id=claim_in.task_id,
        resource_path=claim_in.resource_path,
        resource_type=claim_in.resource_type.value,
        claimed_by_machine_id=machine_id,
        claimed_by_agent_id=agent_id,
        ttl_seconds=claim_in.ttl_seconds,
        expires_at=now + timedelta(seconds=claim_in.ttl_seconds),
    )
    session.add(claim)
    await session.flush()
    return await _commit_with_event(session, principal, claim, EventType.RESOURCE_CLAIMED)


async def has_conflict(session: AsyncSession, claim: ResourceClaimModel) -> bool:
    others = await _active_claims(session, claim.project_id)
    return any(
        other.id != claim.id
        and _conflicts(
            claim.resource_path, claim.resource_type, other.resource_path, other.resource_type
        )
        for other in others
    )


async def renew_claim(
    session: AsyncSession, principal: Principal, claim: ResourceClaimModel
) -> ResourceClaimModel:
    ensure_project_access(principal, claim.project_id, "write")
    ensure_machine_owned(principal, claim.claimed_by_machine_id, "claim", "renew")
    if claim.status == "released":
        # A released claim stays released: no write, no `resource.renewed`.
        return claim
    now = datetime.now(UTC)
    claim.renewed_at = now
    claim.expires_at = now + timedelta(seconds=claim.ttl_seconds)
    return await _commit_with_event(session, principal, claim, EventType.RESOURCE_RENEWED)


async def release_claim(
    session: AsyncSession, principal: Principal, claim: ResourceClaimModel
) -> ResourceClaimModel:
    ensure_project_access(principal, claim.project_id, "write")
    ensure_machine_owned(principal, claim.claimed_by_machine_id, "claim", "release")
    if claim.status == "released":
        # Releasing twice is harmless: no second write, no second event.
        return claim
    previous_status = claim.status
    claim.status = "released"
    claim.released_at = datetime.now(UTC)
    return await _commit_with_event(
        session,
        principal,
        claim,
        EventType.RESOURCE_RELEASED,
        {"previous_status": previous_status},
    )


async def get_claim(session: AsyncSession, claim_id: uuid.UUID) -> ResourceClaimModel:
    claim = await session.get(ResourceClaimModel, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "claim not found")
    return claim


async def release_task_claims_by_task(
    session: AsyncSession, principal: Principal, task: TaskModel
) -> list[ResourceClaimModel]:
    """Release all active claims for a given task. Used by L3 handoff
    fallback when a session ends. Idempotent: already-released claims
    are skipped without error."""
    ensure_project_access(principal, task.project_id, "write")
    result = await session.execute(
        select(ResourceClaimModel).where(
            ResourceClaimModel.task_id == task.id,
            ResourceClaimModel.status == "active",
        )
    )
    claims = list(result.scalars().all())
    released = []
    for claim in claims:
        # Ownership check per claim: only the holding machine can release
        if claim.claimed_by_machine_id != principal.machine.id:
            continue
        claim.status = "released"
        claim.released_at = datetime.now(UTC)
        released.append(claim)
    if released:
        await session.commit()
        for claim in released:
            await session.refresh(claim)
    return released
