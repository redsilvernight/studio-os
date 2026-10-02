from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.ai_integration import (
    AiIntegrationStatus,
    AppliedBootstrap,
    DesiredIntegration,
    ReportedMachineIntegration,
    ReportFreshness,
)
from studio_contracts.auth import Role
from studio_contracts.bootstrap import BootstrapFileSummary
from studio_contracts.bootstrap_plan import BootstrapPlanRequest

from studio_api.db.models.machine import MachineModel
from studio_api.services import bootstrap_plan as bootstrap_plan_service
from studio_api.services import heartbeats as heartbeats_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import Principal, ensure_project_access
from studio_api.settings import Settings

_UNKNOWN_ERROR = "plan_unavailable"


def _in_sync(summary: BootstrapFileSummary) -> bool:
    drifted = summary.absent + summary.obsolete + summary.modified + summary.incompatible
    return drifted == 0 and summary.up_to_date > 0


def reported_view(
    machine: MachineModel, *, project_id: uuid.UUID, settings: Settings, now: datetime
) -> ReportedMachineIntegration:
    status = heartbeats_service.derive_status(machine, settings)
    capabilities = heartbeats_service.parse_stored_capabilities(machine.capabilities)
    reported_at = machine.capabilities_reported_at
    if capabilities is None or reported_at is None:
        return ReportedMachineIntegration(
            machine_id=machine.id,
            display_name=machine.display_name,
            status=status,
            freshness=ReportFreshness.NEVER_REPORTED,
        )
    stale = now - reported_at > timedelta(seconds=settings.heartbeat_offline_after_seconds)
    applied = next((b for b in capabilities.bootstrap or [] if b.project_id == project_id), None)
    return ReportedMachineIntegration(
        machine_id=machine.id,
        display_name=machine.display_name,
        status=status,
        freshness=ReportFreshness.STALE if stale else ReportFreshness.FRESH,
        bootstrap=(
            None
            if applied is None
            else AppliedBootstrap(
                checked_at=applied.checked_at,
                summary=applied.summary,
                in_sync=_in_sync(applied.summary),
            )
        ),
        reported_at=reported_at,
        project_registered=project_id in capabilities.project_ids,
        harnesses=capabilities.harnesses,
    )


async def _desired(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> tuple[DesiredIntegration | None, str | None]:
    try:
        plan = await bootstrap_plan_service.build_bootstrap_plan(
            session, principal, BootstrapPlanRequest(project_id=project_id)
        )
    except HTTPException as exc:
        detail = exc.detail
        code = detail.get("error_code") if isinstance(detail, dict) else None
        return None, code if isinstance(code, str) else _UNKNOWN_ERROR
    counts = Counter(artifact.kind.value for artifact in plan.artifacts)
    return (
        DesiredIntegration(
            plan_hash=plan.plan_hash,
            agent_keys=plan.agent_keys,
            artifact_counts=dict(sorted(counts.items())),
        ),
        None,
    )


async def ai_integration_status(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, settings: Settings
) -> AiIntegrationStatus:
    ensure_project_access(principal, project_id)
    desired, desired_error = await _desired(session, principal, project_id)
    owner = None if principal.role == Role.ADMIN else principal.user.id
    machines = await provisioning_service.list_active_machines(session, owner)
    now = datetime.now(UTC)
    views = [
        reported_view(machine, project_id=project_id, settings=settings, now=now)
        for machine in machines
    ]
    views.sort(key=lambda v: (v.display_name, str(v.machine_id)))
    return AiIntegrationStatus(
        project_id=project_id, desired=desired, desired_error=desired_error, machines=views
    )
