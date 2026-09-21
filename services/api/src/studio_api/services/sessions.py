from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.events import ActorType, EventCreate, EventType
from studio_contracts.sessions import WorkSessionCreate

from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import events as events_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal, ensure_can_write, ensure_machine_owned

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


async def list_sessions(
    session: AsyncSession, task_id: uuid.UUID | None = None
) -> list[WorkSessionModel]:
    stmt = select(WorkSessionModel)
    if task_id is not None:
        stmt = stmt.where(WorkSessionModel.task_id == task_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def start_session(
    session: AsyncSession, principal: Principal, session_in: WorkSessionCreate
) -> WorkSessionModel:
    ensure_can_write(principal, "session")
    work_session = WorkSessionModel(
        task_id=session_in.task_id,
        machine_id=session_in.machine_id,
        agent_id=session_in.agent_id,
        started_at=datetime.now(UTC),
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
    ensure_machine_owned(principal, work_session.machine_id, "session", "end")
    if work_session.ended_at is not None:
        return work_session
    work_session.ended_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(work_session)
    await _emit_session_event(session, principal, work_session, EventType.SESSION_ENDED)
    return work_session
