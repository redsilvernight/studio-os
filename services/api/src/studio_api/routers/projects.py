from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from studio_contracts.auth import Role
from studio_contracts.claims import ResourceClaim
from studio_contracts.project_state import ProjectState
from studio_contracts.projects import Project, ProjectCreate
from studio_contracts.tasks import Task

from studio_api.db.models.user import UserModel
from studio_api.deps import CurrentMachine, DbSession, require_roles
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
    description="List all projects. Any authenticated machine may read.",
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_projects(session: DbSession, machine: CurrentMachine) -> list[Project]:
    projects = await projects_service.list_projects(session)
    return [Project.model_validate(p) for p in projects]


@router.post(
    "",
    response_model=Project,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create a project. Requires a privileged role (admin or "
        "developer); other roles receive `403 forbidden`. Slugs are "
        "unique: reusing one fails with 409. Accepts `Idempotency-Key` "
        "for safe retries."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_IDEMPOTENCY},
)
async def create_project(
    project_in: ProjectCreate,
    request: Request,
    session: DbSession,
    machine: CurrentMachine,
    _owner: Annotated[UserModel, Depends(require_roles(Role.ADMIN, Role.DEVELOPER))],
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> Project:
    async def _create() -> Project:
        return Project.model_validate(
            await projects_service.create_project(
                session, project_in.slug, project_in.name, project_in.description
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
    description="Get one project by id. Any authenticated machine may read.",
    responses={**RESP_401_UNAUTHORIZED, **RESP_404_NOT_FOUND},
)
async def get_project(project_id: UUID, session: DbSession, machine: CurrentMachine) -> Project:
    project = await projects_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return Project.model_validate(project)


@router.get(
    "/{project_id}/state",
    response_model=ProjectState,
    description=(
        "Bootstrap read for a project: its active tasks and active "
        "resource claims in one call. Start here before working on a "
        "project. Any authenticated machine may read."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_404_NOT_FOUND},
)
async def get_project_state(
    project_id: UUID, session: DbSession, machine: CurrentMachine
) -> ProjectState:
    project = await projects_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    tasks = await projects_service.get_active_tasks(session, project_id)
    claims = await projects_service.get_active_claims(session, project_id)

    return ProjectState(
        project_id=project_id,
        active_tasks=[Task.model_validate(t) for t in tasks],
        active_claims=[ResourceClaim.model_validate(c) for c in claims],
        generated_at=datetime.now(UTC),
    )
