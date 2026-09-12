from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.ai_work import AIWorkLog, AIWorkLogCreate, AIWorkLogUpdate

from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.deps import CurrentMachine, DbSession
from studio_api.services import ai_work as ai_work_service
from studio_api.services import idempotency as idempotency_service

router = APIRouter(prefix="/api/v1/ai-work", tags=["ai-work"])


@router.get("", response_model=list[AIWorkLog])
async def list_ai_work(
    session: DbSession,
    machine: CurrentMachine,
    project_id: UUID | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
) -> list[AIWorkLog]:
    entries = await ai_work_service.list_ai_work(session, project_id=project_id, task_id=task_id)
    return [AIWorkLog.model_validate(e) for e in entries]


@router.post("", response_model=AIWorkLog, status_code=status.HTTP_201_CREATED)
async def create_ai_work(
    work_in: AIWorkLogCreate,
    request: Request,
    session: DbSession,
    machine: CurrentMachine,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AIWorkLog:
    async def _create() -> AIWorkLog:
        return AIWorkLog.model_validate(await ai_work_service.create_ai_work(session, work_in))

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /ai-work",
        AIWorkLog,
        _create,
        status.HTTP_201_CREATED,
    )


@router.patch("/{work_id}", response_model=AIWorkLog)
async def update_ai_work(
    work_id: UUID, work_in: AIWorkLogUpdate, session: DbSession, machine: CurrentMachine
) -> AIWorkLog:
    work = await session.get(AIWorkLogModel, work_id)
    if work is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ai_work entry not found")
    work = await ai_work_service.update_ai_work(session, work, work_in)
    return AIWorkLog.model_validate(work)
