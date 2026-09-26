"""Shared building blocks of the Roadmap domain service (Roadmaps P2).

Errors, provenance resolution, the loaded plan tree, the read models derived
from it (state, availability, progress use the pure rules of
`studio_contracts.roadmaps` — one implementation for API, MCP and Dashboard),
the neutral document builder, revision snapshots and event emission. The
public operations live in `roadmaps`, `roadmap_structure` and
`roadmap_hydration`; this module holds no route logic and no policy of its own
beyond the write guard.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.events import EventCreate, EventType
from studio_contracts.roadmaps import (
    DiffChange,
    DiffEntry,
    LinkedTask,
    Phase,
    PhaseContent,
    Progress,
    Provenance,
    RevisionKind,
    RevisionStatus,
    Roadmap,
    RoadmapDocument,
    RoadmapErrorCode,
    RoadmapErrorDetail,
    RoadmapOrigin,
    RoadmapRevision,
    RoadmapRevisionSummary,
    RoadmapStatus,
    RoadmapSummary,
    RoadmapTransition,
    Step,
    StepContent,
    StepState,
    StepStateOverride,
    TaskPlanItem,
    TaskProgress,
    TaskStatusValue,
    WriteKind,
    WriteProvenance,
    compute_progress,
    derive_step_state,
    is_agent_write,
    waiting_on,
    write_allowed,
)

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.roadmap import (
    RoadmapModel,
    RoadmapPhaseModel,
    RoadmapRevisionModel,
    RoadmapStepDependencyModel,
    RoadmapStepModel,
    RoadmapStepTaskLinkModel,
)
from studio_api.db.models.task import TaskModel
from studio_api.services import events as events_service
from studio_api.services.authz import (
    Principal,
    ProjectAction,
    ensure_can_write,
    ensure_project_access,
)


# --- errors ---
def roadmap_error(
    status_code: int,
    code: RoadmapErrorCode,
    *,
    message: str | None = None,
    reason: str | None = None,
    field_name: str | None = None,
    server_version: int | None = None,
    server_revision_no: int | None = None,
    roadmap_status: RoadmapStatus | None = None,
    transition: RoadmapTransition | None = None,
    path: list[str] | None = None,
    limit: str | None = None,
) -> HTTPException:
    """`{"detail": {"error_code": ...}}` envelope of the existing API, built
    from the closed `RoadmapErrorDetail` so an undocumented member cannot leak."""
    detail = RoadmapErrorDetail(
        error_code=code,
        message=message,
        reason=reason,
        field=field_name,
        server_version=server_version,
        server_revision_no=server_revision_no,
        status=roadmap_status,
        transition=transition,
        path=path,
        limit=limit,
    )
    return HTTPException(status_code, detail=detail.model_dump(mode="json", exclude_none=True))


def not_found(what: str = "roadmap") -> HTTPException:
    return roadmap_error(status.HTTP_404_NOT_FOUND, RoadmapErrorCode.NOT_FOUND, message=what)


def reference_not_found(what: str) -> HTTPException:
    return roadmap_error(
        status.HTTP_404_NOT_FOUND, RoadmapErrorCode.REFERENCE_NOT_FOUND, message=what
    )


def invalid_state(
    roadmap_status: RoadmapStatus, message: str, transition: RoadmapTransition | None = None
) -> HTTPException:
    return roadmap_error(
        status.HTTP_409_CONFLICT,
        RoadmapErrorCode.INVALID_STATE,
        message=message,
        roadmap_status=roadmap_status,
        transition=transition,
    )


def invalid_roadmap(reason: str, field_name: str) -> HTTPException:
    return roadmap_error(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        RoadmapErrorCode.INVALID_ROADMAP,
        reason=reason,
        field_name=field_name,
    )


def step_has_links() -> HTTPException:
    return roadmap_error(status.HTTP_409_CONFLICT, RoadmapErrorCode.STEP_HAS_LINKS)


def limit_exceeded(limit: str) -> HTTPException:
    return roadmap_error(
        status.HTTP_422_UNPROCESSABLE_CONTENT, RoadmapErrorCode.LIMIT_EXCEEDED, limit=limit
    )


def check_version(current: int, expected: int) -> None:
    if current != expected:
        raise roadmap_error(
            status.HTTP_409_CONFLICT, RoadmapErrorCode.VERSION_CONFLICT, server_version=current
        )


# --- provenance ---
@dataclass(frozen=True)
class ResolvedProvenance:
    """Server-derived provenance (DEC-0084 §7): the actor is the machine's
    owner unless a declared `agent_id` is attached to the authenticated machine."""

    origin: str
    actor_type: str
    actor_id: uuid.UUID
    agent_id: uuid.UUID | None
    machine_id: uuid.UUID | None

    def columns(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "agent_id": self.agent_id,
            "machine_id": self.machine_id,
        }


async def resolve_provenance(
    session: AsyncSession, principal: Principal, declared: WriteProvenance
) -> ResolvedProvenance:
    if declared.agent_id is not None:
        agent = await session.get(AgentModel, declared.agent_id)
        if agent is None or agent.machine_id != principal.machine.id:
            raise roadmap_error(
                status.HTTP_409_CONFLICT,
                RoadmapErrorCode.ACTOR_NOT_OWNED,
                message="agent_id must be an agent attached to the authenticated machine",
            )
        return ResolvedProvenance(
            declared.origin.value, "agent", agent.id, agent.id, principal.machine.id
        )
    return ResolvedProvenance(
        declared.origin.value, "user", principal.user.id, None, principal.machine.id
    )


def provenance_view(row: Any) -> Provenance:
    return Provenance(
        origin=RoadmapOrigin(row.origin),
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        agent_id=row.agent_id,
        machine_id=row.machine_id,
        at=row.created_at,
    )


def _revision_status(value: str | None) -> RevisionStatus | None:
    return RevisionStatus(value) if value is not None else None


def revision_summary_view(row: RoadmapRevisionModel) -> RoadmapRevisionSummary:
    return RoadmapRevisionSummary(
        id=row.id,
        roadmap_id=row.roadmap_id,
        revision_no=row.revision_no,
        kind=RevisionKind(row.kind),
        status=_revision_status(row.status),
        base_revision_no=row.base_revision_no,
        summary=row.summary,
        provenance=provenance_view(row),
        reviewed_by_user_id=row.reviewed_by_user_id,
        reviewed_at=row.reviewed_at,
        review_comment=row.review_comment,
    )


def revision_view(row: RoadmapRevisionModel) -> RoadmapRevision:
    summary = revision_summary_view(row)
    return RoadmapRevision(
        **summary.model_dump(),
        content=RoadmapDocument.model_validate(row.content) if row.content is not None else None,
    )


# --- locking and write guard ---
async def lock_roadmap(session: AsyncSession, roadmap_id: uuid.UUID) -> RoadmapModel:
    """`SELECT ... FOR UPDATE`: every mutation serializes on its roadmap row, so
    a version check is followed by an atomic write and two writers can never
    both pass the same expected version."""
    result = await session.execute(
        select(RoadmapModel)
        .where(RoadmapModel.id == roadmap_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    roadmap = result.scalar_one_or_none()
    if roadmap is None:
        raise not_found()
    return roadmap


async def ensure_roadmap_access(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    action: ProjectAction = "read",
) -> RoadmapModel:
    """Load a roadmap (404 when absent) and check its project level
    (DEC-0103 §7): an inaccessible project answers 403 before anything of the
    roadmap is returned."""
    roadmap = await session.get(RoadmapModel, roadmap_id)
    if roadmap is None:
        raise not_found()
    ensure_project_access(principal, roadmap.project_id, action)
    return roadmap


async def authorize_roadmap_write(
    session: AsyncSession, principal: Principal, roadmap_id: uuid.UUID
) -> None:
    """Project then role check of a roadmap mutation, run ahead of the
    idempotency replay short-circuit (DEC-0036, DEC-0103 §12)."""
    await ensure_roadmap_access(session, principal, roadmap_id, "write")
    ensure_can_write(principal, "roadmap")


def authorize_roadmap_create(principal: Principal, project_id: uuid.UUID) -> None:
    """Project then role check of a roadmap creation or import."""
    ensure_project_access(principal, project_id, "write")
    ensure_can_write(principal, "roadmap")


def guard_write(
    principal: Principal,
    roadmap: RoadmapModel,
    kind: WriteKind,
    declared: WriteProvenance,
) -> None:
    """`readonly` never writes; the status must accept this kind of write
    (`ALLOWED_WRITES`); an agent *content* write on an `active` roadmap is never
    applied directly (DEC-0084 §6). It must go through the proposal endpoint
    (`POST .../proposals`, `WriteKind.PROPOSAL`) so the change becomes a pending
    revision a human reviews: refused explicitly here, never silently applied
    and never dropped."""
    ensure_project_access(principal, roadmap.project_id, "write")
    ensure_can_write(principal, "roadmap")
    current = RoadmapStatus(roadmap.status)
    if not write_allowed(current, kind):
        raise invalid_state(current, f"a {roadmap.status} roadmap does not accept {kind.value}")
    if (
        kind is WriteKind.CONTENT
        and current is RoadmapStatus.ACTIVE
        and is_agent_write(principal.role == Role.AGENT, declared)
    ):
        raise invalid_state(
            current,
            "content changes by an agent on an active roadmap require a proposal: "
            f"POST /api/v1/roadmaps/{roadmap.id}/proposals",
        )


# --- plan tree ---
@dataclass
class RoadmapTree:
    roadmap: RoadmapModel
    phases: list[RoadmapPhaseModel]
    steps: list[RoadmapStepModel]
    deps: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)
    links: dict[uuid.UUID, list[RoadmapStepTaskLinkModel]] = field(default_factory=dict)
    task_status: dict[uuid.UUID, TaskStatusValue] = field(default_factory=dict)

    def steps_of(self, phase_id: uuid.UUID) -> list[RoadmapStepModel]:
        return [step for step in self.steps if step.phase_id == phase_id]

    def step_by_key(self, key: str) -> RoadmapStepModel | None:
        return next((step for step in self.steps if step.key == key), None)

    def phase_by_key(self, key: str) -> RoadmapPhaseModel | None:
        return next((phase for phase in self.phases if phase.key == key), None)

    def key_of(self, step_id: uuid.UUID) -> str:
        return next(step.key for step in self.steps if step.id == step_id)

    def edges(self) -> dict[str, list[str]]:
        return {step.key: self.depends_on_keys(step) for step in self.steps}

    def depends_on_keys(self, step: RoadmapStepModel) -> list[str]:
        order = {s.id: index for index, s in enumerate(self.steps)}
        targets = sorted(self.deps.get(step.id, []), key=lambda step_id: order[step_id])
        return [self.key_of(target) for target in targets]

    def states(self) -> dict[str, StepState]:
        return {step.key: self._state(step) for step in self.steps}

    def _state(self, step: RoadmapStepModel) -> StepState:
        override = StepStateOverride(step.state_override) if step.state_override else None
        statuses = [
            self.task_status[link.task_id]
            for link in self.links.get(step.id, [])
            if link.task_id in self.task_status
        ]
        return derive_step_state(override, statuses)


def _link_order(
    step: RoadmapStepModel,
) -> Callable[[RoadmapStepTaskLinkModel], tuple[int, Any, str]]:
    plan_index = {item["hydration_key"]: i for i, item in enumerate(step.task_plan)}

    def key(link: RoadmapStepTaskLinkModel) -> tuple[int, Any, str]:
        return (
            plan_index.get(link.hydration_key or "", len(plan_index)),
            link.created_at,
            str(link.id),
        )

    return key


async def load_tree(session: AsyncSession, roadmap: RoadmapModel) -> RoadmapTree:
    """Reads the whole plan of one roadmap in a fixed number of queries (no
    per-step round trip). Flushes first so an in-flight change is visible."""
    await session.flush()
    phases = list(
        (
            await session.execute(
                select(RoadmapPhaseModel)
                .where(RoadmapPhaseModel.roadmap_id == roadmap.id)
                .order_by(RoadmapPhaseModel.position, RoadmapPhaseModel.key)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    phase_order = {phase.id: index for index, phase in enumerate(phases)}
    raw_steps = list(
        (
            await session.execute(
                select(RoadmapStepModel)
                .where(RoadmapStepModel.roadmap_id == roadmap.id)
                .order_by(RoadmapStepModel.position, RoadmapStepModel.key)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    steps = sorted(raw_steps, key=lambda step: phase_order[step.phase_id])
    tree = RoadmapTree(roadmap=roadmap, phases=phases, steps=steps)

    edge_rows = (
        (
            await session.execute(
                select(RoadmapStepDependencyModel).where(
                    RoadmapStepDependencyModel.roadmap_id == roadmap.id
                )
            )
        )
        .scalars()
        .all()
    )
    for edge in edge_rows:
        tree.deps.setdefault(edge.step_id, []).append(edge.depends_on_step_id)

    step_ids = [step.id for step in steps]
    if step_ids:
        link_rows = (
            (
                await session.execute(
                    select(RoadmapStepTaskLinkModel)
                    .where(RoadmapStepTaskLinkModel.step_id.in_(step_ids))
                    .order_by(RoadmapStepTaskLinkModel.created_at, RoadmapStepTaskLinkModel.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        for link in link_rows:
            tree.links.setdefault(link.step_id, []).append(link)
        # Deterministic order that survives a single-transaction hydration (all
        # `created_at` equal): plan order of the `hydration_key`, then the rest.
        for step in steps:
            tree.links.get(step.id, []).sort(key=_link_order(step))
        task_ids = {link.task_id for link in link_rows}
        if task_ids:
            for task_id, task_status in (
                await session.execute(
                    select(TaskModel.id, TaskModel.status).where(TaskModel.id.in_(task_ids))
                )
            ).all():
                tree.task_status[task_id] = TaskStatusValue(task_status)
    return tree


# --- read models ---
def _step_view(tree: RoadmapTree, step: RoadmapStepModel, states: dict[str, StepState]) -> Step:
    depends_on = tree.depends_on_keys(step)
    links = tree.links.get(step.id, [])
    state = states[step.key]
    waiting = waiting_on(depends_on, states)
    completed = sum(
        1 for link in links if tree.task_status.get(link.task_id) is TaskStatusValue.COMPLETED
    )
    return Step(
        created_at=step.created_at,
        updated_at=step.updated_at,
        version=step.version,
        id=step.id,
        roadmap_id=step.roadmap_id,
        phase_id=step.phase_id,
        key=step.key,
        position=step.position,
        title=step.title,
        objective=step.objective,
        context=step.context,
        instructions=step.instructions,
        acceptance_criteria=list(step.acceptance_criteria),
        criteria_checked=list(step.criteria_checked),
        notes=step.notes,
        metadata=dict(step.step_metadata),
        depends_on=depends_on,
        tasks=[TaskPlanItem.model_validate(item) for item in step.task_plan],
        linked_tasks=[
            LinkedTask(
                task_id=link.task_id,
                hydration_key=link.hydration_key,
                origin=RoadmapOrigin(link.origin),
            )
            for link in links
        ],
        state_override=StepStateOverride(step.state_override) if step.state_override else None,
        state_override_reason=step.state_override_reason,
        state=state,
        available=state not in (StepState.DONE, StepState.SKIPPED) and not waiting,
        waiting_on=waiting,
        task_progress=TaskProgress(completed=completed, total=len(links)),
        provenance=provenance_view(step),
    )


def _progress(tree: RoadmapTree, states: dict[str, StepState], phase_id: uuid.UUID | None) -> Any:
    keys = [step.key for step in tree.steps if phase_id is None or step.phase_id == phase_id]
    return compute_progress([states[key] for key in keys])


def _summary_fields(tree: RoadmapTree, progress: Progress, current: str | None) -> dict[str, Any]:
    roadmap = tree.roadmap
    return {
        "created_at": roadmap.created_at,
        "updated_at": roadmap.updated_at,
        "version": roadmap.version,
        "id": roadmap.id,
        "project_id": roadmap.project_id,
        "title": roadmap.title,
        "objective": roadmap.objective,
        "status": RoadmapStatus(roadmap.status),
        "revision_no": roadmap.revision_no,
        "approved_revision_no": roadmap.approved_revision_no,
        "progress": progress,
        "current_step_key": current,
        "provenance": provenance_view(roadmap),
    }


def build_roadmap(tree: RoadmapTree) -> Roadmap:
    states = tree.states()
    views = {step.id: _step_view(tree, step, states) for step in tree.steps}
    phases = [
        Phase(
            created_at=phase.created_at,
            updated_at=phase.updated_at,
            version=phase.version,
            id=phase.id,
            roadmap_id=phase.roadmap_id,
            key=phase.key,
            position=phase.position,
            title=phase.title,
            objective=phase.objective,
            progress=_progress(tree, states, phase.id),
            steps=[views[step.id] for step in tree.steps_of(phase.id)],
        )
        for phase in tree.phases
    ]
    current = next((views[step.id].key for step in tree.steps if views[step.id].available), None)
    return Roadmap(
        **_summary_fields(tree, _progress(tree, states, None), current),
        context=tree.roadmap.context,
        metadata=dict(tree.roadmap.roadmap_metadata),
        phases=phases,
    )


def build_summary(tree: RoadmapTree) -> RoadmapSummary:
    states = tree.states()
    current = None
    for step in tree.steps:
        state = states[step.key]
        if state in (StepState.DONE, StepState.SKIPPED):
            continue
        if not waiting_on(tree.depends_on_keys(step), states):
            current = step.key
            break
    return RoadmapSummary(**_summary_fields(tree, _progress(tree, states, None), current))


def build_document(tree: RoadmapTree) -> RoadmapDocument:
    """The neutral plan of the current state: no id, no status, no link to an
    existing Task, no provenance."""
    return RoadmapDocument(
        title=tree.roadmap.title,
        objective=tree.roadmap.objective,
        context=tree.roadmap.context,
        metadata=dict(tree.roadmap.roadmap_metadata),
        phases=[
            PhaseContent(
                key=phase.key,
                title=phase.title,
                objective=phase.objective,
                steps=[
                    StepContent(
                        key=step.key,
                        title=step.title,
                        objective=step.objective,
                        context=step.context,
                        instructions=step.instructions,
                        acceptance_criteria=list(step.acceptance_criteria),
                        notes=step.notes,
                        metadata=dict(step.step_metadata),
                        depends_on=tree.depends_on_keys(step),
                        tasks=[TaskPlanItem.model_validate(item) for item in step.task_plan],
                    )
                    for step in tree.steps_of(phase.id)
                ],
            )
            for phase in tree.phases
        ],
    )


async def read_roadmap(session: AsyncSession, roadmap: RoadmapModel) -> Roadmap:
    return build_roadmap(await load_tree(session, roadmap))


# --- revisions and events ---
async def next_revision_no(session: AsyncSession, roadmap: RoadmapModel) -> int:
    """Single monotonic source of a roadmap's revision numbers, shared by every
    kind (`snapshot`, `proposal`, `review`). A pending proposal does not move
    `roadmap.revision_no` (it is not applied content), so the next number is
    derived from the highest row already used: no two revisions ever share a
    number, which keeps `GET .../revisions/{n}` and the diff base unambiguous."""
    highest = (
        await session.execute(
            select(func.max(RoadmapRevisionModel.revision_no)).where(
                RoadmapRevisionModel.roadmap_id == roadmap.id
            )
        )
    ).scalar_one_or_none()
    return max(highest or 0, roadmap.revision_no) + 1


def add_revision(
    session: AsyncSession,
    roadmap: RoadmapModel,
    prov: ResolvedProvenance,
    *,
    kind: str,
    revision_no: int,
    document: RoadmapDocument,
    status_value: str | None = None,
    base_revision_no: int | None = None,
    summary: str | None = None,
) -> RoadmapRevisionModel:
    revision = RoadmapRevisionModel(
        roadmap_id=roadmap.id,
        revision_no=revision_no,
        kind=kind,
        status=status_value,
        base_revision_no=base_revision_no,
        summary=summary,
        content=document.model_dump(mode="json"),
        **prov.columns(),
    )
    session.add(revision)
    return revision


async def record_snapshot(
    session: AsyncSession, roadmap: RoadmapModel, prov: ResolvedProvenance
) -> None:
    """One `snapshot` revision per applied change of an `active` roadmap
    (DEC-0084 §6): the neutral document of the resulting state, so any earlier
    state can be re-proposed."""
    revision_no = await next_revision_no(session, roadmap)
    roadmap.revision_no = revision_no
    roadmap.approved_revision_no = revision_no
    document = build_document(await load_tree(session, roadmap))
    add_revision(
        session,
        roadmap,
        prov,
        kind="snapshot",
        revision_no=revision_no,
        document=document,
    )


# --- diff (P8.3) and proposal application ---
def _steps_by_key(document: RoadmapDocument | None) -> dict[str, tuple[str, StepContent]]:
    if document is None:
        return {}
    return {step.key: (phase.key, step) for phase in document.phases for step in phase.steps}


def compute_diff(base: RoadmapDocument | None, proposal: RoadmapDocument) -> list[DiffEntry]:
    """Human-readable diff (P8.3) computed at read time by matching phases and
    steps on their `key`; deterministic, never stored. A `None` base (no
    recorded base revision) treats every element as added."""
    entries: list[DiffEntry] = []
    if base is None:
        entries.append(DiffEntry(scope="roadmap", change=DiffChange.ADDED))
    else:
        fields = [
            name
            for name, previous, current in (
                ("title", base.title, proposal.title),
                ("objective", base.objective, proposal.objective),
                ("context", base.context, proposal.context),
                ("metadata", base.metadata, proposal.metadata),
            )
            if previous != current
        ]
        if fields:
            entries.append(DiffEntry(scope="roadmap", change=DiffChange.CHANGED, fields=fields))

    base_phases = {phase.key: phase for phase in (base.phases if base else [])}
    proposal_phases = {phase.key: phase for phase in proposal.phases}
    for key in sorted(set(base_phases) | set(proposal_phases)):
        previous = base_phases.get(key)
        current = proposal_phases.get(key)
        if previous is None:
            entries.append(DiffEntry(scope="phase", key=key, change=DiffChange.ADDED))
            continue
        if current is None:
            entries.append(DiffEntry(scope="phase", key=key, change=DiffChange.REMOVED))
            continue
        fields = [
            name
            for name, old, new in (
                ("title", previous.title, current.title),
                ("objective", previous.objective, current.objective),
            )
            if old != new
        ]
        if fields:
            entries.append(
                DiffEntry(scope="phase", key=key, change=DiffChange.CHANGED, fields=fields)
            )

    base_steps = _steps_by_key(base)
    proposal_steps = _steps_by_key(proposal)
    for key in sorted(set(base_steps) | set(proposal_steps)):
        previous_entry = base_steps.get(key)
        current_entry = proposal_steps.get(key)
        if previous_entry is None:
            entries.append(DiffEntry(scope="step", key=key, change=DiffChange.ADDED))
            continue
        if current_entry is None:
            entries.append(DiffEntry(scope="step", key=key, change=DiffChange.REMOVED))
            continue
        previous_phase, old_step = previous_entry
        current_phase, new_step = current_entry
        fields = [
            name
            for name, old, new in (
                ("title", old_step.title, new_step.title),
                ("objective", old_step.objective, new_step.objective),
                ("context", old_step.context, new_step.context),
                ("instructions", old_step.instructions, new_step.instructions),
                ("acceptance_criteria", old_step.acceptance_criteria, new_step.acceptance_criteria),
                ("notes", old_step.notes, new_step.notes),
                ("metadata", old_step.metadata, new_step.metadata),
            )
            if old != new
        ]
        if previous_phase != current_phase:
            fields.insert(0, "phase")
        if fields:
            entries.append(
                DiffEntry(scope="step", key=key, change=DiffChange.CHANGED, fields=fields)
            )

        added = sorted(set(new_step.depends_on) - set(old_step.depends_on))
        removed = sorted(set(old_step.depends_on) - set(new_step.depends_on))
        if added:
            entries.append(
                DiffEntry(scope="dependency", key=key, change=DiffChange.ADDED, fields=added)
            )
        if removed:
            entries.append(
                DiffEntry(scope="dependency", key=key, change=DiffChange.REMOVED, fields=removed)
            )

        old_plan = {item.hydration_key: item.title for item in old_step.tasks}
        new_plan = {item.hydration_key: item.title for item in new_step.tasks}
        planned = (
            [f"+{item}" for item in sorted(set(new_plan) - set(old_plan))]
            + [f"-{item}" for item in sorted(set(old_plan) - set(new_plan))]
            + [
                f"~{item}"
                for item in sorted(set(old_plan) & set(new_plan))
                if old_plan[item] != new_plan[item]
            ]
        )
        if planned:
            entries.append(
                DiffEntry(scope="task_plan", key=key, change=DiffChange.CHANGED, fields=planned)
            )
    return entries


async def reconcile_document(
    session: AsyncSession,
    tree: RoadmapTree,
    document: RoadmapDocument,
    prov: ResolvedProvenance,
) -> None:
    """Apply a reviewed proposal's neutral document to the persisted plan,
    matching phases and steps by `key`: a kept step keeps its id, its links and
    its dependency edges (rebuilt from the document); a step removed while it
    still has links is `409 step_has_links` (DEC-0084 §6). The document was
    validated by the caller (`roadmap_document_errors`)."""
    roadmap = tree.roadmap
    phases_by_key = {phase.key: phase for phase in tree.phases}
    steps_by_key = {step.key: step for step in tree.steps}
    document_phase_keys = {phase.key for phase in document.phases}
    document_step_keys = {step.key for phase in document.phases for step in phase.steps}

    for existing_step in tree.steps:
        if existing_step.key not in document_step_keys and tree.links.get(existing_step.id):
            raise step_has_links()

    for position, phase_in in enumerate(document.phases):
        phase = phases_by_key.get(phase_in.key)
        if phase is None:
            phase = RoadmapPhaseModel(
                roadmap_id=roadmap.id,
                key=phase_in.key,
                position=position,
                title=phase_in.title,
                objective=text_or_none(phase_in.objective),
                **prov.columns(),
            )
            session.add(phase)
            phases_by_key[phase_in.key] = phase
        else:
            phase.position = position
            phase.title = phase_in.title
            phase.objective = text_or_none(phase_in.objective)
            phase.version += 1
    await session.flush()

    plan_by_key: dict[str, RoadmapStepModel] = {}
    for phase_in in document.phases:
        phase = phases_by_key[phase_in.key]
        for position, step_in in enumerate(phase_in.steps):
            plan = [item.model_dump(mode="json") for item in step_in.tasks]
            step_model = steps_by_key.get(step_in.key)
            if step_model is None:
                step_model = RoadmapStepModel(
                    roadmap_id=roadmap.id,
                    phase_id=phase.id,
                    key=step_in.key,
                    position=position,
                    title=step_in.title,
                    objective=text_or_none(step_in.objective),
                    context=text_or_none(step_in.context),
                    instructions=text_or_none(step_in.instructions),
                    acceptance_criteria=list(step_in.acceptance_criteria),
                    criteria_checked=[],
                    notes=text_or_none(step_in.notes),
                    step_metadata=dict(step_in.metadata),
                    task_plan=plan,
                    **prov.columns(),
                )
                session.add(step_model)
                steps_by_key[step_in.key] = step_model
            else:
                if list(step_in.acceptance_criteria) != list(step_model.acceptance_criteria):
                    step_model.criteria_checked = []
                step_model.phase_id = phase.id
                step_model.position = position
                step_model.title = step_in.title
                step_model.objective = text_or_none(step_in.objective)
                step_model.context = text_or_none(step_in.context)
                step_model.instructions = text_or_none(step_in.instructions)
                step_model.acceptance_criteria = list(step_in.acceptance_criteria)
                step_model.notes = text_or_none(step_in.notes)
                step_model.step_metadata = dict(step_in.metadata)
                step_model.task_plan = plan
                step_model.version += 1
            plan_by_key[step_in.key] = step_model
    await session.flush()

    for key, step_row in steps_by_key.items():
        if key not in document_step_keys:
            await session.delete(step_row)
    for key, phase in phases_by_key.items():
        if key not in document_phase_keys:
            await session.delete(phase)
    await session.flush()

    await session.execute(
        delete(RoadmapStepDependencyModel).where(
            RoadmapStepDependencyModel.roadmap_id == roadmap.id
        )
    )
    await session.flush()
    for phase_in in document.phases:
        for step_in in phase_in.steps:
            for dependency in step_in.depends_on:
                session.add(
                    RoadmapStepDependencyModel(
                        step_id=plan_by_key[step_in.key].id,
                        depends_on_step_id=plan_by_key[dependency].id,
                        roadmap_id=roadmap.id,
                    )
                )
    await session.flush()


def text_or_none(value: str | None) -> str | None:
    return value or None


@dataclass(frozen=True)
class PendingEvent:
    event_type: EventType
    payload: dict[str, object]


def updated_event(roadmap: RoadmapModel, entity: str, key: str | None = None) -> PendingEvent:
    payload: dict[str, object] = {
        "roadmap_id": str(roadmap.id),
        "revision_no": roadmap.revision_no,
        "status": roadmap.status,
        "entity": entity,
    }
    if key is not None:
        payload["key"] = key
    return PendingEvent(EventType.ROADMAP_UPDATED, payload)


async def content_changed(
    session: AsyncSession,
    roadmap: RoadmapModel,
    prov: ResolvedProvenance,
    entity: str,
    key: str | None = None,
) -> PendingEvent:
    """Bookkeeping of an applied plan-content change: roadmap version bump and,
    on an `active` roadmap, a snapshot revision."""
    roadmap.version += 1
    if roadmap.status == RoadmapStatus.ACTIVE.value:
        await record_snapshot(session, roadmap, prov)
    return updated_event(roadmap, entity, key)


async def finish_result(
    session: AsyncSession,
    principal: Principal,
    roadmap: RoadmapModel,
    prov: ResolvedProvenance,
    pending: list[PendingEvent],
) -> None:
    """Stage the unit of work's events in the same transaction, commit once (state
    and audit trail become durable atomically: a failure leaves neither), then
    fan the committed events out to the realtime stream."""
    staged = [
        await events_service.stage_event(
            session,
            EventCreate(
                event_id=uuid.uuid4(),
                event_type=item.event_type,
                project_id=roadmap.project_id,
                machine_id=principal.machine.id,
                actor_type=prov.actor_type,  # type: ignore[arg-type]
                actor_id=prov.actor_id,
                client_timestamp=datetime.now(UTC),
                payload=item.payload,
            ),
        )
        for item in pending
    ]
    await session.commit()
    for event in staged:
        await session.refresh(event)
        events_service.publish_event(event)


async def finish(
    session: AsyncSession,
    principal: Principal,
    roadmap: RoadmapModel,
    prov: ResolvedProvenance,
    pending: list[PendingEvent],
) -> Roadmap:
    """`finish_result`, then the resulting roadmap (carries the new versions)."""
    await finish_result(session, principal, roadmap, prov, pending)
    await session.refresh(roadmap)
    return await read_roadmap(session, roadmap)
