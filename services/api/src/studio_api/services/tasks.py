from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.events import EventCreate, EventType
from studio_contracts.tasks import TaskCreate, TaskUpdate

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.task import TaskModel
from studio_api.services import events as events_service
from studio_api.services.authz import Principal, ensure_can_write, ensure_machine_owned

_STATUS_EVENT_TYPES: dict[str, EventType] = {
    "in_progress": EventType.TASK_STARTED,
    "blocked": EventType.TASK_BLOCKED,
    "completed": EventType.TASK_COMPLETED,
}


async def list_tasks(
    session: AsyncSession, project_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0
) -> list[TaskModel]:
    stmt = select(TaskModel).limit(limit).offset(offset)
    if project_id is not None:
        stmt = stmt.where(TaskModel.project_id == project_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> TaskModel | None:
    return await session.get(TaskModel, task_id)


async def _actor(
    session: AsyncSession, principal: Principal, agent_id: uuid.UUID | None
) -> tuple[Literal["user", "agent"], uuid.UUID]:
    if agent_id is not None:
        agent = await session.get(AgentModel, agent_id)
        if agent is not None and agent.machine_id == principal.machine.id:
            return "agent", agent.id
    return "user", principal.user.id


async def _commit_with_event(
    session: AsyncSession,
    principal: Principal,
    task: TaskModel,
    event_type: EventType,
    payload: dict[str, Any],
    agent_id: uuid.UUID | None = None,
) -> TaskModel:
    """Commits the task write and its event atomically, then fans the event
    out to the SSE stream (TECH/03_EVENT_CONTRACT.md, emission serveur Tasks)."""
    actor_type, actor_id = await _actor(session, principal, agent_id)
    event = await events_service.stage_event(
        session,
        EventCreate(
            event_id=uuid.uuid4(),
            event_type=event_type,
            project_id=task.project_id,
            task_id=task.id,
            machine_id=principal.machine.id,
            actor_type=actor_type,
            actor_id=actor_id,
            client_timestamp=datetime.now(UTC),
            payload={"status": task.status, "version": task.version, **payload},
        ),
    )
    await session.commit()
    await session.refresh(task)
    await session.refresh(event)
    events_service.publish_event(event)
    return task


async def add_task(session: AsyncSession, principal: Principal, task_in: TaskCreate) -> TaskModel:
    """`create_task` without the commit (DEC-0084 F1): stages the row and
    flushes so its id exists, leaving the transaction to the caller — used by
    units of work (Roadmap hydration) that must create several Tasks atomically."""
    ensure_can_write(principal, "task")
    task = TaskModel(
        project_id=task_in.project_id, title=task_in.title, description=task_in.description
    )
    session.add(task)
    await session.flush()
    return task


async def create_task(
    session: AsyncSession, principal: Principal, task_in: TaskCreate
) -> TaskModel:
    task = await add_task(session, principal, task_in)
    await session.refresh(task)
    return await _commit_with_event(
        session, principal, task, EventType.TASK_CREATED, {"transition": "created"}
    )


async def update_task(
    session: AsyncSession,
    principal: Principal,
    task: TaskModel,
    task_in: TaskUpdate,
    expected_version: int,
) -> TaskModel:
    ensure_can_write(principal, "task")
    if task.version != expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "version_conflict", "server_version": task.version},
        )
    previous_status = task.status
    if task_in.title is not None:
        task.title = task_in.title
    if task_in.description is not None:
        task.description = task_in.description
    if task_in.status is not None:
        task.status = task_in.status.value
    task.version += 1
    event_type = EventType.TASK_UPDATED
    if task.status != previous_status:
        event_type = _STATUS_EVENT_TYPES.get(task.status, EventType.TASK_UPDATED)
    return await _commit_with_event(
        session,
        principal,
        task,
        event_type,
        {"transition": "updated", "previous_status": previous_status},
        agent_id=task.claimed_by_agent_id,
    )


async def claim_task(
    session: AsyncSession,
    principal: Principal,
    task: TaskModel,
    machine_id: uuid.UUID,
    agent_id: uuid.UUID | None,
) -> TaskModel:
    ensure_can_write(principal, "task")
    if task.claimed_by_machine_id is not None and task.claimed_by_machine_id != machine_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"error_code": "already_claimed"})
    previous_status = task.status
    task.claimed_by_machine_id = machine_id
    task.claimed_by_agent_id = agent_id
    task.status = "in_progress"
    task.version += 1
    return await _commit_with_event(
        session,
        principal,
        task,
        EventType.TASK_STARTED,
        {"transition": "claimed", "previous_status": previous_status},
        agent_id=agent_id,
    )


async def release_task(session: AsyncSession, principal: Principal, task: TaskModel) -> TaskModel:
    ensure_machine_owned(principal, task.claimed_by_machine_id, "task", "release")
    agent_id = task.claimed_by_agent_id
    task.claimed_by_machine_id = None
    task.claimed_by_agent_id = None
    task.version += 1
    return await _commit_with_event(
        session,
        principal,
        task,
        EventType.TASK_UPDATED,
        {"transition": "released"},
        agent_id=agent_id,
    )
