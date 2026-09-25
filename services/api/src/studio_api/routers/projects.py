from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from studio_contracts.auth import Role
from studio_contracts.claims import ResourceClaim
from studio_contracts.project_state import ProjectState
from studio_contracts.projects import Project, ProjectCreate, ProjectMember
from studio_contracts.tasks import Task

from studio_api.db.models.user import UserModel
from studio_api.deps import CurrentPrincipal, DbSession, require_roles
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import projects as projects_service

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get(
    "",
    response_model=list[Project],
    description=(
        "List the projects the caller may access: every project for an "
        "admin, the projects the caller's User is a member of otherwise."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_projects(session: DbSession, principal: CurrentPrincipal) -> list[Project]:
    projects = await projects_service.list_projects(session, principal)
    return [Project.model_validate(p) for p in projects]


@router.post(
    "",
    response_model=Project,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create a project. Requires a privileged role (admin or "
        "developer); other roles receive `403 forbidden`. Slugs are "
        "unique: reusing one fails with 409. The creator becomes a member "
        "of the new project. Accepts `Idempotency-Key` for safe retries."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_IDEMPOTENCY},
)
async def create_project(
    project_in: ProjectCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    _owner: Annotated[UserModel, Depends(require_roles(Role.ADMIN, Role.DEVELOPER))],
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> Project:
    async def _create() -> Project:
        return Project.model_validate(
            await projects_service.create_project(
                session,
                project_in.slug,
                project_in.name,
                project_in.description,
                creator=principal.user,
            )
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /projects",
        Project,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "/{project_id}",
    response_model=Project,
    description=(
        "Get one project by id. A project the caller may not access — "
        "nonexistent included — answers `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_project(project_id: UUID, session: DbSession, principal: CurrentPrincipal) -> Project:
    project = await projects_service.get_project(session, principal, project_id)
    return Project.model_validate(project)


@router.get(
    "/{project_id}/state",
    response_model=ProjectState,
    description=(
        "Bootstrap read for a project: its active tasks and active "
        "resource claims in one call. Start here before working on a "
        "project. Same project access rule as `GET /projects/{id}`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_project_state(
    project_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> ProjectState:
    await projects_service.get_project(session, principal, project_id)
    tasks = await projects_service.get_active_tasks(session, principal, project_id)
    claims = await projects_service.get_active_claims(session, principal, project_id)

    return ProjectState(
        project_id=project_id,
        active_tasks=[Task.model_validate(t) for t in tasks],
        active_claims=[ResourceClaim.model_validate(c) for c in claims],
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMember],
    description=(
        "List the users with access to a project. Requires the "
        "admin role: any other role gets `403 forbidden` before any lookup. "
        "Unknown project: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def list_project_members(
    project_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> list[ProjectMember]:
    projects_service.ensure_members_admin(principal, "read")
    members = await projects_service.list_members(session, project_id)
    return [ProjectMember.model_validate(m) for m in members]


@router.put(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMember,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Grant a user access to a project (admin only). `201` with the new "
        "membership; granting an existing member returns it unchanged with "
        "`200` (the original `granted_by_user_id` is kept). Naturally "
        "idempotent: no `Idempotency-Key`. Unknown project or user: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def grant_project_member(
    project_id: UUID,
    user_id: UUID,
    response: Response,
    session: DbSession,
    principal: CurrentPrincipal,
) -> ProjectMember:
    projects_service.ensure_members_admin(principal, "write")
    membership, created = await projects_service.grant_member(
        session, project_id, user_id, granted_by_user_id=principal.user.id
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return ProjectMember.model_validate(membership)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Remove a user's access to a project (admin only). Idempotent `204`; "
        "the user's open event streams on this project are closed. Unknown "
        "project or user: 404."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def revoke_project_member(
    project_id: UUID, user_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> Response:
    projects_service.ensure_members_admin(principal, "write")
    await projects_service.revoke_member(session, project_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
