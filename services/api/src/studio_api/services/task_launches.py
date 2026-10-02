from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import MachineCapabilities, MachineStatus, Role
from studio_contracts.events import EventCreate, EventType
from studio_contracts.task_launch import (
    ALLOWED_TRANSITIONS,
    LAUNCH_POLL_MAX,
    TERMINAL_STATUSES,
    TaskLaunch,
    TaskLaunchActor,
    TaskLaunchCancel,
    TaskLaunchCreate,
    TaskLaunchMachineReport,
    TaskLaunchPull,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import events as events_service
from studio_api.services import heartbeats as heartbeats_service
from studio_api.services import launch_grants as grants_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_project_access,
    project_visibility_clause,
)
from studio_api.settings import Settings

_STATUS_EVENT_TYPES: dict[TaskLaunchStatus, EventType] = {
    TaskLaunchStatus.REQUESTED: EventType.TASK_LAUNCH_REQUESTED,
    TaskLaunchStatus.ACCEPTED: EventType.TASK_LAUNCH_ACCEPTED,
    TaskLaunchStatus.REJECTED: EventType.TASK_LAUNCH_REJECTED,
    TaskLaunchStatus.CANCELLED: EventType.TASK_LAUNCH_CANCELLED,
    TaskLaunchStatus.EXPIRED: EventType.TASK_LAUNCH_EXPIRED,
    TaskLaunchStatus.SUCCEEDED: EventType.TASK_LAUNCH_FINISHED,
    TaskLaunchStatus.FAILED: EventType.TASK_LAUNCH_FINISHED,
}


def _launch_event_payload(launch: TaskLaunchModel, previous_status: str) -> dict[str, Any]:
    return {
        "launch_id": str(launch.id),
        "machine_id": str(launch.machine_id),
        "harness_id": launch.harness_id,
        "status": launch.status,
        "previous_status": previous_status,
        "reason_code": launch.reason_code,
    }


async def _commit_with_event(
    session: AsyncSession,
    principal: Principal,
    launch: TaskLaunchModel,
    event_type: EventType,
    previous_status: str,
    actor: tuple[Literal["user", "agent", "system"], uuid.UUID] | None = None,
) -> TaskLaunchModel:
    actor_type, actor_id = actor or await tasks_service.event_actor(session, principal, None)
    event = await events_service.stage_event(
        session,
        EventCreate(
            event_id=uuid.uuid4(),
            event_type=event_type,
            project_id=launch.project_id,
            task_id=launch.task_id,
            machine_id=principal.machine.id,
            actor_type=actor_type,
            actor_id=actor_id,
            client_timestamp=datetime.now(UTC),
            payload=_launch_event_payload(launch, previous_status),
        ),
    )
    await session.commit()
    await session.refresh(launch)
    await session.refresh(event)
    events_service.publish_event(event)
    return launch


async def authorize_create(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    task: TaskModel,
    machine: MachineModel,
    launch_in: TaskLaunchCreate,
    settings: Settings,
    now: datetime,
) -> None:
    """Project then role check of a launch creation, run ahead of the
    idempotency replay short-circuit (DEC-0036). Task/project/machine
    coherence and the target machine's launch aptitude are 409s, never
    oracles: the project gate answers the single 403 first. Who may
    request (owner, admin or grantee) is AIB-J (`launch_grants`)."""
    ensure_project_access(principal, project_id, "write")
    ensure_can_write(principal, "task_launch")
    if task.project_id != project_id or launch_in.task_id != task.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "task_project_mismatch"},
        )
    if launch_in.machine_id != machine.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "launch_machine_mismatch"},
        )
    await grants_service.ensure_can_launch(session, principal, machine, project_id)
    capabilities: MachineCapabilities | None = None
    if machine.capabilities is not None:
        capabilities = heartbeats_service.parse_stored_capabilities(machine.capabilities)
    reported_at = machine.capabilities_reported_at
    if capabilities is None or reported_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "machine_capabilities_missing"},
        )
    if now - reported_at > timedelta(seconds=settings.heartbeat_offline_after_seconds):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "machine_capabilities_stale"},
        )
    if heartbeats_service.derive_status(machine, settings) != MachineStatus.ONLINE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "machine_offline"},
        )
    if not capabilities.accepts_launches:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "machine_not_opted_in"},
        )
    if project_id not in (capabilities.project_ids or []):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "project_not_registered"},
        )


async def get_target_machine(session: AsyncSession, machine_id: uuid.UUID) -> MachineModel | None:
    return await session.get(MachineModel, machine_id)


async def create_launch(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    launch_in: TaskLaunchCreate,
) -> TaskLaunchModel:
    now = datetime.now(UTC)
    launch = TaskLaunchModel(
        project_id=project_id,
        task_id=launch_in.task_id,
        machine_id=launch_in.machine_id,
        requested_by_user_id=principal.user.id,
        harness_id=str(launch_in.harness_id),
        agent_stable_key=launch_in.agent_stable_key,
        status=TaskLaunchStatus.REQUESTED.value,
        reason_code=TaskLaunchReasonCode.NONE.value,
        expires_at=now + timedelta(seconds=launch_in.expires_in_seconds),
    )
    session.add(launch)
    await session.flush()
    return await _commit_with_event(
        session,
        principal,
        launch,
        EventType.TASK_LAUNCH_REQUESTED,
        previous_status="",
    )


async def get_launch(
    session: AsyncSession, principal: Principal, launch_id: uuid.UUID
) -> TaskLaunchModel | None:
    launch = await session.get(TaskLaunchModel, launch_id)
    if launch is not None:
        await expire_launch_if_overdue(session, principal, launch)
        ensure_project_access(principal, launch.project_id)
    return launch


async def list_launches(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[TaskLaunchModel]:
    ensure_project_access(principal, project_id)
    stmt = (
        select(TaskLaunchModel)
        .where(TaskLaunchModel.project_id == project_id)
        .order_by(TaskLaunchModel.created_at.asc(), TaskLaunchModel.id)
        .limit(limit)
        .offset(offset)
    )
    if (visible := project_visibility_clause(principal, TaskLaunchModel.project_id)) is not None:
        stmt = stmt.where(visible)
    result = await session.execute(stmt)
    launches = list(result.scalars().all())
    for launch in launches:
        await expire_launch_if_overdue(session, principal, launch)
    return launches


async def expire_launch_if_overdue(
    session: AsyncSession, principal: Principal, launch: TaskLaunchModel
) -> TaskLaunchModel:
    """Server-side expiry (DEC-0173): a non-terminal launch past `expires_at`
    becomes `expired` with the server as actor. `expired_unpulled` when it
    never left `requested`, `expired_timeout` otherwise."""
    if launch.status in {s.value for s in TERMINAL_STATUSES}:
        return launch
    if datetime.now(UTC) < launch.expires_at:
        return launch
    previous_status = launch.status
    launch.status = TaskLaunchStatus.EXPIRED.value
    launch.reason_code = (
        TaskLaunchReasonCode.EXPIRED_UNPULLED.value
        if previous_status == TaskLaunchStatus.REQUESTED.value
        else TaskLaunchReasonCode.EXPIRED_TIMEOUT.value
    )
    launch.finished_at = datetime.now(UTC)
    launch.version += 1
    return await _commit_with_event(
        session,
        principal,
        launch,
        EventType.TASK_LAUNCH_EXPIRED,
        previous_status=previous_status,
        actor=("system", principal.machine.id),
    )


async def expire_overdue_launches(session: AsyncSession, principal: Principal) -> int:
    """Sweep every overdue non-terminal launch. Returns the expired count."""
    stmt = select(TaskLaunchModel).where(
        TaskLaunchModel.expires_at <= datetime.now(UTC),
        TaskLaunchModel.status.notin_([s.value for s in TERMINAL_STATUSES]),
    )
    result = await session.execute(stmt)
    count = 0
    for launch in result.scalars().all():
        ensure_project_access(principal, launch.project_id)
        await expire_launch_if_overdue(session, principal, launch)
        count += 1
    return count


async def pull_pending(
    session: AsyncSession, principal: Principal, machine_id: uuid.UUID
) -> TaskLaunchPull:
    """The target machine pulls its non-terminal launches, oldest first,
    bounded. Only that machine may pull — a pull changes nothing, so it
    emits no event (lazy server expiry aside)."""
    if machine_id != principal.machine.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"error_code": "forbidden", "resource": "task_launch", "action": "pull"},
        )
    machine = await session.get(MachineModel, machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "machine not found")
    stmt = (
        select(TaskLaunchModel)
        .where(
            TaskLaunchModel.machine_id == machine_id,
            TaskLaunchModel.status.notin_([s.value for s in TERMINAL_STATUSES]),
        )
        .order_by(TaskLaunchModel.created_at.asc(), TaskLaunchModel.id)
        .limit(LAUNCH_POLL_MAX + 1)
    )
    result = await session.execute(stmt)
    launches = list(result.scalars().all())
    for launch in launches:
        await expire_launch_if_overdue(session, principal, launch)
    live = [
        launch for launch in launches if launch.status not in {s.value for s in TERMINAL_STATUSES}
    ]
    items = [TaskLaunch.model_validate(launch) for launch in live[:LAUNCH_POLL_MAX]]
    return TaskLaunchPull(items=items)


def authorize_report(principal: Principal, launch: TaskLaunchModel) -> None:
    """Only the launch's target machine reports execution."""
    ensure_can_write(principal, "task_launch")
    if launch.machine_id != principal.machine.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"error_code": "forbidden", "resource": "task_launch", "action": "report"},
        )


async def _report_actor(
    session: AsyncSession, principal: Principal, launch: TaskLaunchModel
) -> tuple[Literal["user", "agent", "system"], uuid.UUID]:
    """Machine reports are attributed to the launch's agent when the target
    machine registered it under `agent_stable_key` (TECH/03: `agent` for
    machine reports), else to the machine's owner — never across machines."""
    if launch.agent_stable_key:
        result = await session.execute(
            select(AgentModel).where(
                AgentModel.machine_id == launch.machine_id,
                AgentModel.stable_key == launch.agent_stable_key,
            )
        )
        agent = result.scalar_one_or_none()
        if agent is not None:
            return ("agent", agent.id)
    return await tasks_service.event_actor(session, principal, None)


async def report_launch(
    session: AsyncSession,
    principal: Principal,
    launch: TaskLaunchModel,
    report: TaskLaunchMachineReport,
) -> TaskLaunchModel:
    authorize_report(principal, launch)
    ensure_project_access(principal, launch.project_id)
    await expire_launch_if_overdue(session, principal, launch)
    if launch.version != report.expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "version_conflict", "server_version": launch.version},
        )
    current = TaskLaunchStatus(launch.status)
    target = report.status
    allowed = ALLOWED_TRANSITIONS.get((current, target))
    if allowed is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "invalid_launch_transition"},
        )
    if allowed != TaskLaunchActor.MACHINE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"error_code": "forbidden", "resource": "task_launch", "action": "report"},
        )
    if report.session_id is not None:
        linked = await session.get(WorkSessionModel, report.session_id)
        if linked is None or linked.machine_id != launch.machine_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"error_code": "invalid_launch_session"},
            )
    previous_status = launch.status
    launch.status = target.value
    launch.reason_code = report.reason_code.value
    launch.session_id = report.session_id
    launch.output_excerpt = report.output_excerpt
    if target in TERMINAL_STATUSES:
        launch.finished_at = datetime.now(UTC)
    launch.version += 1
    event_type = _STATUS_EVENT_TYPES.get(target)
    if event_type is None:
        await session.commit()
        await session.refresh(launch)
        return launch
    actor = await _report_actor(session, principal, launch)
    return await _commit_with_event(session, principal, launch, event_type, previous_status, actor)


async def cancel_launch(
    session: AsyncSession,
    principal: Principal,
    launch: TaskLaunchModel,
    cancel: TaskLaunchCancel,
) -> TaskLaunchModel:
    """Only the requester (or an admin) cancels, on a non-terminal launch."""
    ensure_can_write(principal, "task_launch")
    ensure_project_access(principal, launch.project_id, "write")
    if principal.role != Role.ADMIN and launch.requested_by_user_id != principal.user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"error_code": "forbidden", "resource": "task_launch", "action": "cancel"},
        )
    await expire_launch_if_overdue(session, principal, launch)
    if launch.version != cancel.expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "version_conflict", "server_version": launch.version},
        )
    current = TaskLaunchStatus(launch.status)
    actor = ALLOWED_TRANSITIONS.get((current, TaskLaunchStatus.CANCELLED))
    if actor is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "invalid_launch_transition"},
        )
    if actor != TaskLaunchActor.REQUESTER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"error_code": "forbidden", "resource": "task_launch", "action": "cancel"},
        )
    previous_status = launch.status
    launch.status = TaskLaunchStatus.CANCELLED.value
    launch.reason_code = TaskLaunchReasonCode.CANCELLED_BY_REQUESTER.value
    launch.finished_at = datetime.now(UTC)
    launch.version += 1
    return await _commit_with_event(
        session, principal, launch, EventType.TASK_LAUNCH_CANCELLED, previous_status
    )
