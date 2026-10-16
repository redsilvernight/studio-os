"""Read-only roadmap admission dry-run (Mission Control P05, additive).

A dry-run answers which linked Tasks of one roadmap could be launched now, on
which of the caller's machines, and why every other Task is excluded. It is a
pure read: no `TaskLaunch` is created, nothing is reserved, no state changes.
The rules live in `admission_rules.compose_dry_run`; this module only projects
the persisted state into the `AdmissionSnapshot` it consumes, in a fixed number
of grouped queries (never one query per Task).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.admission import (
    AdmissionBatchRefused,
    AdmissionBatchRequest,
    AdmissionBatchResult,
    AdmissionDryRun,
    AdmissionRefusal,
    AdmissionRefusalReason,
)
from studio_contracts.ai_work import AIWorkStatus
from studio_contracts.decisions import DecisionStatus
from studio_contracts.roadmaps import RoadmapStatus, TaskStatusValue, waiting_on
from studio_contracts.task_launch import TaskLaunch, TaskLaunchCreate, TaskLaunchStatus

from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.roadmap import RoadmapModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.services import claims as claims_service
from studio_api.services import eligibility as eligibility_service
from studio_api.services import events as events_service
from studio_api.services import launch_grants as grants_service
from studio_api.services import roadmap_support
from studio_api.services import task_launches as launches_service
from studio_api.services.admission_rules import (
    AdmissionSnapshot,
    StepFacts,
    TaskFacts,
    compose_dry_run,
)
from studio_api.services.authz import Principal, ensure_can_write
from studio_api.settings import Settings

_ACTIVE_LAUNCH_STATUSES = frozenset(
    {
        TaskLaunchStatus.REQUESTED.value,
        TaskLaunchStatus.ACCEPTED.value,
        TaskLaunchStatus.PREPARING.value,
        TaskLaunchStatus.RUNNING.value,
    }
)


async def _tasks_by_id(
    session: AsyncSession, task_ids: set[uuid.UUID]
) -> dict[uuid.UUID, TaskModel]:
    if not task_ids:
        return {}
    rows = (
        (await session.execute(select(TaskModel).where(TaskModel.id.in_(task_ids)))).scalars().all()
    )
    return {row.id: row for row in rows}


async def _launch_active_task_ids(
    session: AsyncSession, task_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    if not task_ids:
        return set()
    rows = (
        (
            await session.execute(
                select(TaskLaunchModel.task_id).where(
                    TaskLaunchModel.task_id.in_(task_ids),
                    TaskLaunchModel.status.in_(_ACTIVE_LAUNCH_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def _review_pending_task_ids(
    session: AsyncSession, task_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    if not task_ids:
        return set()
    ai_work = (
        (
            await session.execute(
                select(AIWorkLogModel.task_id).where(
                    AIWorkLogModel.task_id.in_(task_ids),
                    AIWorkLogModel.status == AIWorkStatus.REVIEW_REQUESTED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    decisions = (
        (
            await session.execute(
                select(DecisionModel.task_id).where(
                    DecisionModel.task_id.in_(task_ids),
                    DecisionModel.status == DecisionStatus.PROPOSED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    return {task_id for task_id in (*ai_work, *decisions) if task_id is not None}


async def _live_claim_machines_by_task(
    session: AsyncSession, project_id: uuid.UUID, task_ids: set[uuid.UUID]
) -> dict[uuid.UUID, frozenset[uuid.UUID]]:
    """Live claims (expired ones excluded by the claims service itself), grouped
    by the Task they are attached to: a claim with no `task_id` is irrelevant."""
    if not task_ids:
        return {}
    machines: dict[uuid.UUID, set[uuid.UUID]] = {}
    for claim in await claims_service.active_claims(session, project_id):
        if claim.task_id in task_ids:
            machines.setdefault(claim.task_id, set()).add(claim.claimed_by_machine_id)
    return {task_id: frozenset(values) for task_id, values in machines.items()}


def _task_facts(
    task_id: uuid.UUID,
    task: TaskModel | None,
    *,
    launch_active: set[uuid.UUID],
    review_pending: set[uuid.UUID],
    claims_by_task: dict[uuid.UUID, frozenset[uuid.UUID]],
) -> TaskFacts:
    """A linked Task absent from the database is a data gap, never a crash: its
    status stays `None` so `compose_dry_run` can exclude it explicitly."""
    return TaskFacts(
        task_id=task_id,
        title=task.title if task is not None else None,
        status=TaskStatusValue(task.status) if task is not None else None,
        claimed_by_machine_id=task.claimed_by_machine_id if task is not None else None,
        launch_active=task_id in launch_active,
        review_pending=task_id in review_pending,
        live_claim_machine_ids=claims_by_task.get(task_id, frozenset()),
    )


async def dry_run(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    harness_id: str | None,
    settings: Settings,
) -> AdmissionDryRun:
    """Read-only admission plan of one roadmap (404 unknown, 403 inaccessible
    project via `ensure_roadmap_access`). Never writes and never commits."""
    roadmap = await roadmap_support.ensure_roadmap_access(session, principal, roadmap_id)
    tree = await roadmap_support.load_tree(session, roadmap)
    states = tree.states()

    linked_task_ids = {link.task_id for step in tree.steps for link in tree.links.get(step.id, [])}
    tasks = await _tasks_by_id(session, linked_task_ids)
    launch_active = await _launch_active_task_ids(session, linked_task_ids)
    review_pending = await _review_pending_task_ids(session, linked_task_ids)
    claims_by_task = await _live_claim_machines_by_task(
        session, roadmap.project_id, linked_task_ids
    )

    steps = tuple(
        StepFacts(
            key=step.key,
            state=states[step.key],
            waiting_on=tuple(waiting_on(tree.depends_on_keys(step), states)),
            tasks=tuple(
                _task_facts(
                    link.task_id,
                    tasks.get(link.task_id),
                    launch_active=launch_active,
                    review_pending=review_pending,
                    claims_by_task=claims_by_task,
                )
                for link in tree.links.get(step.id, [])
            ),
        )
        for step in tree.steps
    )
    machines = await eligibility_service.eligible_machines(
        session,
        principal,
        project_id=roadmap.project_id,
        harness_id=harness_id,
        settings=settings,
    )
    snapshot = AdmissionSnapshot(
        roadmap_id=roadmap.id,
        project_id=roadmap.project_id,
        roadmap_status=RoadmapStatus(roadmap.status),
        roadmap_version=roadmap.version,
        harness_id=harness_id,
        steps=steps,
        machines=tuple(machines),
    )
    return compose_dry_run(snapshot, evaluated_at=datetime.now(UTC))


async def _lock_xact(session: AsyncSession, key: str) -> None:
    """Postgres advisory lock scoped to the current transaction: held until this
    session's commit/rollback, so a concurrent batch or creation for the same
    key blocks here instead of racing (same model as
    `transfers._lock_quota_bucket`)."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})


async def authorize_admit(
    session: AsyncSession, principal: Principal, roadmap_id: uuid.UUID
) -> RoadmapModel:
    """Project then role check of a batch admission, run ahead of the
    idempotency replay short-circuit (DEC-0036, DEC-0103 §12): the roadmap's
    project level (`write`) then the writer role (`task_launch`). Who may launch
    on each target machine is checked per item (`launch_grants`)."""
    roadmap = await roadmap_support.ensure_roadmap_access(session, principal, roadmap_id, "write")
    ensure_can_write(principal, "task_launch")
    return roadmap


def _refused(
    error_code: Literal["admission_plan_changed", "admission_refused"],
    *,
    plan: AdmissionDryRun | None = None,
    refusals: list[AdmissionRefusal] | None = None,
) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail=AdmissionBatchRefused(
            error_code=error_code, plan=plan, refusals=refusals or []
        ).model_dump(mode="json"),
    )


def _refusal(
    task_id: uuid.UUID,
    machine_id: uuid.UUID,
    reason: AdmissionRefusalReason,
    *,
    exclusion_reasons: list[Any] | None = None,
    budget: dict[str, Any] | None = None,
) -> AdmissionRefusal:
    return AdmissionRefusal(
        task_id=task_id,
        machine_id=machine_id,
        reason=reason,
        exclusion_reasons=exclusion_reasons or [],
        budget=budget,
    )


async def admit_batch(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    body: AdmissionBatchRequest,
    settings: Settings,
) -> AdmissionBatchResult:
    """Admit a whole batch or nothing (Mission Control P05). Under a roadmap
    then sorted-task advisory lock, the dry-run is recomputed with the same
    `harness_id`; a moved `plan_digest` is `409 admission_plan_changed` with the
    fresh plan. Otherwise every item is checked (`duplicate_item`,
    `not_launchable` + `exclusion_reasons`, `machine_not_eligible`, the caller's
    launch right on the machine, then the budget). Any refusal rolls the whole
    transaction back and answers `409 admission_refused` with every refusal.
    Only a fully admitted batch commits once, then publishes every event."""
    roadmap = await authorize_admit(session, principal, roadmap_id)
    await _lock_xact(session, f"admission:{roadmap_id}")
    for task_id in sorted({item.task_id for item in body.items}, key=str):
        await _lock_xact(session, f"task-launch:{task_id}")

    plan = await dry_run(session, principal, roadmap_id, str(body.harness_id), settings)
    if plan.plan_digest != body.plan_digest:
        raise _refused("admission_plan_changed", plan=plan)

    candidates = {candidate.task_id: candidate for candidate in plan.launchable}
    exclusions = {exclusion.task_id: exclusion for exclusion in plan.excluded}
    refusals: list[AdmissionRefusal] = []
    staged: list[tuple[TaskLaunchModel, EventModel]] = []
    seen: set[uuid.UUID] = set()
    for item in body.items:
        if item.task_id in seen:
            refusals.append(
                _refusal(item.task_id, item.machine_id, AdmissionRefusalReason.DUPLICATE_ITEM)
            )
            continue
        seen.add(item.task_id)
        candidate = candidates.get(item.task_id)
        if candidate is None:
            exclusion = exclusions.get(item.task_id)
            refusals.append(
                _refusal(
                    item.task_id,
                    item.machine_id,
                    AdmissionRefusalReason.NOT_LAUNCHABLE,
                    exclusion_reasons=None if exclusion is None else list(exclusion.reasons),
                )
            )
            continue
        if item.machine_id not in candidate.machine_ids:
            refusals.append(
                _refusal(item.task_id, item.machine_id, AdmissionRefusalReason.MACHINE_NOT_ELIGIBLE)
            )
            continue
        machine = await session.get(MachineModel, item.machine_id)
        if machine is None:
            refusals.append(
                _refusal(item.task_id, item.machine_id, AdmissionRefusalReason.MACHINE_NOT_ELIGIBLE)
            )
            continue
        try:
            await grants_service.ensure_can_launch(session, principal, machine, roadmap.project_id)
        except HTTPException:
            refusals.append(
                _refusal(item.task_id, item.machine_id, AdmissionRefusalReason.MACHINE_NOT_ELIGIBLE)
            )
            continue
        launch_in = TaskLaunchCreate(
            task_id=item.task_id,
            machine_id=item.machine_id,
            harness_id=body.harness_id,
            agent_stable_key=body.agent_stable_key,
            profile_key=body.profile_key,
            expires_in_seconds=body.expires_in_seconds,
        )
        try:
            launch, event = await launches_service.stage_launch(
                session, principal, roadmap.project_id, launch_in
            )
        except HTTPException as exc:
            if (
                exc.status_code == status.HTTP_409_CONFLICT
                and isinstance(exc.detail, dict)
                and exc.detail.get("error_code") == "budget_refused"
            ):
                refusals.append(
                    _refusal(
                        item.task_id,
                        item.machine_id,
                        AdmissionRefusalReason.BUDGET_REFUSED,
                        budget=exc.detail,
                    )
                )
                continue
            raise
        staged.append((launch, event))

    if refusals:
        await session.rollback()
        raise _refused("admission_refused", refusals=refusals)

    await session.commit()
    for launch, event in staged:
        await session.refresh(launch)
        await session.refresh(event)
        events_service.publish_event(event)
    return AdmissionBatchResult(
        roadmap_id=roadmap.id,
        plan_digest=plan.plan_digest,
        launches=[TaskLaunch.model_validate(launch) for launch, _ in staged],
        admitted_at=datetime.now(UTC),
    )
