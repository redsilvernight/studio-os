from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.claims import ResourceClaimCreate

from studio_api.db.models.claim import ResourceClaimModel


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


async def list_claims(
    session: AsyncSession, project_id: uuid.UUID | None = None
) -> list[ResourceClaimModel]:
    stmt = select(ResourceClaimModel)
    if project_id is not None:
        stmt = stmt.where(ResourceClaimModel.project_id == project_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_claim(
    session: AsyncSession,
    claim_in: ResourceClaimCreate,
    machine_id: uuid.UUID,
    agent_id: uuid.UUID | None,
) -> ResourceClaimModel:
    """Soft lock: a conflict is surfaced (`resource.conflict` event, left to the
    router) but never blocks the write here — see AI/01_AI_OPERATING_REFERENCE.md
    interdiction on blocking locks."""
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
    await session.commit()
    await session.refresh(claim)
    return claim


async def has_conflict(session: AsyncSession, claim: ResourceClaimModel) -> bool:
    others = await _active_claims(session, claim.project_id)
    return any(
        other.id != claim.id
        and _conflicts(
            claim.resource_path, claim.resource_type, other.resource_path, other.resource_type
        )
        for other in others
    )


async def renew_claim(session: AsyncSession, claim: ResourceClaimModel) -> ResourceClaimModel:
    now = datetime.now(UTC)
    claim.renewed_at = now
    claim.expires_at = now + timedelta(seconds=claim.ttl_seconds)
    await session.commit()
    await session.refresh(claim)
    return claim


async def release_claim(session: AsyncSession, claim: ResourceClaimModel) -> ResourceClaimModel:
    claim.status = "released"
    claim.released_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(claim)
    return claim


async def get_claim(session: AsyncSession, claim_id: uuid.UUID) -> ResourceClaimModel:
    claim = await session.get(ResourceClaimModel, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "claim not found")
    return claim
