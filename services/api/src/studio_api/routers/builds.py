from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from studio_contracts.builds import Build, BuildStatus

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
)
from studio_api.services import github as github_service

router = APIRouter(prefix="/api/v1/builds", tags=["builds"])


@router.get(
    "",
    response_model=list[Build],
    description=(
        "List CI builds of the caller's accessible projects, observed on "
        "wired GitHub repositories, newest first. A `project_id` the caller "
        "cannot access (or that does not exist) answers `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_builds(
    session: DbSession,
    principal: CurrentPrincipal,
    project_id: UUID | None = Query(default=None),
    status: BuildStatus | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[Build]:
    builds = await github_service.list_builds(
        session,
        principal,
        project_id=project_id,
        status_value=status.value if status is not None else None,
        limit=limit,
    )
    return [Build.model_validate(b) for b in builds]


@router.get(
    "/{build_id}",
    response_model=Build,
    description=(
        "Get one build by id. A build of a project the caller cannot access "
        "answers `403 forbidden` (resource `project`)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_build(build_id: UUID, session: DbSession, principal: CurrentPrincipal) -> Build:
    build = await github_service.get_build(session, principal, build_id)
    if build is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "build not found")
    return Build.model_validate(build)
