from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import (
    HarnessReport,
    IneligibilityReason,
    MachineCapabilities,
    MachineEligibility,
    MachineStatus,
    Role,
)
from studio_contracts.task_launch import TaskLaunchStatus

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.user import UserModel
from studio_api.services import heartbeats as heartbeats_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import (
    ALL_PROJECTS,
    Principal,
    has_project_access,
    load_project_scope,
)
from studio_api.settings import Settings


def evaluate(
    machine: MachineModel,
    *,
    project_id: uuid.UUID,
    owner_has_access: bool,
    harness_id: str | None,
    settings: Settings,
    now: datetime,
    unreported_launches: int = 0,
) -> MachineEligibility:
    status = heartbeats_service.derive_status(machine, settings)
    reasons: list[IneligibilityReason] = []
    capabilities: MachineCapabilities | None = None
    if machine.capabilities is not None:
        capabilities = heartbeats_service.parse_stored_capabilities(machine.capabilities)
    reported_at = machine.capabilities_reported_at

    if status != MachineStatus.ONLINE:
        reasons.append(IneligibilityReason.OFFLINE)
    if capabilities is None or reported_at is None:
        reasons.append(IneligibilityReason.NO_CAPABILITIES_REPORT)
    elif now - reported_at > timedelta(seconds=settings.heartbeat_offline_after_seconds):
        reasons.append(IneligibilityReason.CAPABILITIES_STALE)
    if not owner_has_access:
        reasons.append(IneligibilityReason.OWNER_NO_PROJECT_ACCESS)

    free_slots = 0
    harnesses: list[HarnessReport] = []
    if capabilities is not None:
        harnesses = capabilities.harnesses
        free_slots = max(
            capabilities.max_launches - capabilities.running_launches - unreported_launches, 0
        )
        if project_id not in capabilities.project_ids:
            reasons.append(IneligibilityReason.PROJECT_NOT_REGISTERED)
        if not capabilities.accepts_launches:
            reasons.append(IneligibilityReason.LAUNCHES_NOT_ACCEPTED)
        if capabilities.launch_safety is not True:
            reasons.append(IneligibilityReason.LAUNCH_SAFETY_UNSUPPORTED)
        usable = [h for h in harnesses if h.detected and h.configured]
        if harness_id is not None and all(h.harness_id != harness_id for h in usable):
            reasons.append(IneligibilityReason.HARNESS_INCOMPATIBLE)
        elif harness_id is None and not usable:
            reasons.append(IneligibilityReason.HARNESS_INCOMPATIBLE)
        if free_slots == 0:
            reasons.append(IneligibilityReason.AT_CAPACITY)

    return MachineEligibility(
        machine_id=machine.id,
        display_name=machine.display_name,
        status=status,
        eligible=not reasons,
        reasons=reasons,
        harnesses=harnesses,
        free_slots=free_slots,
        reported_at=reported_at,
    )


_STARTED_LAUNCH_STATUSES = (
    TaskLaunchStatus.ACCEPTED.value,
    TaskLaunchStatus.PREPARING.value,
    TaskLaunchStatus.RUNNING.value,
)


async def unreported_launch_counts(
    session: AsyncSession, machine_ids: list[uuid.UUID], now: datetime
) -> dict[uuid.UUID, int]:
    """Active launches each machine's last heartbeat cannot have counted in
    `running_launches`: every unexpired `requested` launch (not yet picked up
    by the daemon) and every started launch created after that report. One
    grouped query."""
    if not machine_ids:
        return {}
    rows = await session.execute(
        select(TaskLaunchModel.machine_id, func.count())
        .join(MachineModel, MachineModel.id == TaskLaunchModel.machine_id)
        .where(
            TaskLaunchModel.machine_id.in_(machine_ids),
            or_(
                and_(
                    TaskLaunchModel.status == TaskLaunchStatus.REQUESTED.value,
                    TaskLaunchModel.expires_at > now,
                ),
                and_(
                    TaskLaunchModel.status.in_(_STARTED_LAUNCH_STATUSES),
                    or_(
                        MachineModel.capabilities_reported_at.is_(None),
                        TaskLaunchModel.created_at > MachineModel.capabilities_reported_at,
                    ),
                ),
            ),
        )
        .group_by(TaskLaunchModel.machine_id)
    )
    return {machine_id: int(count) for machine_id, count in rows.all()}


async def _owner_has_access(
    session: AsyncSession, principal: Principal, owner_id: uuid.UUID, project_id: uuid.UUID
) -> bool:
    if owner_id == principal.user.id:
        return has_project_access(principal, project_id)
    owner = await session.get(UserModel, owner_id)
    if owner is None:
        return False
    scope = await load_project_scope(session, owner_id, Role(owner.role))
    return scope is ALL_PROJECTS or project_id in scope


async def eligible_machines(
    session: AsyncSession,
    principal: Principal,
    *,
    project_id: uuid.UUID,
    harness_id: str | None,
    settings: Settings,
) -> list[MachineEligibility]:
    """The caller's own machines (every machine for `admin`, as in
    `GET /machines`), each evaluated against one task's project. Eligible
    machines first, then by name and id — a stable order."""
    owner = None if principal.role == Role.ADMIN else principal.user.id
    machines = await provisioning_service.list_active_machines(session, owner)
    now = datetime.now(UTC)
    unreported = await unreported_launch_counts(session, [m.id for m in machines], now)
    access: dict[uuid.UUID, bool] = {}
    results: list[MachineEligibility] = []
    for machine in machines:
        owner_id = machine.owner_user_id
        if owner_id not in access:
            access[owner_id] = await _owner_has_access(session, principal, owner_id, project_id)
        results.append(
            evaluate(
                machine,
                project_id=project_id,
                owner_has_access=access[owner_id],
                harness_id=harness_id,
                settings=settings,
                now=now,
                unreported_launches=unreported.get(machine.id, 0),
            )
        )
    results.sort(key=lambda r: (not r.eligible, r.display_name, str(r.machine_id)))
    return results
