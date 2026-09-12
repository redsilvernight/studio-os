from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.tasks import Task, TaskCreate, TaskUpdate

from studio_api.deps import CurrentMachine, DbSession
from studio_api.services import idempotency as idempotency_service
from studio_api.services import tasks as tasks_service

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
async def list_tasks(
    session: DbSession,
    machine: CurrentMachine,
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
) -> list[Task]:
    tasks = await tasks_service.list_tasks(
        session, project_id=project_id, limit=limit, offset=offset
    )
    return [Task.model_validate(t) for t in tasks]


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    request: Request,
    session: DbSession,
    machine: CurrentMachine,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Task:
    async def _create() -> Task:
        return Task.model_validate(await tasks_service.create_task(session, task_in))

    return await idempotency_service.run_idempotent(
        session, request, idempotency_key, "POST /tasks", Task, _create, status.HTTP_201_CREATED
    )


@router.get("/{task_id}", response_model=Task)
async def get_task(task_id: UUID, session: DbSession, machine: CurrentMachine) -> Task:
    task = await tasks_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return Task.model_validate(task)


@router.patch("/{task_id}", response_model=Task)
async def update_task(
    task_id: UUID,
    task_in: TaskUpdate,
    session: DbSession,
    machine: CurrentMachine,
    if_match_version: int = Header(alias="If-Match-Version"),
) -> Task:
    task = await tasks_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    task = await tasks_service.update_task(session, task, task_in, if_match_version)
    return Task.model_validate(task)


@router.post("/{task_id}/claim", response_model=Task)
async def claim_task(task_id: UUID, session: DbSession, machine: CurrentMachine) -> Task:
    task = await tasks_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    task = await tasks_service.claim_task(session, task, machine.id, agent_id=None)
    return Task.model_validate(task)


@router.post("/{task_id}/release", response_model=Task)
async def release_task(task_id: UUID, session: DbSession, machine: CurrentMachine) -> Task:
    task = await tasks_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    task = await tasks_service.release_task(session, task)
    return Task.model_validate(task)
