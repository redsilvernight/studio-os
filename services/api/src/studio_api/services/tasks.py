from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.tasks import TaskCreate, TaskUpdate

from studio_api.db.models.task import TaskModel


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


async def create_task(session: AsyncSession, task_in: TaskCreate) -> TaskModel:
    task = TaskModel(
        project_id=task_in.project_id, title=task_in.title, description=task_in.description
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def update_task(
    session: AsyncSession, task: TaskModel, task_in: TaskUpdate, expected_version: int
) -> TaskModel:
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
    session: AsyncSession, task: TaskModel, machine_id: uuid.UUID, agent_id: uuid.UUID | None
) -> TaskModel:
    if task.claimed_by_machine_id is not None and task.claimed_by_machine_id != machine_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"error_code": "already_claimed"})
    task.claimed_by_machine_id = machine_id
    task.claimed_by_agent_id = agent_id
    task.status = "in_progress"
    task.version += 1
    await session.commit()
    await session.refresh(task)
    return task


async def release_task(session: AsyncSession, task: TaskModel) -> TaskModel:
    task.claimed_by_machine_id = None
    task.claimed_by_agent_id = None
    task.version += 1
    await session.commit()
    await session.refresh(task)
    return task
