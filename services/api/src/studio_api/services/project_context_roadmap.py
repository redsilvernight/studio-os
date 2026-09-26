"""Roadmap section of `studio_prepare_context` (Roadmaps P6, DEC-0088).

Answers "what should I work on now, and why?" from the Roadmap domain, never
"give me the whole Roadmap". Same contract as the rest of the facade: a
read-only, deterministic selection over what `studio_api.services.roadmaps`
already derives (state, availability, progress, current step), so no rule is
re-implemented here and no SQL is written.

* Only an `active` roadmap yields the `roadmap` slice (DEC-0084 §8). Drafts,
  proposals and completed roadmaps are summarised, by reference only, in
  `roadmap_overview`; a project without any roadmap yields neither.
* Free text competes for a dedicated slice of the shared character budget, in
  the priority current step > blockers > linked Tasks > criteria > upcoming
  steps > roadmap objective, so the section can neither starve nor swamp the
  essential context taken before and after it. Identity and position fields
  (ids, keys, titles of the roadmap and of the current step, state, progress)
  are the anchor of the section and, like other fixed fields, are not counted.
* A Task already represented elsewhere in the package is referenced by id
  (`in_context`), never copied.
* A Roadmap source that fails is reported (`unavailable`) instead of failing
  the whole context.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.project_context import (
    RoadmapItem,
    RoadmapOverview,
    RoadmapRef,
    RoadmapStepItem,
    RoadmapTaskRef,
    TaskLocation,
    Why,
)
from studio_contracts.roadmaps import (
    ContextStep,
    LinkedTask,
    Phase,
    Roadmap,
    RoadmapStatus,
    RoadmapSummary,
    Step,
    StepState,
)

from studio_api.services import roadmaps as roadmaps_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal

__all__ = [
    # Canonical contract re-exports (live in studio_contracts.project_context).
    "RoadmapItem",
    "RoadmapOverview",
    "RoadmapRef",
    "RoadmapStepItem",
    "RoadmapTaskRef",
    "TaskLocation",
    "Why",
    # Section entry points.
    "RoadmapSelection",
    "TextBudget",
    "select_roadmap",
]

TITLE_CAP = 200
OBJECTIVE_CAP = 600
CRITERION_CAP = 500  # the contract's own maximum: only an exhausted budget can cut one
MAX_UPCOMING_STEPS = 5  # `RoadmapContext.upcoming_steps` bound
MAX_BLOCKING = 10
MAX_CRITERIA = 10
MAX_ROADMAPS_SCANNED = 50

_DONE = (StepState.DONE, StepState.SKIPPED)
_OVERVIEW_RANK = {
    RoadmapStatus.PROPOSED: 0,
    RoadmapStatus.DRAFT: 1,
    RoadmapStatus.COMPLETED: 2,
}


class TextBudget(Protocol):
    """The slice of the shared character budget the section spends from."""

    def take(self, text: str, cap: int) -> tuple[str, bool] | None: ...

    def take_whole(self, text: str) -> bool: ...

    def mark(self) -> int: ...

    def rollback(self, mark: int) -> None: ...


@dataclass
class RoadmapSelection:
    item: RoadmapItem | None = None
    overview: RoadmapOverview | None = None
    omitted: dict[str, int] = field(default_factory=dict)
    additional: dict[str, int] = field(default_factory=dict)
    unavailable: bool = False
    scan_capped: bool = False


def _title(text: str) -> tuple[str, bool]:
    return text[:TITLE_CAP], len(text) > TITLE_CAP


def _bump(counter: dict[str, int], key: str, amount: int = 1) -> None:
    if amount > 0:
        counter[key] = counter.get(key, 0) + amount


def _ordered_steps(roadmap: Roadmap) -> list[tuple[Phase, Step]]:
    phases = sorted(roadmap.phases, key=lambda phase: (phase.position, phase.key))
    return [
        (phase, step)
        for phase in phases
        for step in sorted(phase.steps, key=lambda step: (step.position, step.key))
    ]


def _blocking_keys(steps: list[Step]) -> list[str]:
    """Unfinished work that stops other steps, in plan order: steps whose Tasks
    are blocked, then unmet dependencies. A step that can be worked on right now
    is not a blocker — it is the work itself, already in `current_step`/`upcoming`."""
    available = {
        step.key for step in steps if step.available and step.state is not StepState.BLOCKED
    }
    ordered: dict[str, None] = {}
    for step in steps:
        if step.state in _DONE:
            continue
        if step.state is StepState.BLOCKED:
            ordered.setdefault(step.key, None)
        for dependency in step.waiting_on:
            ordered.setdefault(dependency, None)
    return [key for key in ordered if key not in available]


def _linked(step: Step) -> list[LinkedTask]:
    """Linked Tasks in a total order: the service does not promise one, and the
    facade must not depend on database row order."""
    return sorted(step.linked_tasks, key=lambda linked: str(linked.task_id))


def _step_task_ids(step: Step) -> list[uuid.UUID]:
    return [linked.task_id for linked in _linked(step)]


def _base_step(step: Step) -> RoadmapStepItem:
    """The anchor of a step: identity, state, availability — title not counted."""
    title, truncated = _title(step.title)
    checked = {
        index for index in step.criteria_checked if 0 <= index < len(step.acceptance_criteria)
    }
    return RoadmapStepItem(
        key=step.key,
        title=title,
        state=step.state,
        available=step.available,
        waiting_on=list(step.waiting_on),
        truncated=truncated,
        criteria_total=len(step.acceptance_criteria),
        criteria_checked=len(checked),
    )


def _add_objective(
    item: RoadmapStepItem, step: Step, budget: TextBudget, omitted: dict[str, int]
) -> None:
    if not step.objective:
        return
    taken = budget.take(step.objective, OBJECTIVE_CAP)
    if taken is None:
        _bump(omitted, "roadmap_objective")
        return
    item.objective, cut = taken
    item.truncated = item.truncated or cut


async def _add_linked_tasks(
    session: AsyncSession,
    project_id: uuid.UUID,
    item: RoadmapStepItem,
    step: Step,
    limit: int,
    known: dict[uuid.UUID, TaskLocation],
    budget: TextBudget,
    omitted: dict[str, int],
    additional: dict[str, int],
) -> None:
    linked = _linked(step)
    _bump(additional, "roadmap_linked_tasks", max(0, len(linked) - limit))
    for entry in linked[:limit]:
        if entry.task_id in known:
            item.linked_task_ids.append(entry.task_id)
            item.linked_tasks.append(
                RoadmapTaskRef(id=entry.task_id, in_context=known[entry.task_id])
            )
            continue
        task = await tasks_service.get_task(session, entry.task_id)
        # A dangling or foreign-project link is partial data, never a leak.
        if task is None or task.project_id != project_id:
            _bump(omitted, "roadmap_linked_tasks")
            continue
        item.linked_task_ids.append(task.id)  # verified: same project, exists
        taken = budget.take(task.title, TITLE_CAP)
        if taken is None:
            _bump(omitted, "roadmap_linked_tasks")
            continue
        item.linked_tasks.append(RoadmapTaskRef(id=task.id, title=taken[0], status=task.status))


def _add_criteria(
    item: RoadmapStepItem,
    step: Step,
    budget: TextBudget,
    omitted: dict[str, int],
    additional: dict[str, int],
) -> None:
    checked = set(step.criteria_checked)
    pending = [text for index, text in enumerate(step.acceptance_criteria) if index not in checked]
    for text in pending[:MAX_CRITERIA]:
        taken = budget.take(text, CRITERION_CAP)
        if taken is None:
            _bump(omitted, "roadmap_criteria")
            continue
        item.acceptance_criteria.append(taken[0])
        item.truncated = item.truncated or taken[1]
    _bump(additional, "roadmap_criteria", max(0, len(pending) - MAX_CRITERIA))


def _upcoming(
    steps: list[Step],
    exclude: set[str],
    limit: int,
    budget: TextBudget,
    omitted: dict[str, int],
    additional: dict[str, int],
) -> list[ContextStep]:
    candidates = [step for step in steps if step.available and step.key not in exclude]
    wanted = min(limit, MAX_UPCOMING_STEPS)
    _bump(additional, "roadmap_upcoming_steps", max(0, len(candidates) - wanted))
    picked: list[ContextStep] = []
    for step in candidates[:wanted]:
        taken = budget.take(step.title, TITLE_CAP)
        if taken is None:
            _bump(omitted, "roadmap_upcoming_steps")
            continue
        picked.append(
            ContextStep(
                key=step.key,
                title=taken[0],
                state=step.state,
                available=step.available,
                waiting_on=list(step.waiting_on),
            )
        )
    return picked


async def _build_item(
    session: AsyncSession,
    project_id: uuid.UUID,
    roadmap: Roadmap,
    draft_pending: int,
    task_id: uuid.UUID | None,
    known: dict[uuid.UUID, TaskLocation],
    limit: int,
    budget: TextBudget,
    selection: RoadmapSelection,
) -> RoadmapItem:
    omitted, additional = selection.omitted, selection.additional
    ordered = _ordered_steps(roadmap)
    steps = [step for _, step in ordered]
    by_key = {step.key: (phase, step) for phase, step in ordered}

    current_phase, current_step = by_key.get(roadmap.current_step_key or "", (None, None))
    task_step: Step | None = None
    if task_id is not None:
        task_step = next(
            (
                step
                for step in steps
                if task_id in _step_task_ids(step) and step is not current_step
            ),
            None,
        )

    title, title_cut = _title(roadmap.title)
    item = RoadmapItem(
        roadmap_id=roadmap.id,
        title=title,
        progress=roadmap.progress,
        status=roadmap.status,
        current_phase_key=current_phase.key if current_phase is not None else None,
        current_step=_base_step(current_step) if current_step is not None else None,
        task_step=_base_step(task_step) if task_step is not None else None,
        draft_pending=draft_pending,
        truncated=title_cut,
        why=Why(reason="active_roadmap"),
    )
    focus = [
        (built, step)
        for built, step in ((item.current_step, current_step), (item.task_step, task_step))
        if built is not None and step is not None
    ]

    # Priority order — each tier spends only what the previous ones left.
    for built, step in focus:  # 1. current step (and the requested Task's step)
        _add_objective(built, step, budget, omitted)

    blocking = _blocking_keys(steps)  # 2. blockers
    _bump(additional, "roadmap_blocking", max(0, len(blocking) - MAX_BLOCKING))
    for key in blocking[:MAX_BLOCKING]:
        if budget.take_whole(key):
            item.blocking.append(key)
        else:
            _bump(omitted, "roadmap_blocking")

    for built, step in focus:  # 3. linked Tasks
        await _add_linked_tasks(
            session, project_id, built, step, limit, known, budget, omitted, additional
        )
    for built, step in focus:  # 4. acceptance criteria
        _add_criteria(built, step, budget, omitted, additional)

    exclude = {step.key for _, step in focus}  # 5. next available steps
    item.upcoming_steps = _upcoming(steps, exclude, limit, budget, omitted, additional)

    if roadmap.objective:  # 6. secondary context
        taken = budget.take(roadmap.objective, OBJECTIVE_CAP)
        if taken is None:
            _bump(omitted, "roadmap_context")
        else:
            item.objective = taken[0]
            item.truncated = item.truncated or taken[1]
    return item


def _overview(
    summaries: list[RoadmapSummary], limit: int, selection: RoadmapSelection
) -> RoadmapOverview | None:
    live = [s for s in summaries if s.status is not RoadmapStatus.ARCHIVED]
    others = sorted(
        (s for s in live if s.status is not RoadmapStatus.ACTIVE),
        key=lambda s: _OVERVIEW_RANK.get(s.status, 9),  # stable: newest first within a status
    )
    if not others:
        return None
    counts: dict[str, int] = {}
    for summary in live:
        _bump(counts, summary.status.value)
    _bump(selection.additional, "roadmaps", max(0, len(others) - limit))
    refs = []
    for summary in others[:limit]:
        title, cut = _title(summary.title)
        refs.append(
            RoadmapRef(
                id=summary.id,
                title=title,
                status=summary.status,
                progress=summary.progress,
                truncated=cut,
            )
        )
    pending = sum(1 for s in live if s.status in (RoadmapStatus.DRAFT, RoadmapStatus.PROPOSED))
    return RoadmapOverview(counts=dict(sorted(counts.items())), draft_pending=pending, others=refs)


async def select_roadmap(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    known_tasks: dict[uuid.UUID, TaskLocation],
    limit: int,
    budget: TextBudget,
) -> RoadmapSelection:
    """Select the Roadmap context of one project. Never raises for a missing,
    partial or unreadable Roadmap: the section is simply absent, and an
    unreadable source is flagged `unavailable`. The reads run in a savepoint so
    a database failure cannot poison the rest of the facade."""
    selection = RoadmapSelection()
    mark = budget.mark()
    try:
        async with session.begin_nested():
            # By status, so archived roadmaps never crowd out an older active one
            # and only the roadmaps that matter are read.
            summaries = list(
                await roadmaps_service.list_roadmaps(
                    session, principal, project_id, RoadmapStatus.ACTIVE, 1
                )
            )
            for other in _OVERVIEW_RANK:
                rows = await roadmaps_service.list_roadmaps(
                    session, principal, project_id, other, MAX_ROADMAPS_SCANNED
                )
                selection.scan_capped = selection.scan_capped or len(rows) == MAX_ROADMAPS_SCANNED
                summaries.extend(rows)
            selection.overview = _overview(summaries, limit, selection)
            active = next((s for s in summaries if s.status is RoadmapStatus.ACTIVE), None)
            if active is not None:
                detail = await roadmaps_service.get_roadmap(session, principal, active.id)
                pending = sum(
                    1
                    for s in summaries
                    if s.status in (RoadmapStatus.DRAFT, RoadmapStatus.PROPOSED)
                )
                selection.item = await _build_item(
                    session,
                    project_id,
                    detail,
                    pending,
                    task_id,
                    known_tasks,
                    limit,
                    budget,
                    selection,
                )
    except Exception:  # noqa: BLE001 - the Roadmap is optional: whatever fails, the rest answers
        budget.rollback(mark)  # nothing of a failed section was returned, so nothing is charged
        return RoadmapSelection(unavailable=True)
    return selection
