from __future__ import annotations

from datetime import datetime
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
    limit: int = Query(default=200, le=500),
) -> Timeline:
    return await timeline_service.get_timeline(
        session, principal, project_id=project_id, since=since, limit=limit
    )
