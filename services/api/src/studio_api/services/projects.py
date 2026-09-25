from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.user import UserModel
from studio_api.services.authz import Principal, ensure_project_access, project_visibility_clause


async def list_projects(session: AsyncSession, principal: Principal) -> list[ProjectModel]:
    """Only the projects the caller may access (DEC-0100 §7)."""
    query = select(ProjectModel).where(ProjectModel.archived.is_(False))
    visible = project_visibility_clause(principal, ProjectModel.id)
    if visible is not None:
        query = query.where(visible)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_project(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> ProjectModel:
    """403 before the lookup: inaccessible and nonexistent look the same to a
    non-member; 404 only for a caller entitled to the id (an admin)."""
    ensure_project_access(principal, project_id)
    project = await session.get(ProjectModel, project_id)
    if project is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "not_found", "message": f"project {project_id} not found"},
        )
    return project


async def create_project(
    session: AsyncSession,
    slug: str,
    name: str,
    description: str | None,
    *,
    creator: UserModel | None,
) -> ProjectModel:
    """Common creation point of `POST /projects` and initialization (HTTP and
    MCP). The creator's membership is written in the same commit as the
    project (DEC-0100 §5) — an admin included, so a later demotion keeps
    access consistent. `creator=None` only for the operator CLI, which grants
    explicitly afterwards."""
    existing = await session.execute(select(ProjectModel).where(ProjectModel.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "project slug already exists")
    project = ProjectModel(slug=slug, name=name, description=description)
    session.add(project)
    await session.flush()
    if creator is not None:
        await session.execute(
            pg_insert(ProjectMembershipModel)
            .values(project_id=project.id, user_id=creator.id, granted_by_user_id=creator.id)
            .on_conflict_do_nothing()
        )
    await session.commit()
    await session.refresh(project)
    return project


async def get_active_tasks(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[TaskModel]:
    ensure_project_access(principal, project_id)
    result = await session.execute(
        select(TaskModel).where(
            TaskModel.project_id == project_id,
            TaskModel.status.in_(["created", "in_progress", "blocked"]),
        )
    )
    return list(result.scalars().all())


async def get_active_claims(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[ResourceClaimModel]:
    ensure_project_access(principal, project_id)
    now = datetime.now(UTC)
    result = await session.execute(
        select(ResourceClaimModel).where(
            ResourceClaimModel.project_id == project_id,
            ResourceClaimModel.status == "active",
            ResourceClaimModel.expires_at > now,
        )
    )
    return list(result.scalars().all())
