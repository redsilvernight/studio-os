from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.tasks import Task, TaskCreate, TaskUpdate

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    IF_MATCH_VERSION_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_ALREADY_CLAIMED,
    RESP_409_IDEMPOTENCY,
    RESP_409_VERSION_CONFLICT,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import tasks as tasks_service

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get(
    "",
    response_model=list[Task],
    description=(
        "List tasks of the caller's accessible projects, optionally filtered "
        "by project. A `project_id` the caller cannot access (or that does "
        "not exist) answers `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_tasks(
    session: DbSession,
    principal: CurrentPrincipal,
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
) -> list[Task]:
    tasks = await tasks_service.list_tasks(
        session, principal, project_id=project_id, limit=limit, offset=offset
    )
    return [Task.model_validate(t) for t in tasks]


@router.post(
    "",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create a task. Requires a writer role. Accepts `Idempotency-Key` "
        "for safe retries: the same key with the identical body returns "
        "the original task instead of a duplicate."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_IDEMPOTENCY},
)
async def create_task(
    task_in: TaskCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> Task:
    tasks_service.authorize_create(principal, task_in.project_id)

    async def _create() -> Task:
        return Task.model_validate(await tasks_service.create_task(session, principal, task_in))

    return await idempotency_service.run_idempotent(
        session, request, idempotency_key, "POST /tasks", Task, _create, status.HTTP_201_CREATED
    )


@router.get(
    "/{task_id}",
    response_model=Task,
    description=(
        "Get one task by id. A task of a project the caller cannot access "
        "answers `403 forbidden` (resource `project`)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_task(task_id: UUID, session: DbSession, principal: CurrentPrincipal) -> Task:
    task = await tasks_service.read_task(session, principal, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return Task.model_validate(task)


@router.patch(
    "/{task_id}",
    response_model=Task,
    description=(
        "Update a task's title, description or status. Requires a writer "
        "role and the current `If-Match-Version`; a stale version is "
        "rejected with the live server version instead of overwriting."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_VERSION_CONFLICT,
    },
)
async def update_task(
    task_id: UUID,
    task_in: TaskUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
    if_match_version: int = Header(
        alias="If-Match-Version", description=IF_MATCH_VERSION_DESCRIPTION
    ),
) -> Task:
    task = await tasks_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    task = await tasks_service.update_task(session, principal, task, task_in, if_match_version)
    return Task.model_validate(task)


@router.post(
    "/{task_id}/claim",
    response_model=Task,
    description=(
        "Claim a task for the caller's machine (sets status to "
        "in_progress). Requires a writer role. Fails with "
        "`already_claimed` if another machine holds it."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_ALREADY_CLAIMED,
    },
)
async def claim_task(task_id: UUID, session: DbSession, principal: CurrentPrincipal) -> Task:
    task = await tasks_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    task = await tasks_service.claim_task(
        session, principal, task, principal.machine.id, agent_id=None
    )
    return Task.model_validate(task)


@router.post(
    "/{task_id}/release",
    response_model=Task,
    description=(
        "Release a task's claim. Only the machine holding the claim (or a "
        "privileged role) may release it; anyone else receives `403 "
        "forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def release_task(task_id: UUID, session: DbSession, principal: CurrentPrincipal) -> Task:
    task = await tasks_service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    task = await tasks_service.release_task(session, principal, task)
    return Task.model_validate(task)
