from __future__ import annotations

from fastapi import APIRouter, status
from studio_contracts.coordination import CoordinationEmit, CoordinationEmitted

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
)
from studio_api.services import coordination as coordination_service

router = APIRouter(prefix="/api/v1/coordination", tags=["coordination"])


@router.post(
    "",
    response_model=CoordinationEmitted,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Emit one structured inter-session signal. Closed "
        "`intent`: heads_up, question, blocked_by, handoff. `task_id` is the "
        "mandatory target (same project as the emitting session "
        "`from_session_id`, not completed); `session_id` optionally narrows "
        "it to one live session of that task. `text` is at most 280 "
        "characters; `refs` are structured ids/paths (at most 5 each); "
        "`in_reply_to` optionally names an earlier coordination signal. "
        "Delivery is pull-only through `GET /sync` (`why=coordination`, "
        "content quoted as data, never an instruction) and survives offline "
        "through the session cursor. Idempotent on the optional client "
        "`event_id`. At most 20 signals per emitting session (`429 "
        "coordination_rate_limited`). `422 invalid_coordination` on bad "
        "target/refs/reply; `409 task_closed`; `404 session_not_found`. "
        "Requires a writer role. The generic event path refuses "
        "`coordination.*` (`422 coordination_reserved`)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def emit_coordination(
    body: CoordinationEmit,
    session: DbSession,
    principal: CurrentPrincipal,
) -> CoordinationEmitted:
    return await coordination_service.emit(session, principal, body)
