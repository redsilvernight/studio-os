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
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import events as events_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_machine_owned,
    ensure_optional_project_in_studio,
    ensure_project_access,
    ensure_project_in_studio,
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


async def active_claims(session: AsyncSession, project_id: uuid.UUID) -> list[ResourceClaimModel]:
    """Public read of live claims (real state with derived expiry), for
    read-only consumers (e.g. sync relevance) that must not depend on claim
    event types being emitted."""
    return await _active_claims(session, project_id)


async def list_claims(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID | None = None
) -> list[ResourceClaimModel]:
    stmt = select(ResourceClaimModel)
    if project_id is not None:
        ensure_project_access(principal, project_id)
        stmt = stmt.where(ResourceClaimModel.project_id == project_id)
        visible = project_visibility_clause(principal, ResourceClaimModel.project_id)
        if visible is not None:
            stmt = stmt.where(visible)
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
    await events_service.publish_event(session, event)
    return claim


def authorize_create(principal: Principal, project_id: uuid.UUID) -> None:
    """Project then role check of a claim creation. Callers run it ahead of
    the idempotency replay short-circuit (DEC-0036, DEC-0103 §12)."""
    ensure_project_access(principal, project_id, "write")
    ensure_can_write(principal, "claim")


async def _open_session_task_id(
    session: AsyncSession,
    project_id: uuid.UUID,
    machine_id: uuid.UUID,
    agent_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Task of the caller's open session in this project, if any (task
    2817382b): a claim made without `task_id` while the machine (and the agent,
    when the caller names one) has a live session on a task of the same project
    is the work in progress, so it is attached to that task and `studio_handoff`
    / `end_session` release it instead of leaving it until its TTL.

    Newest open session wins; no open session, or sessions only on other
    projects, leaves the claim task-less. A named agent only matches its own
    sessions, so one agent never inherits another's task."""
    stmt = (
        select(WorkSessionModel.task_id)
        .join(TaskModel, WorkSessionModel.task_id == TaskModel.id)
        .where(
            WorkSessionModel.machine_id == machine_id,
            WorkSessionModel.ended_at.is_(None),
            TaskModel.project_id == project_id,
        )
        .order_by(WorkSessionModel.started_at.desc(), WorkSessionModel.id.desc())
    )
    if agent_id is not None:
        stmt = stmt.where(WorkSessionModel.agent_id == agent_id)
    return (await session.execute(stmt)).scalars().first()


async def create_claim(
    session: AsyncSession,
    principal: Principal,
    claim_in: ResourceClaimCreate,
    machine_id: uuid.UUID,
    agent_id: uuid.UUID | None,
) -> ResourceClaimModel:
    """Soft lock: a conflict is surfaced (`resource.conflict` event, left to the
    router) but never blocks the write here — see AI/01_AI_OPERATING_REFERENCE.md
    interdiction on blocking locks. A claim made without `task_id` is attached to
    the caller's open session's task when there is one in the same project."""
    authorize_create(principal, claim_in.project_id)
    await ensure_optional_project_in_studio(session, principal, claim_in.project_id, "write")
    await ensure_project_in_studio(session, principal, claim_in.project_id, "write")
    task_id = claim_in.task_id
    if task_id is None:
        task_id = await _open_session_task_id(session, claim_in.project_id, machine_id, agent_id)
    now = datetime.now(UTC)
    claim = ResourceClaimModel(
        project_id=claim_in.project_id,
        task_id=task_id,
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
    await ensure_project_in_studio(session, principal, claim.project_id, "write")
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
    await ensure_project_in_studio(session, principal, claim.project_id, "write")
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


# Deterministic on the claim id: two overlapping server-side releases (lazy
# expiry racing the sweep) converge on one `resource.released`, never two.
_CLAIM_RELEASED_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "studio-os/claim-released")


async def release_claim_server_side(
    session: AsyncSession,
    claim: ResourceClaimModel,
    *,
    emitter_machine_id: uuid.UUID,
) -> ResourceClaimModel:
    """Release one claim on the server's behalf (launch expiry, task 63a909ea):
    the server, not the claiming machine, closes it — hence no
    `ensure_machine_owned` — and the event is attributed to the target machine
    that held the claim (`emitter_machine_id`), actor `system`. The caller
    commits, so the release stays atomic with the launch expiry."""
    if claim.status == "released":
        return claim
    previous_status = claim.status
    claim.status = "released"
    claim.released_at = datetime.now(UTC)
    await events_service.stage_event(
        session,
        EventCreate(
            event_id=uuid.uuid5(_CLAIM_RELEASED_NAMESPACE, str(claim.id)),
            event_type=EventType.RESOURCE_RELEASED,
            project_id=claim.project_id,
            task_id=claim.task_id,
            machine_id=emitter_machine_id,
            actor_type="system",
            actor_id=emitter_machine_id,
            client_timestamp=datetime.now(UTC),
            payload={
                "claim_id": str(claim.id),
                "resource_path": claim.resource_path,
                "resource_type": claim.resource_type,
                "status": claim.status,
                "claimed_by_machine_id": str(claim.claimed_by_machine_id),
                "expires_at": claim.expires_at.isoformat(),
                "previous_status": previous_status,
            },
        ),
    )
    return claim


async def get_claim(session: AsyncSession, claim_id: uuid.UUID) -> ResourceClaimModel:
    claim = await session.get(ResourceClaimModel, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "claim not found")
    return claim


async def release_task_claims_by_task(
    session: AsyncSession,
    principal: Principal,
    task: TaskModel,
    *,
    agent_id: uuid.UUID | None,
) -> list[ResourceClaimModel]:
    """Release the session agent's active claims for a task. Used by L3 handoff and
    the `end_session` fallback. Claims made without a `task_id` during the
    session are attached to that task at creation (`create_claim`), so they are
    released here too. Each release goes through `release_claim`
    so a `resource.released` event is emitted per claim, exactly like a
    single release. Idempotent: already-released claims are skipped
    without error; another machine or agent's claims are never touched.
    Unattributed claims follow the task holder when no different agent holds it."""
    await ensure_project_in_studio(session, principal, task.project_id, "write")
    result = await session.execute(
        select(ResourceClaimModel).where(
            ResourceClaimModel.task_id == task.id,
            ResourceClaimModel.status == "active",
        )
    )
    claims = list(result.scalars().all())
    released = []
    for claim in claims:
        # Ownership check per claim: only the holding machine can release.
        if claim.claimed_by_machine_id != principal.machine.id:
            continue
        if claim.claimed_by_agent_id != agent_id and (
            claim.claimed_by_agent_id is not None
            or task.claimed_by_agent_id not in (None, agent_id)
        ):
            continue
        released.append(await release_claim(session, principal, claim))
    return released
