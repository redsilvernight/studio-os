from __future__ import annotations

from fastapi import APIRouter, Header, Request, status
from studio_contracts.start_work import StartWorkRequest, StartWorkResult

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import start_work as start_work_service
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1/start-work", tags=["start-work"])

_RESP_409_ACTOR_NOT_OWNED = {
    409: {
        "description": (
            "`actor_not_owned` (agent not attached to the caller's machine) or "
            "`idempotency_key_payload_mismatch`."
        )
    }
}


@router.post(
    "",
    response_model=StartWorkResult,
    description=(
        "Start or resume work on a task in one call. Requires a writer role. "
        "With `task_id`: claim the task for the caller's machine (idempotent) "
        "+ resume or create the agent's open session on it + the scoped "
        "project context. Without `task_id`: the project context plus the "
        "candidate tasks (current-step linked tasks first, then other "
        "unclaimed tasks), claiming nothing. `agent_id` must belong to the "
        "caller's machine (`409 actor_not_owned`). Always `200`: the response "
        "fields (`resumed`, `candidates`) tell a resumed session from a new "
        "one, so the status never varies under replay. Accepts "
        "`Idempotency-Key`: the same key returns the original result instead "
        "of claiming or starting again."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **_RESP_409_ACTOR_NOT_OWNED,
        **RESP_409_IDEMPOTENCY,
    },
)
async def start_work(
    request_in: StartWorkRequest,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> StartWorkResult:
    # Ahead of the idempotency replay short-circuit (DEC-0036).
    await start_work_service.authorize_start_work(session, principal, request_in)

    async def _run() -> StartWorkResult:
        return await start_work_service.start_work(session, principal, request_in, get_settings())

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /start-work",
        StartWorkResult,
        _run,
        status.HTTP_200_OK,
    )
