from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from studio_contracts.claims import ResourceClaim
from studio_contracts.project_state import ProjectState
from studio_contracts.projects import Project
from studio_contracts.tasks import Task

from studio_api.deps import CurrentMachine, DbSession
from studio_api.services import projects as projects_service

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=list[Project])
async def list_projects(session: DbSession, machine: CurrentMachine) -> list[Project]:
    projects = await projects_service.list_projects(session)
    return [Project.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: UUID, session: DbSession, machine: CurrentMachine) -> Project:
    project = await projects_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return Project.model_validate(project)


@router.get("/{project_id}/state", response_model=ProjectState)
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
