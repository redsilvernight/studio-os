from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from studio_contracts.builds import Build, BuildStatus

from studio_api.deps import CurrentMachine, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_404_NOT_FOUND
from studio_api.services import github as github_service

router = APIRouter(prefix="/api/v1/builds", tags=["builds"])


@router.get(
    "",
    response_model=list[Build],
    description=(
        "List CI builds observed on wired GitHub repositories, newest first. "
        "Any authenticated machine may read."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_builds(
    session: DbSession,
    machine: CurrentMachine,
    project_id: UUID | None = Query(default=None),
    status: BuildStatus | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[Build]:
    builds = await github_service.list_builds(
        session,
        project_id=project_id,
        status_value=status.value if status is not None else None,
        limit=limit,
    )
    return [Build.model_validate(b) for b in builds]


@router.get(
    "/{build_id}",
    response_model=Build,
    description="Get one build by id. Any authenticated machine may read.",
    responses={**RESP_401_UNAUTHORIZED, **RESP_404_NOT_FOUND},
)
async def get_build(build_id: UUID, session: DbSession, machine: CurrentMachine) -> Build:
    build = await github_service.get_build(session, build_id)
    if build is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "build not found")
    return Build.model_validate(build)
