from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from studio_contracts.mission import (
    MISSION_DEFAULT_LIMIT,
    MISSION_MAX_LIMIT,
    MissionProtocolState,
    MissionRun,
    ProjectMission,
)

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN
from studio_api.services import mission as mission_service

router = APIRouter(prefix="/api/v1/projects", tags=["review-queue"])

MissionProtocolState.__doc__ = (
    "Protocol closure of the run, reported apart from the process result: "
    "`handed_off` (the session ended and a non-`started` AI work entry is "
    "linked to it), `ended_without_handoff` (the session ended with no such "
    "entry), `open` (the session has not ended) and `missing` (no session)."
)
# The published OpenAPI document carries no internal decision number, so the
# enum's docstring is republished here in public wording, and the models
# carrying it are rebuilt because pydantic froze that docstring into their
# schema at import. The contract is left untouched: same members, same values.
MissionRun.model_rebuild(force=True)
ProjectMission.model_rebuild(force=True)


@router.get(
    "/{project_id}/mission",
    response_model=ProjectMission,
    description=(
        "Mission Control read model: a bounded, read-only projection of the "
        "project's executions, built at read time from task launches, work "
        "sessions, AI work, resource claims, machines and proposed "
        "decisions. One run per launch, plus one per session no launch "
        "references. Each run carries the server-derived verdict and every "
        "reason that produced it (the winning one first), so a discordant "
        "state stays visible; `counts` covers the whole window, not only the "
        "returned page. Clients display the verdict and never re-derive it. "
        "A `project_id` the caller cannot access answers `403 forbidden`. "
        "Clients must tolerate an unknown `verdict`, `reason`, "
        "`protocol_state` or `data_gaps` value."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def get_project_mission(
    project_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    window_hours: int = Query(default=mission_service.MISSION_DEFAULT_WINDOW_HOURS, le=720),
    limit: int = Query(default=MISSION_DEFAULT_LIMIT, ge=1, le=MISSION_MAX_LIMIT),
    cursor: str | None = Query(default=None),
) -> ProjectMission:
    return await mission_service.get_project_mission(
        session, principal, project_id, window_hours=window_hours, limit=limit, cursor=cursor
    )
