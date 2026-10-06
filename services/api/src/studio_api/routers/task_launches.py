from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.common import Page
from studio_contracts.task_launch import (
    TaskLaunch,
    TaskLaunchCancel,
    TaskLaunchCreate,
    TaskLaunchCredential,
    TaskLaunchMachineReport,
    TaskLaunchPull,
)

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
    RESP_409_LAUNCH_TRANSITION,
    RESP_409_VERSION_CONFLICT,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import launch_credentials as credentials_service
from studio_api.services import task_launches as launches_service
from studio_api.services import tasks as tasks_service
from studio_api.settings import get_settings

router = APIRouter(tags=["task-launches"])


@router.post(
    "/api/v1/projects/{project_id}/task-launches",
    response_model=TaskLaunch,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Request a typed task launch on a target machine (AIB R2). Data "
        "only, never a command: ids and stable keys. Requires a writer "
        "role; the target machine's owner (or an admin) may request. "
        "Accepts `Idempotency-Key`: the same key with the identical body "
        "returns the original launch instead of a duplicate."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_409_IDEMPOTENCY,
        **RESP_409_LAUNCH_TRANSITION,
    },
)
async def create_task_launch(
    project_id: UUID,
    launch_in: TaskLaunchCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> TaskLaunch:
    task = await tasks_service.get_task(session, launch_in.task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    machine = await launches_service.get_target_machine(session, launch_in.machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "machine not found")
    await launches_service.authorize_create(
        session, principal, project_id, task, machine, launch_in, get_settings(), datetime.now(UTC)
    )

    async def _create() -> TaskLaunch:
        return TaskLaunch.model_validate(
            await launches_service.create_launch(session, principal, project_id, launch_in)
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /projects/{project_id}/task-launches",
        TaskLaunch,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "/api/v1/task-launches/{launch_id}",
    response_model=TaskLaunch,
    description="Get one task launch by id.",
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def get_task_launch(
    launch_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> TaskLaunch:
    launch = await launches_service.get_launch(session, principal, launch_id)
    if launch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task launch not found")
    return TaskLaunch.model_validate(launch)


@router.get(
    "/api/v1/projects/{project_id}/task-launches",
    response_model=Page[TaskLaunch],
    description="List task launches of a project, oldest first.",
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_task_launches(
    project_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
) -> Page[TaskLaunch]:
    launches = await launches_service.list_launches(
        session, principal, project_id, limit=limit, offset=offset
    )
    return Page[TaskLaunch](
        items=[TaskLaunch.model_validate(launch) for launch in launches],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/api/v1/task-launches/{launch_id}/cancel",
    response_model=TaskLaunch,
    description=(
        "Cancel a task launch. Only the requester (or an admin) may "
        "cancel, on a non-terminal launch. Requires the current version; "
        "a stale version is rejected with the live server version."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_VERSION_CONFLICT,
        **RESP_409_LAUNCH_TRANSITION,
    },
)
async def cancel_task_launch(
    launch_id: UUID,
    cancel: TaskLaunchCancel,
    session: DbSession,
    principal: CurrentPrincipal,
) -> TaskLaunch:
    launch = await launches_service.get_launch(session, principal, launch_id)
    if launch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task launch not found")
    launch = await launches_service.cancel_launch(session, principal, launch, cancel)
    return TaskLaunch.model_validate(launch)


@router.get(
    "/api/v1/machines/{machine_id}/task-launches/pending",
    response_model=TaskLaunchPull,
    description=(
        "The target machine pulls its non-terminal launches, oldest "
        "first, at most 20. Only that machine may pull. A pull changes "
        "nothing and emits no event."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def pull_pending_launches(
    machine_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> TaskLaunchPull:
    return await launches_service.pull_pending(session, principal, machine_id)


@router.post(
    "/api/v1/task-launches/{launch_id}/report",
    response_model=TaskLaunch,
    description=(
        "The target machine reports execution (`accepted` -> `preparing` "
        "-> `running` -> terminal, or `rejected`/`failed`). Only the "
        "launch's target machine may report. Requires the current "
        "version; a stale version is rejected with the live server version."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_VERSION_CONFLICT,
        **RESP_409_LAUNCH_TRANSITION,
    },
)
async def report_task_launch(
    launch_id: UUID,
    report: TaskLaunchMachineReport,
    session: DbSession,
    principal: CurrentPrincipal,
) -> TaskLaunch:
    launch = await launches_service.get_launch(session, principal, launch_id)
    if launch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task launch not found")
    launch = await launches_service.report_launch(session, principal, launch, report)
    return TaskLaunch.model_validate(launch)


@router.post(
    "/api/v1/task-launches/{launch_id}/credential",
    response_model=TaskLaunchCredential,
    status_code=status.HTTP_201_CREATED,
    description=(
        "The target machine obtains the ephemeral credential of the harness "
        "this launch starts (AIB P9). Only the launch's target machine, "
        "authenticated with its durable credential, on an accepted, "
        "preparing or running launch. The token is returned once, bound to "
        "the launch's project and task, void when the launch is terminal or "
        "expires, and opens only the launch allowlist of routes and tools. "
        "A new request revokes the previous credential of the launch."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_LAUNCH_TRANSITION,
    },
)
async def issue_task_launch_credential(
    launch_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> TaskLaunchCredential:
    launch = await launches_service.get_launch(session, principal, launch_id)
    if launch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task launch not found")
    return await credentials_service.issue_credential(session, principal, launch)
