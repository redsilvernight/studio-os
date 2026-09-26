from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.decisions import DecisionCreate, DecisionStatus
from studio_contracts.events import EventCreate, EventType

from studio_api.db.models.decision import DecisionModel
from studio_api.services import events as events_service
from studio_api.services.authz import (
    Principal,
    ProjectAction,
    ensure_can_write,
    ensure_project_access,
    ensure_shared_access,
    forbidden,
    project_visibility_clause,
)

_ALLOWED_TRANSITIONS: dict[DecisionStatus, frozenset[DecisionStatus]] = {
    DecisionStatus.ACCEPTED: frozenset({DecisionStatus.PROPOSED}),
    DecisionStatus.SUPERSEDED: frozenset({DecisionStatus.PROPOSED, DecisionStatus.ACCEPTED}),
}

_TRANSITION_EVENT_TYPES: dict[DecisionStatus, EventType] = {
    DecisionStatus.ACCEPTED: EventType.DECISION_ACCEPTED,
    DecisionStatus.SUPERSEDED: EventType.DECISION_SUPERSEDED,
}


async def _next_readable_id(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT nextval('decisions_readable_id_seq')"))
    next_value = result.scalar_one()
    return f"DEC-{next_value:04d}"


def decision_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "decision not found")


def invalid_decision_transition(current: str, target: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "error_code": "invalid_decision_transition",
            "message": f"cannot set status {target!r} from {current!r}",
        },
    )


async def list_decisions(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID | None = None
) -> list[DecisionModel]:
    """Unfiltered: the accessible projects' decisions plus the global
    (project-less) ones, the latter only for a Principal with at least one
    project (DEC-0103 §4/§7)."""
    stmt = select(DecisionModel)
    if project_id is not None:
        ensure_project_access(principal, project_id)
        stmt = stmt.where(DecisionModel.project_id == project_id)
    elif (visible := project_visibility_clause(principal, DecisionModel.project_id)) is not None:
        stmt = stmt.where(visible)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _ensure_decision_scope(
    principal: Principal, project_id: uuid.UUID | None, action: ProjectAction
) -> None:
    if project_id is None:
        ensure_shared_access(principal, action)
    else:
        ensure_project_access(principal, project_id, action)


def authorize_create(principal: Principal, project_id: uuid.UUID | None) -> None:
    """Project (or shared-data) then role check of a decision creation, run
    ahead of the idempotency replay short-circuit (DEC-0036, DEC-0103 §12)."""
    _ensure_decision_scope(principal, project_id, "write")
    ensure_can_write(principal, "decision")


async def create_decision(
    session: AsyncSession, principal: Principal, decision_in: DecisionCreate
) -> DecisionModel:
    authorize_create(principal, decision_in.project_id)
    decision = DecisionModel(
        readable_id=await _next_readable_id(session),
        project_id=decision_in.project_id,
        task_id=decision_in.task_id,
        title=decision_in.title,
        body=decision_in.body,
        proposed_by_type=decision_in.proposed_by_type,
        proposed_by_id=decision_in.proposed_by_id,
    )
    session.add(decision)
    await session.commit()
    await session.refresh(decision)
    return decision


async def _lock_decision(session: AsyncSession, decision_id: uuid.UUID) -> DecisionModel:
    """`SELECT ... FOR UPDATE`: the row lock serializes concurrent transitions
    on the same Decision so the status check and the write are atomic —
    two admins accepting the same Decision at once can never both succeed
    (the second waits for the lock, then sees the already-updated status
    and gets `409 invalid_decision_transition`)."""
    result = await session.execute(
        select(DecisionModel).where(DecisionModel.id == decision_id).with_for_update()
    )
    decision = result.scalar_one_or_none()
    if decision is None:
        raise decision_not_found()
    return decision


async def _commit_decision_transition(
    session: AsyncSession, decision: DecisionModel, principal: Principal, event_type: EventType
) -> None:
    """Stage the event in the same transaction as the status write, commit
    once (state and audit trail become durable atomically), then fan the
    committed event out to the realtime SSE stream — mirrors
    `roadmap_support.finish_result`. The event envelope's `project_id` is
    required (`.claude/rules/contracts.md`, `EventEnvelope`/`EventModel`),
    but a Decision's is optional (a global, project-less Decision) — such a
    transition still commits, it just has no event to emit."""
    if decision.project_id is None:
        await session.commit()
        await session.refresh(decision)
        return
    event = await events_service.stage_event(
        session,
        EventCreate(
            event_id=uuid.uuid4(),
            event_type=event_type,
            project_id=decision.project_id,
            task_id=decision.task_id,
            machine_id=principal.machine.id,
            actor_type="user",
            actor_id=principal.user.id,
            client_timestamp=datetime.now(UTC),
            payload={
                "decision_id": str(decision.id),
                "readable_id": decision.readable_id,
                "status": decision.status,
            },
        ),
    )
    await session.commit()
    await session.refresh(decision)
    await session.refresh(event)
    events_service.publish_event(event)


async def _transition_decision(
    session: AsyncSession, principal: Principal, decision_id: uuid.UUID, target: DecisionStatus
) -> DecisionModel:
    """Admin-only status transition: `proposed -> accepted`,
    `proposed|accepted -> superseded`. `superseded` is terminal — no
    transition is ever allowed out of it. Not a creation: no
    `Idempotency-Key`, a retried transition simply fails the status check
    again (`409 invalid_decision_transition`)."""
    ensure_can_write(principal, "decision")
    if principal.role != Role.ADMIN:
        raise forbidden("decision", target.value)
    decision = await _lock_decision(session, decision_id)
    _ensure_decision_scope(principal, decision.project_id, "write")
    current = DecisionStatus(decision.status)
    if current not in _ALLOWED_TRANSITIONS[target]:
        raise invalid_decision_transition(decision.status, target.value)
    decision.status = target.value
    await _commit_decision_transition(session, decision, principal, _TRANSITION_EVENT_TYPES[target])
    return decision


async def accept_decision(
    session: AsyncSession, principal: Principal, decision_id: uuid.UUID
) -> DecisionModel:
    return await _transition_decision(session, principal, decision_id, DecisionStatus.ACCEPTED)


async def supersede_decision(
    session: AsyncSession, principal: Principal, decision_id: uuid.UUID
) -> DecisionModel:
    return await _transition_decision(session, principal, decision_id, DecisionStatus.SUPERSEDED)
