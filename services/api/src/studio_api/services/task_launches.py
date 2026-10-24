from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import MachineCapabilities, MachineStatus, Role
from studio_contracts.events import EventCreate, EventType
from studio_contracts.library import LibraryKind
from studio_contracts.profiles import (
    REFERENCE_PROFILES,
    LaunchProfilePin,
    pin_profile,
    profile_elements,
    reference_work_profile,
)
from studio_contracts.task_launch import (
    ALLOWED_TRANSITIONS,
    LAUNCH_POLL_MAX,
    TERMINAL_STATUSES,
    TaskLaunch,
    TaskLaunchActor,
    TaskLaunchCancel,
    TaskLaunchCreate,
    TaskLaunchMachineReport,
    TaskLaunchProtocol,
    TaskLaunchProtocolStatus,
    TaskLaunchPull,
    TaskLaunchReasonCode,
    TaskLaunchRecovery,
    TaskLaunchRecoveryReason,
    TaskLaunchRecoveryState,
    TaskLaunchRetry,
    TaskLaunchStatus,
    TaskLaunchView,
)
from studio_contracts.task_launch_replay import TaskLaunchReplayBasis
from studio_contracts.tasks import TaskStatus

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import budgets as budgets_service
from studio_api.services import events as events_service
from studio_api.services import heartbeats as heartbeats_service
from studio_api.services import launch_grants as grants_service
from studio_api.services import resolution as resolution_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_project_access,
    project_visibility_clause,
)
from studio_api.settings import Settings, get_settings

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


async def _stage_launch_event(
    session: AsyncSession,
    principal: Principal,
    launch: TaskLaunchModel,
    event_type: EventType,
    previous_status: str,
    actor: tuple[Literal["user", "agent", "system"], uuid.UUID] | None = None,
) -> EventModel:
    """Stage the launch's event in the caller's transaction (flush only, no
    commit), so a unit of work and its audit trail become durable atomically."""
    actor_type, actor_id = actor or await tasks_service.event_actor(session, principal, None)
    return await events_service.stage_event(
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


async def _commit_with_event(
    session: AsyncSession,
    principal: Principal,
    launch: TaskLaunchModel,
    event_type: EventType,
    previous_status: str,
    actor: tuple[Literal["user", "agent", "system"], uuid.UUID] | None = None,
    *,
    event: EventModel | None = None,
) -> TaskLaunchModel:
    """Commit the launch together with its event and publish it. `event` lets a
    caller that already staged the event (`stage_launch`) reuse it instead of
    staging a second one; otherwise it is staged here. Stays the single commit
    seam of a launch write, so a crash injected before it leaves neither launch
    nor reservation behind."""
    if event is None:
        event = await _stage_launch_event(
            session, principal, launch, event_type, previous_status, actor
        )
    await session.commit()
    await session.refresh(launch)
    await session.refresh(event)
    events_service.publish_event(event)
    return launch


def authorize_profile_request(launch_in: TaskLaunchCreate) -> None:
    """Shape gate of the optional work profile (DEC-0198): a `profile_key`
    profiles one specific agent, so it needs that agent, and only a reference
    profile key names a profile the server knows how to materialize. Both
    refusals describe the caller's own payload, never a resource, so neither
    is an oracle. `None` means "no profile asked for"."""
    if launch_in.profile_key is None:
        return
    if launch_in.agent_stable_key is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error_code": "profile_requires_agent"},
        )
    if launch_in.profile_key not in REFERENCE_PROFILES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error_code": "unknown_profile", "profile_key": launch_in.profile_key},
        )


def authorize_production_request(principal: Principal, launch_in: TaskLaunchCreate) -> None:
    if launch_in.allow_production and not principal.human_authenticated:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"error_code": "production_approval_requires_user_session"},
        )


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
    authorize_profile_request(launch_in)
    authorize_production_request(principal, launch_in)
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
    if capabilities.launch_safety is not True:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "launch_safety_unsupported_by_machine"},
        )
    if launch_in.profile_key is not None and capabilities.launch_profiles is not True:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "profile_unsupported_by_machine"},
        )


async def resolve_profile_pin(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    launch_in: TaskLaunchCreate,
) -> LaunchProfilePin | None:
    """The work-profile pin of a profiled launch (DEC-0198), `None` for an
    unprofiled one. The profiled agent goes through the server's own P5
    resolver — same visibility, versioning and runtime precedence as a
    preview — and the pin carries the reference profile plus the element
    versions it composes, so the machine recomputes the same digest or
    refuses the run with `profile_version_changed` instead of executing a
    profile nobody saw."""
    if launch_in.profile_key is None or launch_in.agent_stable_key is None:
        return None
    profile = reference_work_profile(launch_in.profile_key, launch_in.agent_stable_key)
    definition = await resolution_service.resolve_full(
        session,
        principal,
        LibraryKind.AGENT_DEFINITION,
        launch_in.agent_stable_key,
        project_id,
    )
    return pin_profile(profile, profile_elements(definition))


async def get_target_machine(session: AsyncSession, machine_id: uuid.UUID) -> MachineModel | None:
    return await session.get(MachineModel, machine_id)


async def stage_launch(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    launch_in: TaskLaunchCreate,
    *,
    attempt: int = 1,
    retry_of_launch_id: uuid.UUID | None = None,
    replay_basis: dict[str, Any] | None = None,
) -> tuple[TaskLaunchModel, EventModel]:
    """Budget admission, launch row, reservation and `task_launch.requested`
    event staged in the caller's transaction — no commit. The task's advisory
    xact lock (held until commit/rollback) serializes concurrent admissions of
    the same task, so a batch and a direct creation never both pass the budget
    or the duplicate check at once; the machine's `machine-slots` lock, taken
    after it, makes a batch counting that machine's unreported launches wait
    for this one. Returns the launch and its staged event;
    the caller commits, refreshes both and publishes the event.

    The attempt is created with the work-profile pin of its profile
    (DEC-0198): a retry inherits `profile_key` and recomputes the pin, so a
    Library version bump between two attempts shows up as a different digest
    instead of silently running the first attempt's profile."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"task-launch:{launch_in.task_id}"},
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"machine-slots:{launch_in.machine_id}"},
    )
    now = datetime.now(UTC)
    admission = await budgets_service.decide_admission(session, project_id, now)
    authorize_production_request(principal, launch_in)
    pin = await resolve_profile_pin(session, principal, project_id, launch_in)
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
        attempt=attempt,
        retry_of_launch_id=retry_of_launch_id,
        replay_basis=replay_basis,
        allow_production=launch_in.allow_production,
        profile_key=launch_in.profile_key,
        profile_contract_version=None if pin is None else pin.contract_version,
        profile_digest=None if pin is None else pin.digest,
    )
    session.add(launch)
    await session.flush()
    if admission is not None:
        await budgets_service.record_reservation(session, project_id, launch.id, admission)
    event = await _stage_launch_event(
        session, principal, launch, EventType.TASK_LAUNCH_REQUESTED, previous_status=""
    )
    return launch, event


async def create_launch(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    launch_in: TaskLaunchCreate,
    *,
    attempt: int = 1,
    retry_of_launch_id: uuid.UUID | None = None,
    replay_basis: dict[str, Any] | None = None,
) -> TaskLaunchModel:
    launch, event = await stage_launch(
        session,
        principal,
        project_id,
        launch_in,
        attempt=attempt,
        retry_of_launch_id=retry_of_launch_id,
        replay_basis=replay_basis,
    )
    return await _commit_with_event(
        session,
        principal,
        launch,
        EventType.TASK_LAUNCH_REQUESTED,
        previous_status="",
        event=event,
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


_TERMINAL_LAUNCH_STATUSES = frozenset(status.value for status in TERMINAL_STATUSES)

_NEVER_RAN_LAUNCH_STATUSES = frozenset(
    {
        TaskLaunchStatus.REJECTED.value,
        TaskLaunchStatus.CANCELLED.value,
        TaskLaunchStatus.EXPIRED.value,
    }
)

_DECIDED_LAUNCH_STATUSES = frozenset(
    {
        TaskLaunchStatus.ACCEPTED.value,
        TaskLaunchStatus.PREPARING.value,
        TaskLaunchStatus.RUNNING.value,
    }
)


_STOPPED_EVENT_TYPES = (
    EventType.TASK_LAUNCH_CANCELLED.value,
    EventType.TASK_LAUNCH_EXPIRED.value,
)


def _derive_protocol(
    launch: TaskLaunchModel,
    work_session: WorkSessionModel | None,
    task: TaskModel | None,
    stopped_while_running: bool = False,
) -> TaskLaunchProtocol:
    """The protocol proof of one launch, read-time only: a closed linked
    session is the handoff whatever the launch became afterwards, a live
    launch awaits its session, a launch stopped before it ran has no proof
    to give, and an exit code alone proves nothing. A launch cancelled or
    expired while `running` did run its harness, so it is unverified, not
    not-applicable. `task_status` is read, never written: a handoff never
    completes the task."""
    if work_session is not None and work_session.ended_at is not None:
        return TaskLaunchProtocol(
            status=TaskLaunchProtocolStatus.HANDED_OFF,
            session_id=work_session.id,
            task_status=TaskStatus(task.status) if task is not None else None,
        )
    if launch.status not in _TERMINAL_LAUNCH_STATUSES:
        return TaskLaunchProtocol(
            status=TaskLaunchProtocolStatus.AWAITING, session_id=launch.session_id
        )
    if (
        launch.status in _NEVER_RAN_LAUNCH_STATUSES
        and work_session is None
        and not stopped_while_running
    ):
        return TaskLaunchProtocol(status=TaskLaunchProtocolStatus.NOT_APPLICABLE)
    return TaskLaunchProtocol(
        status=TaskLaunchProtocolStatus.UNVERIFIED, session_id=launch.session_id
    )


def derive_recovery(
    launch: TaskLaunchModel, machine: MachineModel | None, settings: Settings
) -> TaskLaunchRecovery:
    """Recovery verdict of one attempt (P02), read-time only: the launch's
    status against its target machine's derived presence. Only an `offline`
    machine counts as unreachable — `idle` is a late heartbeat, not a loss.
    Writes nothing: recovering is always an explicit retry."""
    machine_status = (
        MachineStatus.OFFLINE
        if machine is None
        else heartbeats_service.derive_status(machine, settings)
    )
    last_seen = machine.last_seen_at if machine is not None else None
    offline = machine_status is MachineStatus.OFFLINE
    status = launch.status
    if status == TaskLaunchStatus.FAILED.value:
        return TaskLaunchRecovery(
            state=TaskLaunchRecoveryState.FAILED,
            reason=TaskLaunchRecoveryReason.LAUNCH_FAILED,
            machine_status=machine_status,
        )
    if status == TaskLaunchStatus.EXPIRED.value:
        return TaskLaunchRecovery(
            state=TaskLaunchRecoveryState.STALE,
            reason=TaskLaunchRecoveryReason.LAUNCH_EXPIRED,
            machine_status=machine_status,
            stale_since=launch.expires_at,
        )
    if offline and status in _DECIDED_LAUNCH_STATUSES:
        state = TaskLaunchRecoveryState.OFFLINE_WIP
    elif offline and status == TaskLaunchStatus.REQUESTED.value:
        state = TaskLaunchRecoveryState.STALE
    else:
        return TaskLaunchRecovery(state=TaskLaunchRecoveryState.OK, machine_status=machine_status)
    return TaskLaunchRecovery(
        state=state,
        reason=TaskLaunchRecoveryReason.MACHINE_OFFLINE,
        machine_status=machine_status,
        stale_since=last_seen,
    )


async def _linked_sessions(
    session: AsyncSession, launches: Sequence[TaskLaunchModel]
) -> dict[uuid.UUID, WorkSessionModel]:
    session_ids = {launch.session_id for launch in launches if launch.session_id is not None}
    if not session_ids:
        return {}
    result = await session.execute(
        select(WorkSessionModel).where(WorkSessionModel.id.in_(session_ids))
    )
    return {row.id: row for row in result.scalars()}


async def _launch_tasks(
    session: AsyncSession, launches: Sequence[TaskLaunchModel]
) -> dict[uuid.UUID, TaskModel]:
    task_ids = {launch.task_id for launch in launches}
    if not task_ids:
        return {}
    result = await session.execute(select(TaskModel).where(TaskModel.id.in_(task_ids)))
    return {row.id: row for row in result.scalars()}


async def _stopped_while_running(
    session: AsyncSession, launches: Sequence[TaskLaunchModel]
) -> set[str]:
    launch_ids = [
        str(launch.id)
        for launch in launches
        if launch.status in _NEVER_RAN_LAUNCH_STATUSES and launch.session_id is None
    ]
    if not launch_ids:
        return set()
    launch_id = EventModel.payload["launch_id"].astext
    result = await session.execute(
        select(launch_id).where(
            EventModel.event_type.in_(_STOPPED_EVENT_TYPES),
            launch_id.in_(launch_ids),
            EventModel.payload["previous_status"].astext == TaskLaunchStatus.RUNNING.value,
        )
    )
    return set(result.scalars())


async def _launch_machines(
    session: AsyncSession, launches: Sequence[TaskLaunchModel]
) -> dict[uuid.UUID, MachineModel]:
    machine_ids = {launch.machine_id for launch in launches}
    if not machine_ids:
        return {}
    result = await session.execute(select(MachineModel).where(MachineModel.id.in_(machine_ids)))
    return {row.id: row for row in result.scalars()}


async def protocol_views(
    session: AsyncSession, launches: Sequence[TaskLaunchModel]
) -> list[TaskLaunchView]:
    """Read model of a launch list: `TaskLaunchView` adds to each launch the
    protocol proof derived from its linked work session and the recovery
    verdict derived from its target machine. Sessions, tasks, machines and
    stop events are loaded in four grouped queries, never one per launch.
    Writes nothing and moves no task."""
    work_sessions = await _linked_sessions(session, launches)
    tasks = await _launch_tasks(session, launches)
    machines = await _launch_machines(session, launches)
    stopped_while_running = await _stopped_while_running(session, launches)
    settings = get_settings()
    return [
        TaskLaunchView(
            **TaskLaunch.model_validate(launch).model_dump(),
            protocol=_derive_protocol(
                launch,
                work_sessions.get(launch.session_id) if launch.session_id else None,
                tasks.get(launch.task_id),
                str(launch.id) in stopped_while_running,
            ),
            recovery=derive_recovery(launch, machines.get(launch.machine_id), settings),
            attempt=launch.attempt,
            retry_of_launch_id=launch.retry_of_launch_id,
            replay_basis=(
                None
                if launch.replay_basis is None
                else TaskLaunchReplayBasis.model_validate(launch.replay_basis)
            ),
        )
        for launch in launches
    ]


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
    emits no event (lazy server expiry aside). A profiled launch is withheld
    from a machine whose latest report no longer advertises
    `launch_profiles`: an earlier daemon would reject the whole page."""
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
    capabilities = (
        None
        if machine.capabilities is None
        else heartbeats_service.parse_stored_capabilities(machine.capabilities)
    )
    profiles_supported = capabilities is not None and capabilities.launch_profiles is True
    safety_supported = capabilities is not None and capabilities.launch_safety is True
    live = [
        launch
        for launch in launches
        if launch.status not in {s.value for s in TERMINAL_STATUSES}
        and safety_supported
        and (profiles_supported or launch.profile_key is None)
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


_LINKABLE_STATUSES = (
    TaskLaunchStatus.ACCEPTED.value,
    TaskLaunchStatus.PREPARING.value,
    TaskLaunchStatus.RUNNING.value,
)


async def link_session_to_launch(
    session: AsyncSession,
    work_session: WorkSessionModel,
    launch_id: uuid.UUID | None = None,
) -> None:
    """Attach a session to the attempt it serves. With `launch_id` (the
    caller's launch credential, DEC-0182) the link is exact and idempotent:
    one session per attempt, whichever way the daemon reconnects — a session
    already bound to that attempt is left alone, and an attempt already
    bound to another session is never stolen. Without it the older
    task/machine heuristic still applies: the newest unlinked live launch.
    Metadata only: `version` is untouched so the target machine's next
    report keeps its `expected_version`."""
    if work_session.task_id is None or work_session.machine_id is None:
        return
    if launch_id is not None:
        launch = await session.get(TaskLaunchModel, launch_id)
        if launch is None or launch.session_id == work_session.id:
            return
        if (
            launch.session_id is not None
            or launch.machine_id != work_session.machine_id
            or launch.task_id != work_session.task_id
            or launch.status not in _LINKABLE_STATUSES
        ):
            return
        launch.session_id = work_session.id
        await session.commit()
        return
    result = await session.execute(
        select(TaskLaunchModel)
        .where(
            TaskLaunchModel.task_id == work_session.task_id,
            TaskLaunchModel.machine_id == work_session.machine_id,
            TaskLaunchModel.session_id.is_(None),
            TaskLaunchModel.status.in_(_LINKABLE_STATUSES),
        )
        .order_by(TaskLaunchModel.created_at.desc())
        .limit(1)
    )
    launch = result.scalar_one_or_none()
    if launch is None:
        return
    launch.session_id = work_session.id
    await session.commit()


async def report_launch(
    session: AsyncSession,
    principal: Principal,
    launch: TaskLaunchModel,
    report: TaskLaunchMachineReport,
) -> TaskLaunchModel:
    authorize_report(principal, launch)
    ensure_project_access(principal, launch.project_id)
    await session.refresh(launch, with_for_update=True)
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
        if (
            linked is None
            or linked.machine_id != launch.machine_id
            or linked.task_id != launch.task_id
            or linked.ended_at is not None
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"error_code": "invalid_launch_session"},
            )
    previous_status = launch.status
    launch.status = target.value
    launch.reason_code = report.reason_code.value
    if report.session_id is not None:
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
    await session.refresh(launch, with_for_update=True)
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


async def existing_retry(session: AsyncSession, launch: TaskLaunchModel) -> TaskLaunchModel | None:
    """The attempt this launch already spawned, if any (at most one, unique
    index `uq_task_launches_retry_of`)."""
    result = await session.execute(
        select(TaskLaunchModel).where(TaskLaunchModel.retry_of_launch_id == launch.id).limit(1)
    )
    return result.scalar_one_or_none()


async def retry_launch(
    session: AsyncSession,
    principal: Principal,
    launch: TaskLaunchModel,
    retry: TaskLaunchRetry,
    settings: Settings,
) -> TaskLaunchModel:
    """Explicit recovery (P02): a terminal attempt retried as a *new*
    attempt that points at the one it replaces, so the trace of what failed
    stays readable — the previous attempt is never rewritten. A live attempt
    is `409 launch_not_terminal`: it is the target machine's to finish, and
    an `offline_wip` attempt is cancelled first, never doubled.

    The work profile is inherited, not copied: `profile_key` travels to the
    new attempt and its pin is recomputed from the Library as it stands now
    (DEC-0198).

    One retry per attempt: the attempt row is locked while deciding and a
    second retry (replayed, concurrent or with another key) resolves to the
    attempt the first one created. Same requester rule as cancel; the target
    machine's aptitude is re-checked exactly like a creation."""
    ensure_can_write(principal, "task_launch")
    ensure_project_access(principal, launch.project_id, "write")
    if principal.role != Role.ADMIN and launch.requested_by_user_id != principal.user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"error_code": "forbidden", "resource": "task_launch", "action": "retry"},
        )
    await session.refresh(launch, with_for_update=True)
    await expire_launch_if_overdue(session, principal, launch)
    # An expiry commits, which releases the row lock: take it again so the
    # existing-retry check and the creation stay serialized.
    await session.refresh(launch, with_for_update=True)
    existing = await existing_retry(session, launch)
    if existing is not None:
        # A replay never converges on an attempt it did not create: only the
        # same accepted preview returns the existing attempt (DEC-0214).
        if retry.replay is not None and (
            existing.replay_basis is None
            or existing.replay_basis.get("preview_digest") != retry.replay.preview_digest
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"error_code": "replay_refused", "codes": ["already_retried"]},
            )
        return existing
    if launch.status not in _TERMINAL_LAUNCH_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "launch_not_terminal", "status": launch.status},
        )
    machine = await session.get(MachineModel, launch.machine_id)
    task = await session.get(TaskModel, launch.task_id)
    if machine is None or task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "launch target not found")
    launch_in = TaskLaunchCreate(
        task_id=launch.task_id,
        machine_id=launch.machine_id,
        harness_id=launch.harness_id,
        agent_stable_key=launch.agent_stable_key,
        profile_key=launch.profile_key,
        expires_in_seconds=retry.expires_in_seconds,
    )
    await authorize_create(
        session, principal, launch.project_id, task, machine, launch_in, settings, datetime.now(UTC)
    )
    replay_basis = None
    if retry.replay is not None:
        from studio_api.services.task_launch_replay import confirm_replay

        replay_basis = await confirm_replay(session, principal, launch, retry.replay, settings)
    return await create_launch(
        session,
        principal,
        launch.project_id,
        launch_in,
        attempt=launch.attempt + 1,
        retry_of_launch_id=launch.id,
        replay_basis=replay_basis,
    )
