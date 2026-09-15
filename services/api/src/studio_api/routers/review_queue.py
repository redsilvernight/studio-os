from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from studio_contracts.review_queue import ReviewQueue

from studio_api.deps import CurrentMachine, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED
from studio_api.services import review_queue as review_queue_service

router = APIRouter(prefix="/api/v1/review-queue", tags=["review-queue"])


@router.get(
    "",
    response_model=ReviewQueue,
    description=(
        "Aggregated view of everything waiting on a human decision: AI work "
        "in `review_requested` (resolve via `PATCH /ai-work/{id}`), "
        "decisions still `proposed` (informational — no transition endpoint "
        "exists for decisions), and recent `resource.conflict` events "
        "within `conflict_window_hours` (best-effort and time-windowed: no "
        "persisted conflict state exists, an old unaddressed conflict "
        "silently ages out of the window). Also serves as the notifications "
        "surface (DEC-0051) — there is no separate notifications endpoint. "
        "Any authenticated machine may read."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def get_review_queue(
    session: DbSession,
    machine: CurrentMachine,
    project_id: UUID | None = Query(default=None),
    conflict_window_hours: int = Query(default=24, le=168),
) -> ReviewQueue:
    return await review_queue_service.get_review_queue(
        session, project_id=project_id, conflict_window_hours=conflict_window_hours
    )
