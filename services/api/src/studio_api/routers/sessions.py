from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from studio_contracts.sessions import WorkSession, WorkSessionCreate

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import sessions as sessions_service

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.get(
    "",
    response_model=list[WorkSession],
    description=(
        "List work sessions, optionally filtered by task, restricted to "
        "sessions whose task belongs to an accessible project. A task of an "
        "inaccessible project answers `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_sessions(
    session: DbSession, principal: CurrentPrincipal, task_id: UUID | None = Query(default=None)
) -> list[WorkSession]:
    sessions = await sessions_service.list_sessions(session, principal, task_id=task_id)
    return [WorkSession.model_validate(s) for s in sessions]


@router.post(
    "",
    response_model=WorkSession,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Start a work session on a task for the caller's machine. "
        "Requires a writer role. Accepts `Idempotency-Key` for safe "
        "retries: the same key returns the original session instead of "
        "starting a duplicate."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_IDEMPOTENCY},
)
async def start_session(
    session_in: WorkSessionCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> WorkSession:
    await sessions_service.authorize_start(session, principal, session_in.task_id)

    async def _create() -> WorkSession:
        return WorkSession.model_validate(
            await sessions_service.start_session(session, principal, session_in)
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /sessions",
        WorkSession,
        _create,
        status.HTTP_201_CREATED,
    )


@router.patch(
    "/{session_id}/end",
    response_model=WorkSession,
    description=(
        "End a work session. Only the machine that started the session "
        "(or a privileged role) may end it; ending twice is a harmless "
        "no-op, never an error storm."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def end_session(
    session_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> WorkSession:
    work_session = await sessions_service.end_session(session, principal, session_id)
    return WorkSession.model_validate(work_session)
