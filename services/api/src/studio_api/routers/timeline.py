from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from studio_contracts.timeline import Timeline

from studio_api.deps import CurrentMachine, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED
from studio_api.services import timeline as timeline_service

router = APIRouter(prefix="/api/v1/timeline", tags=["timeline"])


@router.get(
    "",
    response_model=Timeline,
    description=(
        "Day-grouped project activity (newest day first), unfiltered — the "
        "full history, not an actionable signal (see GET /review-queue for "
        "that). Inherits GET /events's 'not claimed exhaustive' honesty: "
        "several event types have no server-side emission yet (question "
        "ouverte n°9, ROADMAP_STEP8_BREAKDOWN.md). Any authenticated "
        "machine may read."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def get_timeline(
    session: DbSession,
    machine: CurrentMachine,
    project_id: UUID = Query(...),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, le=500),
) -> Timeline:
    return await timeline_service.get_timeline(
        session, project_id=project_id, since=since, limit=limit
    )
