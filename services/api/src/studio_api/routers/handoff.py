from __future__ import annotations

from fastapi import APIRouter, Header, Request, status
from studio_contracts.handoff import HandoffRequest, HandoffResult

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
)
from studio_api.services import handoff as handoff_service
from studio_api.services import idempotency as idempotency_service

router = APIRouter(prefix="/api/v1/handoff", tags=["handoff"])


@router.post(
    "",
    response_model=HandoffResult,
    description=(
        "Close a work session in one call. Requires a writer role. "
        "Updates the task status (with `expected_version` for optimistic "
        "concurrency), releases all claims for the task, logs AI work "
        "(if `agent_id` + `summary` provided), and ends the session. "
        "The calling machine must own the session. `agent_id` must belong "
        "to the caller's machine. Compact response: ids + statuses only. "
        "Accepts `Idempotency-Key`: the same key returns the original "
        "result instead of running the composite again."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_IDEMPOTENCY,
        409: {
            "description": "Invalid session (no task), version conflict, or actor_not_owned."
        },
    },
)
async def handoff(
    request_in: HandoffRequest,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> HandoffResult:
    async def _run() -> HandoffResult:
        return await handoff_service.handoff(session, principal, request_in)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /handoff",
        HandoffResult,
        _run,
        status.HTTP_200_OK,
    )