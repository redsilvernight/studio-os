from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.tasks import TaskCreate, TaskUpdate

from studio_api.db.models.task import TaskModel
from studio_api.services.authz import Principal, ensure_can_write, ensure_machine_owned


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
    await session.commit()
    await session.refresh(task)
    return task


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
    if task_in.title is not None:
        task.title = task_in.title
    if task_in.description is not None:
        task.description = task_in.description
    if task_in.status is not None:
        task.status = task_in.status.value
    task.version += 1
    await session.commit()
    await session.refresh(task)
    return task


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
    task.claimed_by_machine_id = machine_id
    task.claimed_by_agent_id = agent_id
    task.status = "in_progress"
    task.version += 1
    await session.commit()
    await session.refresh(task)
    return task


async def release_task(session: AsyncSession, principal: Principal, task: TaskModel) -> TaskModel:
    ensure_machine_owned(principal, task.claimed_by_machine_id, "task", "release")
    task.claimed_by_machine_id = None
    task.claimed_by_agent_id = None
    task.version += 1
    await session.commit()
    await session.refresh(task)
    return task
