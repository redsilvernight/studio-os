from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Query
from studio_contracts.timeline import Timeline

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN
from studio_api.services import timeline as timeline_service

router = APIRouter(prefix="/api/v1/timeline", tags=["timeline"])


@router.get(
    "",
    response_model=Timeline,
    description=(
        "Day-grouped project activity (newest day first), unfiltered — the "
        "full history, not an actionable signal (see GET /review-queue for "
        "that). Inherits GET /events's 'not claimed exhaustive' honesty: "
        "several event types have no server-side emission yet. Any "
        "authenticated machine with access to the project may read; any "
        "other project answers `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def get_timeline(
    session: DbSession,
    principal: CurrentPrincipal,
    project_id: UUID = Query(...),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=0, le=500),
    until: datetime | None = Query(default=None, description="Exclusive upper timestamp bound."),
    offset: int = Query(
        default=0, ge=0, description="Rows to skip in timestamp/sequence descending order."
    ),
) -> Timeline:
    return await timeline_service.get_timeline(
        session,
        principal,
        project_id=project_id,
        since=since,
        limit=limit,
        until=until,
        offset=offset,
    )


@router.get(
    "/dates",
    response_model=list[date],
    description=(
        "Complete UTC dates of project events and recorded session starts/ends, newest first. "
        "Independent of timeline page limits. Restricted to an accessible project."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def get_timeline_dates(
    session: DbSession,
    principal: CurrentPrincipal,
    project_id: UUID = Query(...),
) -> list[date]:
    return await timeline_service.get_timeline_dates(session, principal, project_id)
