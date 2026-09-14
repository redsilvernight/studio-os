from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from studio_contracts.sessions import WorkSession, WorkSessionCreate

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.services import idempotency as idempotency_service
from studio_api.services import sessions as sessions_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.get("", response_model=list[WorkSession])
async def list_sessions(
    session: DbSession, machine: CurrentMachine, task_id: UUID | None = Query(default=None)
) -> list[WorkSession]:
    sessions = await sessions_service.list_sessions(session, task_id=task_id)
    return [WorkSession.model_validate(s) for s in sessions]


@router.post("", response_model=WorkSession, status_code=status.HTTP_201_CREATED)
async def start_session(
    session_in: WorkSessionCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> WorkSession:
    """Runs unconditionally, ahead of `run_idempotent`'s replay
    short-circuit — see `routers/tasks.py::create_task` for why (DEC-0036)."""
    ensure_can_write(principal, "session")

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


@router.patch("/{session_id}/end", response_model=WorkSession)
async def end_session(
    session_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> WorkSession:
    work_session = await sessions_service.end_session(session, principal, session_id)
    return WorkSession.model_validate(work_session)
