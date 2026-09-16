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
        "exists for decisions), recent `resource.conflict` events "
        "within `conflict_window_hours` (best-effort and time-windowed: no "
        "persisted conflict state exists, an old unaddressed conflict "
        "silently ages out of the window), failed builds (`build_failure`, "
        "informational — no build transition endpoint exists), and opened "
        "PRs with no merge yet (`pr_ready`, best-effort and time-windowed "
        "like conflicts). Also serves as the notifications "
        "surface — there is no separate notifications endpoint. "
        "Any authenticated machine may read. Clients must tolerate an "
        "unknown `kind`."
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
