"""Roadmap hydration (Roadmaps P2, DEC-0084 §4, DEC-0085 §3): materialize the
`tasks` plan of steps as real Tasks, idempotently.

`preview` and `apply` share one planning function, so what the preview shows
is exactly what `apply` does. Per plan item: `create` when no Task is linked
under its `hydration_key`, `reuse` the Task already linked under it, `skip`
when the step is `done` or `skipped`. Hydration never modifies or deletes an
existing Task, never links a pre-existing Task (that is the explicit `LinkTask`
operation) and never makes a Task depend on the Roadmap.

`apply` does not move the roadmap or step versions: it is a deterministic
materialization of the plan, replay-safe by `hydration_key`, so a retry under
a fresh `Idempotency-Key` with the same `expected_version` finds its links
(`reuse`) instead of failing; the plan-changing writes are what move the
version and invalidate a preview.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.events import EventType
from studio_contracts.roadmaps import (
    HydrationAction,
    HydrationApplyRequest,
    HydrationCounts,
    HydrationItem,
    HydrationReason,
    HydrationRequest,
    HydrationResult,
    RoadmapStatus,
    StepState,
    TaskPlanItem,
    WriteKind,
    count_hydration,
)
from studio_contracts.tasks import TaskCreate

from studio_api.db.models.roadmap import RoadmapModel, RoadmapStepModel, RoadmapStepTaskLinkModel
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal
from studio_api.services.roadmap_support import (
    PendingEvent,
    RoadmapTree,
    check_version,
    finish_result,
    guard_write,
    invalid_state,
    load_tree,
    lock_roadmap,
    not_found,
    reference_not_found,
    resolve_provenance,
)


@dataclass
class _PlannedItem:
    step: RoadmapStepModel
    plan: TaskPlanItem
    item: HydrationItem


def _plan(tree: RoadmapTree, step_keys: list[str] | None) -> list[_PlannedItem]:
    if step_keys is not None:
        unknown = [key for key in step_keys if tree.step_by_key(key) is None]
        if unknown:
            raise reference_not_found(f"step {unknown[0]}")
    wanted = None if step_keys is None else set(step_keys)
    states = tree.states()
    planned: list[_PlannedItem] = []
    for step in tree.steps:
        if wanted is not None and step.key not in wanted:
            continue
        linked = {
            link.hydration_key: link.task_id
            for link in tree.links.get(step.id, [])
            if link.hydration_key is not None
        }
        for raw in step.task_plan:
            plan = TaskPlanItem.model_validate(raw)
            existing = linked.get(plan.hydration_key)
            action = HydrationAction.CREATE
            reason: HydrationReason | None = None
            if states[step.key] is StepState.DONE:
                action, reason = HydrationAction.SKIP, HydrationReason.STEP_DONE
            elif states[step.key] is StepState.SKIPPED:
                action, reason = HydrationAction.SKIP, HydrationReason.STEP_SKIPPED
            elif existing is not None:
                action = HydrationAction.REUSE
            planned.append(
                _PlannedItem(
                    step,
                    plan,
                    HydrationItem(
                        step_key=step.key,
                        hydration_key=plan.hydration_key,
                        action=action,
                        title=plan.title,
                        task_id=existing,
                        reason=reason,
                    ),
                )
            )
    return planned


def _result(
    roadmap: RoadmapModel, planned: list[_PlannedItem], *, applied: bool
) -> HydrationResult:
    items = [entry.item for entry in planned]
    active = roadmap.status == RoadmapStatus.ACTIVE.value
    return HydrationResult(
        roadmap_id=roadmap.id,
        roadmap_version=roadmap.version,
        applied=applied,
        applicable=active,
        not_applicable_reason=None if active else HydrationReason.ROADMAP_NOT_ACTIVE,
        items=items,
        counts=count_hydration(items) if items else HydrationCounts(),
    )


async def preview_hydration(
    session: AsyncSession, roadmap_id: uuid.UUID, payload: HydrationRequest
) -> HydrationResult:
    """Read-only: any non-archived status; a non-`active` roadmap answers
    `applicable=False`. Writes nothing."""
    roadmap = await session.get(RoadmapModel, roadmap_id)
    if roadmap is None:
        raise not_found()
    if roadmap.status == RoadmapStatus.ARCHIVED.value:
        raise invalid_state(RoadmapStatus.ARCHIVED, "an archived roadmap cannot be hydrated")
    tree = await load_tree(session, roadmap)
    return _result(roadmap, _plan(tree, payload.step_keys), applied=False)


async def apply_hydration(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    payload: HydrationApplyRequest,
) -> HydrationResult:
    roadmap = await lock_roadmap(session, roadmap_id)
    guard_write(principal, roadmap, WriteKind.HYDRATION_APPLY, payload.provenance)
    prov = await resolve_provenance(session, principal, payload.provenance)
    check_version(roadmap.version, payload.expected_version)
    tree = await load_tree(session, roadmap)
    planned = _plan(tree, payload.step_keys)

    for entry in planned:
        if entry.item.action is not HydrationAction.CREATE:
            continue
        task = await tasks_service.add_task(
            session,
            principal,
            TaskCreate(
                project_id=roadmap.project_id,
                title=entry.plan.title,
                description=entry.plan.description,
            ),
        )
        session.add(
            RoadmapStepTaskLinkModel(
                step_id=entry.step.id,
                task_id=task.id,
                hydration_key=entry.plan.hydration_key,
                **prov.columns(),
            )
        )
        entry.item = entry.item.model_copy(update={"task_id": task.id})
    await session.flush()

    result = _result(roadmap, planned, applied=True)
    pending: list[PendingEvent] = []
    if result.counts.create:
        pending.append(
            PendingEvent(
                EventType.ROADMAP_HYDRATED,
                {
                    "roadmap_id": str(roadmap.id),
                    "revision_no": roadmap.revision_no,
                    "status": roadmap.status,
                    "counts": result.counts.model_dump(),
                },
            )
        )
    await finish_result(session, principal, roadmap, prov, pending)
    return result
