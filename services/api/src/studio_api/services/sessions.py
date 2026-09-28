from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.events import ActorType, EventCreate, EventType
from studio_contracts.sessions import SessionStatus, WorkSessionCreate

from studio_api.db.models.task import TaskModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import claims as claims_service
from studio_api.services import events as events_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ProjectAction,
    ensure_can_write,
    ensure_machine_owned,
    ensure_project_access,
    project_visibility_clause,
)
from studio_api.settings import Settings

_SESSION_EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "studio-os/session-events")


def _derive_session_event_id(session_id: uuid.UUID, event_type: EventType) -> uuid.UUID:
    """Deterministic on (session_id, event_type): ending the same session twice
    resolves to the same event via get-or-create, never a duplicate — the same
    pattern AI work and Producer jobs use."""
    return uuid.uuid5(_SESSION_EVENT_NAMESPACE, f"{session_id}:{event_type.value}")


async def _session_project_id(
    session: AsyncSession, work_session: WorkSessionModel
) -> uuid.UUID | None:
    """Sessions hang off an optional task; without one there is no project
    scope to publish under, so no event is emitted."""
    if work_session.task_id is None:
        return None
    task = await tasks_service.get_task(session, work_session.task_id)
    return task.project_id if task is not None else None


async def _emit_session_event(
    session: AsyncSession,
    principal: Principal,
    work_session: WorkSessionModel,
    event_type: EventType,
) -> None:
    project_id = await _session_project_id(session, work_session)
    if project_id is None:
        return
    if work_session.agent_id is not None:
        actor_type: ActorType = "agent"
        actor_id = work_session.agent_id
    else:
        actor_type = "system"
        actor_id = principal.machine.id
    await events_service.create_event(
        session,
        EventCreate(
            event_id=_derive_session_event_id(work_session.id, event_type),
            event_type=event_type,
            project_id=project_id,
            task_id=work_session.task_id,
            machine_id=principal.machine.id,
            actor_type=actor_type,
            actor_id=actor_id,
            client_timestamp=datetime.now(UTC),
            payload={"session_id": str(work_session.id)},
        ),
    )


async def _ensure_task_project_access(
    session: AsyncSession, principal: Principal, task_id: uuid.UUID | None, action: ProjectAction
) -> None:
    """A session has no project of its own: it is visible through
    session -> task -> project only (DEC-0103 §11). An unknown task has no
    project to check; the caller's own not-found handling applies."""
    if task_id is None:
        return
    task = await tasks_service.get_task(session, task_id)
    if task is not None:
        ensure_project_access(principal, task.project_id, action)


async def list_sessions(
    session: AsyncSession,
    principal: Principal,
    task_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    open_only: bool = False,
) -> list[WorkSessionModel]:
    stmt = select(WorkSessionModel)
    if task_id is not None:
        await _ensure_task_project_access(session, principal, task_id, "read")
        stmt = stmt.where(WorkSessionModel.task_id == task_id)
    elif (visible := project_visibility_clause(principal, TaskModel.project_id)) is not None:
        stmt = stmt.join(TaskModel, WorkSessionModel.task_id == TaskModel.id).where(visible)
    if agent_id is not None:
        stmt = stmt.where(WorkSessionModel.agent_id == agent_id)
    if open_only:
        stmt = stmt.where(WorkSessionModel.ended_at.is_(None))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _find_open_session(
    session: AsyncSession,
    task_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    machine_id: uuid.UUID,
) -> WorkSessionModel | None:
    """The calling machine's open session (never ended) for this agent on
    the task, newest first (AIB-H). Ownership mirrors `end_session`: a
    session is that machine's live presence on the work, so another machine
    never resumes it."""
    stmt = (
        select(WorkSessionModel)
        .where(
            WorkSessionModel.task_id == task_id,
            WorkSessionModel.machine_id == machine_id,
            WorkSessionModel.ended_at.is_(None),
        )
        .order_by(WorkSessionModel.started_at.desc())
    )
    if agent_id is None:
        stmt = stmt.where(WorkSessionModel.agent_id.is_(None))
    else:
        stmt = stmt.where(WorkSessionModel.agent_id == agent_id)
    result = await session.execute(stmt)
    return result.scalars().first()


async def authorize_start(
    session: AsyncSession, principal: Principal, task_id: uuid.UUID | None
) -> None:
    """Project (via the task) then role check of a session start, run ahead
    of the idempotency replay short-circuit (DEC-0036, DEC-0103 §12)."""
    await _ensure_task_project_access(session, principal, task_id, "write")
    ensure_can_write(principal, "session")


async def resume_or_start_session(
    session: AsyncSession,
    principal: Principal,
    session_in: WorkSessionCreate,
    settings: Settings,
) -> tuple[WorkSessionModel, bool]:
    """Resume-or-create (AIB-H), the session half of `studio_start_work`:
    the calling machine's open session for the same agent on the task is
    resumed (touched, `resumed=True`); an open session whose derived
    presence is `expired` is **closed first** (the effective closing C1
    deferred to L2) and a fresh one created (`resumed=False`), as is the
    case with no open session. An `ended` session is never reused. The
    caller is authorized exactly like a start; closing emits `session.ended`
    then the new one `session.started`. Returns `(session, resumed)`."""
    await authorize_start(session, principal, session_in.task_id)
    # Same ownership rule as `end_session`: a session is a machine's own
    # presence, so it never resumes (nor closes) another machine's session.
    ensure_machine_owned(principal, session_in.machine_id, "session", "resume")
    now = datetime.now(UTC)
    existing = await _find_open_session(
        session, session_in.task_id, session_in.agent_id, session_in.machine_id
    )
    if existing is not None and (
        derive_session_status(existing, settings) is not SessionStatus.EXPIRED
    ):
        existing.last_activity_at = now
        await session.commit()
        await session.refresh(existing)
        return existing, True
    if existing is not None:
        existing.ended_at = now
        existing.last_activity_at = now
        await session.commit()
        await session.refresh(existing)
        await _emit_session_event(session, principal, existing, EventType.SESSION_ENDED)
    work_session = WorkSessionModel(
        task_id=session_in.task_id,
        machine_id=session_in.machine_id,
        agent_id=session_in.agent_id,
        started_at=now,
        last_activity_at=now,
    )
    session.add(work_session)
    await session.commit()
    await session.refresh(work_session)
    await _emit_session_event(session, principal, work_session, EventType.SESSION_STARTED)
    return work_session, False


async def start_session(
    session: AsyncSession, principal: Principal, session_in: WorkSessionCreate
) -> WorkSessionModel:
    await authorize_start(session, principal, session_in.task_id)
    now = datetime.now(UTC)
    work_session = WorkSessionModel(
        task_id=session_in.task_id,
        machine_id=session_in.machine_id,
        agent_id=session_in.agent_id,
        started_at=now,
        last_activity_at=now,
    )
    session.add(work_session)
    await session.commit()
    await session.refresh(work_session)
    await _emit_session_event(session, principal, work_session, EventType.SESSION_STARTED)
    return work_session


async def end_session(
    session: AsyncSession, principal: Principal, session_id: uuid.UUID
) -> WorkSessionModel:
    work_session = await session.get(WorkSessionModel, session_id)
    if work_session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    await _ensure_task_project_access(session, principal, work_session.task_id, "write")
    ensure_machine_owned(principal, work_session.machine_id, "session", "end")
    if work_session.ended_at is not None:
        return work_session
    now = datetime.now(UTC)
    work_session.ended_at = now
    work_session.last_activity_at = now
    await session.commit()
    await session.refresh(work_session)
    await _emit_session_event(session, principal, work_session, EventType.SESSION_ENDED)
    # Release all claims for this task (L3 handoff minimal fallback)
    if work_session.task_id is not None:
        task = await tasks_service.get_task(session, work_session.task_id)
        if task is not None:
            await claims_service.release_task_claims_by_task(session, principal, task)
    return work_session


def _effective_activity(work_session: WorkSessionModel) -> datetime | None:
    """Newest known activity: explicit touches win, `started_at` is the
    fallback for rows predating C1 (migration 0020 backfilled them)."""
    return work_session.last_activity_at or work_session.started_at


def derive_session_status(work_session: WorkSessionModel, settings: Settings) -> SessionStatus:
    """Presence derived at read with configurable thresholds (C1, DEC-0157)
    — never stored, never a heartbeat. `ended` wins over every age; an
    expired session still reads `expired` until L2 (l2-resume) closes it."""
    if work_session.ended_at is not None:
        return SessionStatus.ENDED
    reference = _effective_activity(work_session)
    if reference is None:
        return SessionStatus.ACTIVE
    age = datetime.now(UTC) - reference
    if age > timedelta(seconds=settings.session_expire_after_seconds):
        return SessionStatus.EXPIRED
    if age > timedelta(seconds=settings.session_idle_after_seconds):
        return SessionStatus.IDLE
    return SessionStatus.ACTIVE


def derive_session_expiry(work_session: WorkSessionModel, settings: Settings) -> datetime | None:
    """When this session will read `expired` if nothing touches it — `None`
    for ended sessions. L2 (l2-resume) is the consumer that closes them."""
    if work_session.ended_at is not None:
        return None
    reference = _effective_activity(work_session)
    if reference is None:
        return None
    return reference + timedelta(seconds=settings.session_expire_after_seconds)


async def touch_session(session: AsyncSession, session_id: uuid.UUID) -> WorkSessionModel | None:
    """Record authenticated activity attached to a session (C1): the single
    writer of `last_activity_at`. Call only from an already-authorized
    session-attached call (start/end today; start_work, sync, event
    emission, ai_work and handoff in their own L2/L3/C2/C4 steps). Returns
    the session, or `None` when unknown. Never touches heartbeats."""
    work_session = await session.get(WorkSessionModel, session_id)
    if work_session is None:
        return None
    work_session.last_activity_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(work_session)
    return work_session
