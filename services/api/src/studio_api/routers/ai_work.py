from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.ai_work import AIWorkLog, AIWorkLogCreate, AIWorkLogUpdate

from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_ACTOR_NOT_OWNED,
    RESP_409_IDEMPOTENCY,
    RESP_409_REVIEW_TRANSITION,
    merge_conflict,
)
from studio_api.services import ai_work as ai_work_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1/ai-work", tags=["ai-work"])


@router.get(
    "",
    response_model=list[AIWorkLog],
    description=(
        "List AI work ledger entries, optionally filtered by project or "
        "task. Any authenticated machine may read."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_ai_work(
    session: DbSession,
    machine: CurrentMachine,
    project_id: UUID | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
) -> list[AIWorkLog]:
    entries = await ai_work_service.list_ai_work(session, project_id=project_id, task_id=task_id)
    return [AIWorkLog.model_validate(e) for e in entries]


@router.post(
    "",
    response_model=AIWorkLog,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Log a unit of AI work. Requires a writer role. `agent_id` must "
        "reference an agent attached to the caller's own authenticated "
        "machine (register one with `POST /agents` first) — a foreign or "
        "unknown agent fails with `409 actor_not_owned`, never a silent "
        "cross-machine attribution. Accepts `Idempotency-Key` for safe "
        "retries."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **merge_conflict(RESP_409_ACTOR_NOT_OWNED, RESP_409_IDEMPOTENCY),
    },
)
async def create_ai_work(
    work_in: AIWorkLogCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> AIWorkLog:
    ensure_can_write(principal, "ai_work")

    async def _create() -> AIWorkLog:
        return AIWorkLog.model_validate(
            await ai_work_service.create_ai_work(session, principal, work_in)
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /ai-work",
        AIWorkLog,
        _create,
        status.HTTP_201_CREATED,
    )


@router.patch(
    "/{work_id}",
    response_model=AIWorkLog,
    description=(
        "Update your own work entry (status, changed files, tests run). "
        "Only the owning machine's entries may be updated. Resolving a "
        "review (`approved` or changes requested) additionally requires a "
        "privileged role and the `review_requested` state — anything else "
        "fails with `409 invalid_status_transition`."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_REVIEW_TRANSITION,
    },
)
async def update_ai_work(
    work_id: UUID, work_in: AIWorkLogUpdate, session: DbSession, principal: CurrentPrincipal
) -> AIWorkLog:
    work = await session.get(AIWorkLogModel, work_id)
    if work is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ai_work entry not found")
    work = await ai_work_service.update_ai_work(session, principal, work, work_in)
    return AIWorkLog.model_validate(work)
