from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.projects import ProjectRead
from studio_contracts.repositories import normalize_remote_url

from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_repository import ProjectRepositoryModel
from studio_api.services.authz import (
    Principal,
    ensure_project_access,
    forbidden,
)


def authorize_repositories_write(principal: Principal, project_id: uuid.UUID) -> None:
    """Project then role check of a repository-link write, run ahead of any
    lookup (DEC-0103 §12): link management is `admin`/`developer` only — a
    `viewer` (readonly, agent) gets the same 403 for any project id."""
    ensure_project_access(principal, project_id, "write")
    if principal.role not in (Role.ADMIN, Role.DEVELOPER):
        raise forbidden("project_repository", "write")


async def _ensure_project(session: AsyncSession, project_id: uuid.UUID) -> ProjectModel:
    project = await session.get(ProjectModel, project_id)
    if project is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "not_found", "message": f"project {project_id} not found"},
        )
    return project


def _invalid_url(url: str, reason: object) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_repository_url", "message": str(reason)},
    )


def _already_linked(normalized: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "error_code": "repository_already_linked",
            "message": "repository is already linked to another project",
            "url": normalized,
        },
    )


async def _by_url(session: AsyncSession, normalized: str) -> ProjectRepositoryModel | None:
    result = await session.execute(
        select(ProjectRepositoryModel).where(ProjectRepositoryModel.normalized_url == normalized)
    )
    return result.scalar_one_or_none()


async def list_repository_urls(session: AsyncSession, project_id: uuid.UUID) -> list[str]:
    result = await session.execute(
        select(ProjectRepositoryModel.normalized_url)
        .where(ProjectRepositoryModel.project_id == project_id)
        .order_by(ProjectRepositoryModel.created_at, ProjectRepositoryModel.normalized_url)
    )
    return list(result.scalars().all())


async def project_read(session: AsyncSession, project: ProjectModel) -> ProjectRead:
    base = ProjectRead.model_validate(project)
    return base.model_copy(update={"repositories": await list_repository_urls(session, project.id)})


async def projects_read(session: AsyncSession, projects: list[ProjectModel]) -> list[ProjectRead]:
    ids = [p.id for p in projects]
    by_project: dict[uuid.UUID, list[str]] = {pid: [] for pid in ids}
    if ids:
        result = await session.execute(
            select(ProjectRepositoryModel.project_id, ProjectRepositoryModel.normalized_url)
            .where(ProjectRepositoryModel.project_id.in_(ids))
            .order_by(ProjectRepositoryModel.created_at, ProjectRepositoryModel.normalized_url)
        )
        for pid, url in result.all():
            by_project.setdefault(pid, []).append(url)
    return [
        ProjectRead.model_validate(p).model_copy(update={"repositories": by_project.get(p.id, [])})
        for p in projects
    ]


async def link_repository(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, url: str
) -> tuple[ProjectRepositoryModel, bool]:
    """Link a remote to a project. Returns the row and whether this call
    created it: re-linking the same URL to the same project is a no-op (like
    `grant_member`), while a URL owned by another project is a 409
    `repository_already_linked` — never silently moved."""
    authorize_repositories_write(principal, project_id)
    await _ensure_project(session, project_id)
    try:
        normalized = normalize_remote_url(url)
    except ValueError as exc:
        raise _invalid_url(url, exc) from None
    existing = await _by_url(session, normalized)
    if existing is not None:
        if existing.project_id == project_id:
            return existing, False
        raise _already_linked(normalized)
    row = ProjectRepositoryModel(
        project_id=project_id, normalized_url=normalized, created_by=principal.user.id
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raced = await _by_url(session, normalized)
        if raced is not None:
            if raced.project_id == project_id:
                return raced, False
            raise _already_linked(normalized) from None
        raise
    await session.refresh(row)
    return row, True


async def unlink_repository(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, normalized_url: str
) -> bool:
    """Idempotent removal of one linked remote. Returns whether a link was
    removed. The path value is re-normalized when possible so equivalent
    spellings of the same remote resolve to the stored canonical URL."""
    authorize_repositories_write(principal, project_id)
    await _ensure_project(session, project_id)
    try:
        target = normalize_remote_url(normalized_url)
    except ValueError:
        target = normalized_url
    result = await session.execute(
        delete(ProjectRepositoryModel)
        .where(
            ProjectRepositoryModel.project_id == project_id,
            ProjectRepositoryModel.normalized_url == target,
        )
        .returning(ProjectRepositoryModel.id)
    )
    removed = result.scalar_one_or_none() is not None
    await session.commit()
    return removed
