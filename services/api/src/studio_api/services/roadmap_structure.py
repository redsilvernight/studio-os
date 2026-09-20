"""Structure and progress operations of the Roadmap domain (Roadmaps P2):
phases, steps, atomic reordering, dependencies (DAG), Step <-> Task links and
bounded progress updates.

Every operation serializes on its roadmap row (`lock_roadmap`), checks the
write matrix and the optimistic version, applies the change and returns the
resulting `Roadmap` (which carries the new roadmap and step versions). Plan
content never reaches a Task; a Task is only ever *read* (its status) or
*joined* (a link) here.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.roadmaps import (
    MAX_DEPENDENCIES_PER_STEP,
    MAX_LINKS_PER_STEP,
    MAX_PHASES,
    MAX_STEPS,
    MAX_STEPS_PER_PHASE,
    MAX_TASK_PLAN,
    DependencyChange,
    LinkTask,
    PhaseCreate,
    PhaseUpdate,
    Reorder,
    Roadmap,
    RoadmapErrorCode,
    RoadmapStatus,
    RoadmapValidationReason,
    StepCreate,
    StepProgressUpdate,
    StepUpdate,
    TaskPlanItem,
    WriteKind,
    WriteProvenance,
    find_dependency_cycle,
)

from studio_api.db.models.roadmap import (
    RoadmapModel,
    RoadmapPhaseModel,
    RoadmapStepDependencyModel,
    RoadmapStepModel,
    RoadmapStepTaskLinkModel,
)
from studio_api.db.models.task import TaskModel
from studio_api.services.authz import Principal
from studio_api.services.roadmap_support import (
    ResolvedProvenance,
    RoadmapTree,
    check_version,
    content_changed,
    finish,
    guard_write,
    invalid_roadmap,
    invalid_state,
    limit_exceeded,
    load_tree,
    lock_roadmap,
    reference_not_found,
    resolve_provenance,
    roadmap_error,
    updated_event,
)
from studio_api.services.roadmaps import text_or_none


async def _open(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    kind: WriteKind,
    declared: WriteProvenance,
    expected_roadmap_version: int | None = None,
) -> tuple[RoadmapModel, ResolvedProvenance, RoadmapTree]:
    roadmap = await lock_roadmap(session, roadmap_id)
    guard_write(principal, roadmap, kind, declared)
    prov = await resolve_provenance(session, principal, declared)
    if expected_roadmap_version is not None:
        check_version(roadmap.version, expected_roadmap_version)
    return roadmap, prov, await load_tree(session, roadmap)


def _phase(tree: RoadmapTree, key: str) -> RoadmapPhaseModel:
    phase = tree.phase_by_key(key)
    if phase is None:
        raise reference_not_found(f"phase {key}")
    return phase


def _step(tree: RoadmapTree, key: str) -> RoadmapStepModel:
    step = tree.step_by_key(key)
    if step is None:
        raise reference_not_found(f"step {key}")
    return step


def _duplicate_key(field_name: str) -> Exception:
    return roadmap_error(
        status.HTTP_409_CONFLICT, RoadmapErrorCode.DUPLICATE_KEY, field_name=field_name
    )


def _check_plan(tree: RoadmapTree, step_key: str, items: list[TaskPlanItem]) -> None:
    keys = [item.hydration_key for item in items]
    if len(set(keys)) != len(keys):
        raise invalid_roadmap(
            RoadmapValidationReason.DUPLICATE_HYDRATION_KEY.value, f"steps.{step_key}.tasks"
        )
    others = sum(len(step.task_plan) for step in tree.steps if step.key != step_key)
    if others + len(items) > MAX_TASK_PLAN:
        raise limit_exceeded("task_plan")


def _require_draft(roadmap: RoadmapModel) -> None:
    if roadmap.status != RoadmapStatus.DRAFT.value:
        raise invalid_state(
            RoadmapStatus(roadmap.status),
            "phases and steps can only be deleted from a draft roadmap; mark a step "
            "`skipped` instead",
        )


def _reposition(rows: Sequence[RoadmapPhaseModel | RoadmapStepModel]) -> None:
    for index, row in enumerate(rows):
        row.position = index


# --- phases ---
async def create_phase(
    session: AsyncSession, principal: Principal, roadmap_id: uuid.UUID, payload: PhaseCreate
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session,
        principal,
        roadmap_id,
        WriteKind.CONTENT,
        payload.provenance,
        payload.expected_roadmap_version,
    )
    if tree.phase_by_key(payload.key) is not None:
        raise _duplicate_key("key")
    if len(tree.phases) >= MAX_PHASES:
        raise limit_exceeded("phases")
    session.add(
        RoadmapPhaseModel(
            roadmap_id=roadmap.id,
            key=payload.key,
            position=len(tree.phases),
            title=payload.title,
            objective=text_or_none(payload.objective),
            **prov.columns(),
        )
    )
    await session.flush()
    event = await content_changed(session, roadmap, prov, "phase", payload.key)
    return await finish(session, principal, roadmap, prov, [event])


async def update_phase(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    key: str,
    payload: PhaseUpdate,
    expected_version: int,
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session, principal, roadmap_id, WriteKind.CONTENT, payload.provenance
    )
    phase = _phase(tree, key)
    check_version(phase.version, expected_version)
    if payload.title is not None:
        phase.title = payload.title
    if payload.objective is not None:
        phase.objective = text_or_none(payload.objective)
    phase.version += 1
    event = await content_changed(session, roadmap, prov, "phase", key)
    return await finish(session, principal, roadmap, prov, [event])


def _check_permutation(current: list[str], ordered: list[str], field_name: str) -> None:
    if len(set(ordered)) != len(ordered) or set(ordered) != set(current):
        raise invalid_roadmap(RoadmapValidationReason.INVALID_REORDER.value, field_name)


async def reorder_phases(
    session: AsyncSession, principal: Principal, roadmap_id: uuid.UUID, payload: Reorder
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session,
        principal,
        roadmap_id,
        WriteKind.CONTENT,
        payload.provenance,
        payload.expected_roadmap_version,
    )
    _check_permutation([phase.key for phase in tree.phases], payload.ordered_keys, "ordered_keys")
    by_key = {phase.key: phase for phase in tree.phases}
    _reposition([by_key[key] for key in payload.ordered_keys])
    await session.flush()
    event = await content_changed(session, roadmap, prov, "phase_order")
    return await finish(session, principal, roadmap, prov, [event])


async def delete_phase(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    key: str,
    expected_roadmap_version: int,
    declared: WriteProvenance,
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session, principal, roadmap_id, WriteKind.CONTENT, declared, expected_roadmap_version
    )
    _require_draft(roadmap)
    phase = _phase(tree, key)
    if any(tree.links.get(step.id) for step in tree.steps_of(phase.id)):
        raise roadmap_error(status.HTTP_409_CONFLICT, RoadmapErrorCode.STEP_HAS_LINKS)
    await session.delete(phase)
    await session.flush()
    _reposition([other for other in tree.phases if other.id != phase.id])
    event = await content_changed(session, roadmap, prov, "phase", key)
    return await finish(session, principal, roadmap, prov, [event])


# --- steps ---
async def create_step(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    phase_key: str,
    payload: StepCreate,
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session,
        principal,
        roadmap_id,
        WriteKind.CONTENT,
        payload.provenance,
        payload.expected_roadmap_version,
    )
    phase = _phase(tree, phase_key)
    content = payload.content
    if tree.step_by_key(content.key) is not None:
        raise _duplicate_key("content.key")
    if len(tree.steps) >= MAX_STEPS:
        raise limit_exceeded("steps")
    if len(tree.steps_of(phase.id)) >= MAX_STEPS_PER_PHASE:
        raise limit_exceeded("steps_per_phase")
    if len(set(content.depends_on)) != len(content.depends_on):
        raise invalid_roadmap(
            RoadmapValidationReason.DUPLICATE_DEPENDENCY.value,
            f"steps.{content.key}.depends_on",
        )
    if content.key in content.depends_on:
        raise invalid_roadmap(
            RoadmapValidationReason.SELF_DEPENDENCY.value, f"steps.{content.key}.depends_on"
        )
    targets = [_step(tree, dependency) for dependency in content.depends_on]
    _check_plan(tree, content.key, content.tasks)

    step = RoadmapStepModel(
        roadmap_id=roadmap.id,
        phase_id=phase.id,
        key=content.key,
        position=len(tree.steps_of(phase.id)),
        title=content.title,
        objective=text_or_none(content.objective),
        context=text_or_none(content.context),
        instructions=text_or_none(content.instructions),
        acceptance_criteria=list(content.acceptance_criteria),
        criteria_checked=[],
        notes=text_or_none(content.notes),
        step_metadata=dict(content.metadata),
        task_plan=[item.model_dump(mode="json") for item in content.tasks],
        **prov.columns(),
    )
    session.add(step)
    await session.flush()
    for target in targets:
        session.add(
            RoadmapStepDependencyModel(
                step_id=step.id, depends_on_step_id=target.id, roadmap_id=roadmap.id
            )
        )
    await session.flush()
    event = await content_changed(session, roadmap, prov, "step", content.key)
    return await finish(session, principal, roadmap, prov, [event])


async def update_step(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    key: str,
    payload: StepUpdate,
    expected_version: int,
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session, principal, roadmap_id, WriteKind.CONTENT, payload.provenance
    )
    step = _step(tree, key)
    check_version(step.version, expected_version)
    if payload.title is not None:
        step.title = payload.title
    if payload.objective is not None:
        step.objective = text_or_none(payload.objective)
    if payload.context is not None:
        step.context = text_or_none(payload.context)
    if payload.instructions is not None:
        step.instructions = text_or_none(payload.instructions)
    if payload.acceptance_criteria is not None:
        if list(payload.acceptance_criteria) != list(step.acceptance_criteria):
            step.criteria_checked = []
        step.acceptance_criteria = list(payload.acceptance_criteria)
    if payload.metadata is not None:
        step.step_metadata = dict(payload.metadata)
    if payload.tasks is not None:
        _check_plan(tree, key, payload.tasks)
        step.task_plan = [item.model_dump(mode="json") for item in payload.tasks]
    step.version += 1
    event = await content_changed(session, roadmap, prov, "step", key)
    return await finish(session, principal, roadmap, prov, [event])


async def reorder_steps(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    phase_key: str,
    payload: Reorder,
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session,
        principal,
        roadmap_id,
        WriteKind.CONTENT,
        payload.provenance,
        payload.expected_roadmap_version,
    )
    phase = _phase(tree, phase_key)
    siblings = tree.steps_of(phase.id)
    _check_permutation([step.key for step in siblings], payload.ordered_keys, "ordered_keys")
    by_key = {step.key: step for step in siblings}
    _reposition([by_key[key] for key in payload.ordered_keys])
    await session.flush()
    event = await content_changed(session, roadmap, prov, "step_order", phase_key)
    return await finish(session, principal, roadmap, prov, [event])


async def delete_step(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    key: str,
    expected_roadmap_version: int,
    declared: WriteProvenance,
) -> Roadmap:
    """Draft only (DEC-0084 §2.5). A step joined to a Task is never deleted
    (`409 step_has_links`); dependency edges to and from it disappear with it."""
    roadmap, prov, tree = await _open(
        session, principal, roadmap_id, WriteKind.CONTENT, declared, expected_roadmap_version
    )
    _require_draft(roadmap)
    step = _step(tree, key)
    if tree.links.get(step.id):
        raise roadmap_error(status.HTTP_409_CONFLICT, RoadmapErrorCode.STEP_HAS_LINKS)
    phase_id = step.phase_id
    await session.delete(step)
    await session.flush()
    _reposition([other for other in tree.steps_of(phase_id) if other.id != step.id])
    event = await content_changed(session, roadmap, prov, "step", key)
    return await finish(session, principal, roadmap, prov, [event])


# --- progress ---
async def update_step_progress(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    key: str,
    payload: StepProgressUpdate,
    expected_version: int,
) -> Roadmap:
    """Bounded progress write (override, notes, checked criteria): applied
    directly for any writer, never a proposal, never a snapshot revision. Only
    an override change moves the roadmap version (it changes derived state)."""
    roadmap, prov, tree = await _open(
        session, principal, roadmap_id, WriteKind.PROGRESS, payload.provenance
    )
    step = _step(tree, key)
    check_version(step.version, expected_version)
    roadmap_moved = False
    if payload.clear_state_override:
        roadmap_moved = step.state_override is not None
        step.state_override = None
        step.state_override_reason = None
    elif payload.state_override is not None:
        roadmap_moved = step.state_override != payload.state_override.value
        step.state_override = payload.state_override.value
    if payload.state_override_reason is not None and not payload.clear_state_override:
        step.state_override_reason = text_or_none(payload.state_override_reason)
    if payload.notes is not None:
        step.notes = text_or_none(payload.notes)
    if payload.criteria_checked is not None:
        if any(index >= len(step.acceptance_criteria) for index in payload.criteria_checked):
            raise invalid_roadmap(
                RoadmapValidationReason.LIMIT_EXCEEDED.value, f"steps.{key}.criteria_checked"
            )
        step.criteria_checked = sorted(payload.criteria_checked)
    step.version += 1
    if roadmap_moved:
        roadmap.version += 1
    event = updated_event(roadmap, "step_progress", key)
    return await finish(session, principal, roadmap, prov, [event])


# --- dependencies ---
async def add_dependency(
    session: AsyncSession, principal: Principal, roadmap_id: uuid.UUID, payload: DependencyChange
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session,
        principal,
        roadmap_id,
        WriteKind.CONTENT,
        payload.provenance,
        payload.expected_roadmap_version,
    )
    step = _step(tree, payload.step_key)
    target = _step(tree, payload.depends_on_key)
    if step.id == target.id:
        raise invalid_roadmap(
            RoadmapValidationReason.SELF_DEPENDENCY.value, f"steps.{step.key}.depends_on"
        )
    existing = tree.deps.get(step.id, [])
    if target.id in existing:
        return await finish(session, principal, roadmap, prov, [])
    if len(existing) >= MAX_DEPENDENCIES_PER_STEP:
        raise limit_exceeded("dependencies_per_step")
    edges = tree.edges()
    edges[step.key] = [*edges[step.key], target.key]
    cycle = find_dependency_cycle(edges)
    if cycle is not None:
        raise roadmap_error(status.HTTP_409_CONFLICT, RoadmapErrorCode.DEPENDENCY_CYCLE, path=cycle)
    session.add(
        RoadmapStepDependencyModel(
            step_id=step.id, depends_on_step_id=target.id, roadmap_id=roadmap.id
        )
    )
    await session.flush()
    event = await content_changed(session, roadmap, prov, "dependency", step.key)
    return await finish(session, principal, roadmap, prov, [event])


async def remove_dependency(
    session: AsyncSession, principal: Principal, roadmap_id: uuid.UUID, payload: DependencyChange
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session,
        principal,
        roadmap_id,
        WriteKind.CONTENT,
        payload.provenance,
        payload.expected_roadmap_version,
    )
    step = _step(tree, payload.step_key)
    target = _step(tree, payload.depends_on_key)
    if target.id not in tree.deps.get(step.id, []):
        return await finish(session, principal, roadmap, prov, [])
    await session.execute(
        delete(RoadmapStepDependencyModel).where(
            RoadmapStepDependencyModel.step_id == step.id,
            RoadmapStepDependencyModel.depends_on_step_id == target.id,
        )
    )
    event = await content_changed(session, roadmap, prov, "dependency", step.key)
    return await finish(session, principal, roadmap, prov, [event])


# --- Step <-> Task links ---
async def link_task(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    key: str,
    payload: LinkTask,
) -> Roadmap:
    roadmap, prov, tree = await _open(
        session, principal, roadmap_id, WriteKind.LINK, payload.provenance
    )
    step = _step(tree, key)
    task = await session.get(TaskModel, payload.task_id)
    if task is None:
        raise reference_not_found("task")
    if task.project_id != roadmap.project_id:
        raise roadmap_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            RoadmapErrorCode.TASK_PROJECT_MISMATCH,
            message="the task belongs to another project",
        )
    links = tree.links.get(step.id, [])
    if any(link.task_id == task.id for link in links):
        return await finish(session, principal, roadmap, prov, [])
    if len(links) >= MAX_LINKS_PER_STEP:
        raise limit_exceeded("links_per_step")
    session.add(RoadmapStepTaskLinkModel(step_id=step.id, task_id=task.id, **prov.columns()))
    await session.flush()
    step.version += 1
    roadmap.version += 1
    return await finish(session, principal, roadmap, prov, [updated_event(roadmap, "link", key)])


async def unlink_task(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    key: str,
    task_id: uuid.UUID,
    declared: WriteProvenance,
) -> Roadmap:
    """Removes the join only; the Task itself is never touched. Unlinking an
    absent link is a successful no-op."""
    roadmap, prov, tree = await _open(session, principal, roadmap_id, WriteKind.LINK, declared)
    step = _step(tree, key)
    result = await session.execute(
        delete(RoadmapStepTaskLinkModel).where(
            RoadmapStepTaskLinkModel.step_id == step.id,
            RoadmapStepTaskLinkModel.task_id == task_id,
        )
    )
    if not getattr(result, "rowcount", 0):
        return await finish(session, principal, roadmap, prov, [])
    step.version += 1
    roadmap.version += 1
    return await finish(session, principal, roadmap, prov, [updated_event(roadmap, "link", key)])
