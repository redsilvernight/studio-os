from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel


async def list_projects(session: AsyncSession) -> list[ProjectModel]:
    result = await session.execute(select(ProjectModel).where(ProjectModel.archived.is_(False)))
    return list(result.scalars().all())


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> ProjectModel | None:
    return await session.get(ProjectModel, project_id)


async def create_project(
    session: AsyncSession, slug: str, name: str, description: str | None
) -> ProjectModel:
    existing = await session.execute(select(ProjectModel).where(ProjectModel.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "project slug already exists")
    project = ProjectModel(slug=slug, name=name, description=description)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def get_active_tasks(session: AsyncSession, project_id: uuid.UUID) -> list[TaskModel]:
    result = await session.execute(
        select(TaskModel).where(
            TaskModel.project_id == project_id,
            TaskModel.status.in_(["created", "in_progress", "blocked"]),
        )
    )
    return list(result.scalars().all())


async def get_active_claims(
    session: AsyncSession, project_id: uuid.UUID
) -> list[ResourceClaimModel]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(ResourceClaimModel).where(
            ResourceClaimModel.project_id == project_id,
            ResourceClaimModel.status == "active",
            ResourceClaimModel.expires_at > now,
        )
    )
    return list(result.scalars().all())
