from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role

from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.user import UserModel
from studio_api.services import event_stream
from studio_api.services.authz import (
    Principal,
    ProjectAction,
    ensure_project_access,
    forbidden,
    project_visibility_clause,
)


async def list_projects(session: AsyncSession, principal: Principal) -> list[ProjectModel]:
    """Only the projects the caller may access (DEC-0103 §7)."""
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
    project (DEC-0103 §5) — an admin included, so a later demotion keeps
    access consistent. `creator=None` only for the operator CLI, which grants
    explicitly afterwards."""
    existing = await session.execute(select(ProjectModel).where(ProjectModel.slug == slug))
    if existing.scalar_one_or_none() is not None:
        # Slugs are non-secret (accepted oracle, DEC slug): a non-member with
        # a provisioning role learns that a slug exists via this 409 — the
        # same answer `POST /projects` and initialization apply give. The
        # structured `conflict` code keeps MCP machine-readable (never the
        # generic `error` fallback of `run_tool` on a plain-string detail).
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "conflict",
                "message": "project slug already exists",
                "slug": slug,
            },
        )
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


def ensure_members_admin(principal: Principal, action: ProjectAction) -> None:
    """Granting access is `admin` only, never self-service (DEC-0103). Runs
    before any lookup: a non-admin gets the same 403 for any project id."""
    if principal.role != Role.ADMIN:
        raise forbidden("project_members", action)


async def _ensure_project_and_user(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> None:
    if await session.get(ProjectModel, project_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "not_found", "message": f"project {project_id} not found"},
        )
    if user_id is not None and await session.get(UserModel, user_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "not_found", "message": f"user {user_id} not found"},
        )


async def list_members(
    session: AsyncSession, project_id: uuid.UUID
) -> list[ProjectMembershipModel]:
    await _ensure_project_and_user(session, project_id)
    result = await session.execute(
        select(ProjectMembershipModel)
        .where(ProjectMembershipModel.project_id == project_id)
        .order_by(ProjectMembershipModel.created_at, ProjectMembershipModel.user_id)
    )
    return list(result.scalars().all())


async def list_user_memberships(
    session: AsyncSession, user_id: uuid.UUID
) -> list[ProjectMembershipModel]:
    result = await session.execute(
        select(ProjectMembershipModel)
        .where(ProjectMembershipModel.user_id == user_id)
        .order_by(ProjectMembershipModel.created_at, ProjectMembershipModel.project_id)
    )
    return list(result.scalars().all())


async def grant_member(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    granted_by_user_id: uuid.UUID,
) -> tuple[ProjectMembershipModel, bool]:
    """Returns the membership and whether it was created. Granting an existing
    member is a no-op: the original `granted_by_user_id` is kept."""
    await _ensure_project_and_user(session, project_id, user_id)
    inserted = await session.execute(
        pg_insert(ProjectMembershipModel)
        .values(project_id=project_id, user_id=user_id, granted_by_user_id=granted_by_user_id)
        .on_conflict_do_nothing()
        .returning(ProjectMembershipModel.user_id)
    )
    created = inserted.scalar_one_or_none() is not None
    await session.commit()
    membership = await session.get(
        ProjectMembershipModel, (project_id, user_id), populate_existing=True
    )
    assert membership is not None
    return membership, created


async def revoke_member(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Idempotent. After the commit, the user's open SSE streams on the
    project close (in-process signal; other processes rely on the streams'
    periodic revalidation). Returns whether a membership was removed."""
    await _ensure_project_and_user(session, project_id, user_id)
    result = await session.execute(
        delete(ProjectMembershipModel)
        .where(
            ProjectMembershipModel.project_id == project_id,
            ProjectMembershipModel.user_id == user_id,
        )
        .returning(ProjectMembershipModel.user_id)
    )
    removed = result.scalar_one_or_none() is not None
    await session.commit()
    if removed:
        event_stream.revoke_access(user_id, project_id)
    return removed
