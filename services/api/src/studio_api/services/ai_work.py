from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.ai_work import AIWorkLogCreate, AIWorkLogUpdate, AIWorkStatus
from studio_contracts.auth import Role
from studio_contracts.events import ActorType, EventCreate, EventType

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.services import events as events_service
from studio_api.services.authz import Principal, ensure_can_write, forbidden

_EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "studio-os/ai-work-events")

_STATUS_EVENT_TYPES: dict[AIWorkStatus, EventType] = {
    AIWorkStatus.COMPLETED: EventType.AI_WORK_COMPLETED,
    AIWorkStatus.FAILED: EventType.AI_WORK_FAILED,
    AIWorkStatus.REVIEW_REQUESTED: EventType.AI_WORK_REVIEW_REQUESTED,
    AIWorkStatus.APPROVED: EventType.AI_WORK_APPROVED,
    AIWorkStatus.CHANGES_REQUESTED: EventType.AI_WORK_CHANGES_REQUESTED,
}

_REVIEW_RESOLUTIONS = (AIWorkStatus.APPROVED, AIWorkStatus.CHANGES_REQUESTED)


def _derive_event_id(work_id: uuid.UUID, event_type: EventType) -> uuid.UUID:
    """Deterministic on (ai_work_id, event_type): an idempotent HTTP retry of
    `POST /ai-work`/`PATCH /ai-work/{id}`, or the MCP tool invoked twice for
    the same target status, must resolve to the same event via
    `events_service.create_event`'s get-or-create-by-id, never a duplicate."""
    return uuid.uuid5(_EVENT_NAMESPACE, f"{work_id}:{event_type.value}")


async def _emit_ai_work_event(
    session: AsyncSession,
    work: AIWorkLogModel,
    event_type: EventType,
    actor_type: ActorType,
    actor_id: uuid.UUID,
) -> None:
    await events_service.create_event(
        session,
        EventCreate(
            event_id=_derive_event_id(work.id, event_type),
            event_type=event_type,
            project_id=work.project_id,
            task_id=work.task_id,
            machine_id=work.machine_id,
            actor_type=actor_type,
            actor_id=actor_id,
            client_timestamp=datetime.now(UTC),
            payload={"ai_work_id": str(work.id), "summary": work.summary, "status": work.status},
        ),
    )


async def list_ai_work(
    session: AsyncSession, project_id: uuid.UUID | None = None, task_id: uuid.UUID | None = None
) -> list[AIWorkLogModel]:
    stmt = select(AIWorkLogModel)
    if project_id is not None:
        stmt = stmt.where(AIWorkLogModel.project_id == project_id)
    if task_id is not None:
        stmt = stmt.where(AIWorkLogModel.task_id == task_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_ai_work(
    session: AsyncSession, principal: Principal, work_in: AIWorkLogCreate
) -> AIWorkLogModel:
    ensure_can_write(principal, "ai_work")
    agent = await session.get(AgentModel, work_in.agent_id)
    if agent is None or agent.machine_id != principal.machine.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "actor_not_owned",
                "message": "agent_id must be an agent attached to the authenticated machine",
            },
        )
    work = AIWorkLogModel(
        task_id=work_in.task_id,
        project_id=work_in.project_id,
        agent_id=work_in.agent_id,
        machine_id=work_in.machine_id,
        summary=work_in.summary,
        started_at=datetime.now(UTC),
        agent_profile=work_in.agent_profile,
        harness=work_in.harness,
        provider=work_in.provider,
        model=work_in.model,
    )
    session.add(work)
    await session.commit()
    await session.refresh(work)
    await _emit_ai_work_event(session, work, EventType.AI_WORK_STARTED, "agent", work.agent_id)
    return work


async def _ensure_ai_work_owned(
    session: AsyncSession, principal: Principal, work: AIWorkLogModel
) -> None:
    """Ownership for a PATCH: `AIWorkLogModel.machine_id` is nullable (an
    entry logged by a coordinator not tied to a specific machine), so the
    non-null `agent_id` (per the audit's "agent_id sur AIWorkLog") is the
    fallback — the same actor-ownership shape `events.resolve_event_identity`
    already uses for `actor_type=agent`."""
    ensure_can_write(principal, "ai_work")
    if principal.role == Role.ADMIN:
        return
    if work.machine_id is not None:
        if work.machine_id != principal.machine.id:
            raise forbidden("ai_work", "update")
        return
    agent = await session.get(AgentModel, work.agent_id)
    if agent is None or agent.machine_id != principal.machine.id:
        raise forbidden("ai_work", "update")


def _ensure_can_resolve_review(
    principal: Principal, work: AIWorkLogModel, target: AIWorkStatus
) -> None:
    """Approving or requesting changes (DEC-0041) is a human decision distinct
    from the owning agent/machine's own writes: only `admin` may set these two
    statuses — the non-admin owning machine never can, unlike every other
    AIWorkLog PATCH (`_ensure_ai_work_owned`) — and only out of
    `review_requested`. Like every other ownership check in this module
    (`ensure_machine_owned`, `_ensure_ai_work_owned`), `admin` bypasses
    ownership by design: an admin machine that also happens to own the work
    can still resolve its own review, the same systemic trust boundary as
    anywhere else `Role.ADMIN` is checked, not a gap specific to review."""
    ensure_can_write(principal, "ai_work")
    if principal.role != Role.ADMIN:
        raise forbidden("ai_work", "resolve_review")
    if work.status != AIWorkStatus.REVIEW_REQUESTED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "invalid_status_transition",
                "message": f"cannot set status {target.value!r} from {work.status!r}",
            },
        )


async def update_ai_work(
    session: AsyncSession, principal: Principal, work: AIWorkLogModel, work_in: AIWorkLogUpdate
) -> AIWorkLogModel:
    previous_status = work.status
    if work_in.status in _REVIEW_RESOLUTIONS:
        _ensure_can_resolve_review(principal, work, work_in.status)
    else:
        await _ensure_ai_work_owned(session, principal, work)

    if work_in.summary is not None:
        work.summary = work_in.summary
    if work_in.status is not None:
        work.status = work_in.status.value
        if work_in.status in (AIWorkStatus.COMPLETED, AIWorkStatus.FAILED):
            work.ended_at = datetime.now(UTC)
    if work_in.changed_files is not None:
        work.changed_files = work_in.changed_files
    if work_in.tests_run is not None:
        work.tests_run = work_in.tests_run
    await session.commit()
    await session.refresh(work)

    if work_in.status is not None and work_in.status.value != previous_status:
        event_type = _STATUS_EVENT_TYPES.get(work_in.status)
        if event_type is not None:
            actor_type: ActorType
            actor_id: uuid.UUID
            if work_in.status in _REVIEW_RESOLUTIONS:
                actor_type, actor_id = "user", principal.user.id
            else:
                actor_type, actor_id = "agent", work.agent_id
            await _emit_ai_work_event(session, work, event_type, actor_type, actor_id)
    return work
