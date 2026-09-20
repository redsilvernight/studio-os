"""Roadmap contracts (Roadmaps P1, DEC-0084/DEC-0085).

A Roadmap is a project-scoped *plan* (Roadmap -> Phase -> Step); Tasks stay the
units of work and the only source of truth for work status. This module owns:

- the neutral, versioned import/export document (`RoadmapDocument`) shared by
  the API, MCP, the initialization plan and the Dashboard fixtures;
- the read/write models of the canonical HTTP surface (P3);
- the closed lifecycle (`ROADMAP_TRANSITIONS`) and its authority rule;
- pure, deterministic rules reused by every lane so there is exactly one
  implementation of them: document validation, cycle detection, step-state
  derivation, progress, availability;
- the structured error vocabulary.

Nothing here knows a provider, a model or a harness (DEC-0084 §2.7):
`extra="forbid"` on every model rejects such fields, and provenance only
carries ids that join to the existing `Agent` row.

Frozen by P1: additions are additive-only; a breaking change of the document
bumps `ROADMAP_FORMAT` (`studio.roadmap/v2`) and goes through reconciliation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, ValidationError, model_validator

from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel

ROADMAP_FORMAT = "studio.roadmap/v1"
"""Neutral document format tag. Additive fields stay in v1 (readers ignore
nothing: `extra="forbid"` means a *writer* newer than the reader is rejected
explicitly rather than silently truncated)."""

KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
"""Stable local identifier of a phase/step (`P0`, `P0.1`, `setup-db`).
Unique within a roadmap; ASCII, no path separator, no whitespace."""

# --- bounds (P1.4): every free-text and collection field is bounded ---------
MAX_TITLE = 200
MAX_OBJECTIVE = 2000
MAX_CONTEXT = 4000
MAX_INSTRUCTIONS = 8000
MAX_NOTES = 4000
MAX_COMMENT = 2000
MAX_CRITERIA = 20
MAX_CRITERION_LENGTH = 500
MAX_PHASES = 30
MAX_STEPS_PER_PHASE = 50
MAX_STEPS = 300
MAX_DEPENDENCIES_PER_STEP = 20
MAX_TASK_PLAN_PER_STEP = 20
MAX_TASK_PLAN = 500
MAX_LINKS_PER_STEP = 50
MAX_METADATA_KEYS = 20
MAX_METADATA_KEY_LENGTH = 64
MAX_METADATA_VALUE_LENGTH = 500
MAX_HYDRATION_STEP_KEYS = 300

MetadataValue = str | int | float | bool | None


def _check_metadata(value: dict[str, MetadataValue]) -> dict[str, MetadataValue]:
    if len(value) > MAX_METADATA_KEYS:
        raise ValueError(f"metadata allows at most {MAX_METADATA_KEYS} keys")
    for key, item in value.items():
        if not key or len(key) > MAX_METADATA_KEY_LENGTH:
            raise ValueError(f"metadata keys must be 1..{MAX_METADATA_KEY_LENGTH} characters")
        if isinstance(item, str) and len(item) > MAX_METADATA_VALUE_LENGTH:
            raise ValueError(f"metadata string values allow at most {MAX_METADATA_VALUE_LENGTH}")
    return value


BoundedMetadata = Annotated[dict[str, MetadataValue], AfterValidator(_check_metadata)]
"""Flat, bounded, JSON-scalar-only metadata. No nesting, no secrets by
contract (the export never adds any); the server never interprets it."""

Key = Annotated[str, Field(pattern=KEY_PATTERN)]
Criterion = Annotated[str, Field(min_length=1, max_length=MAX_CRITERION_LENGTH)]


# --- vocabularies -------------------------------------------------------------
class RoadmapStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class RoadmapOrigin(StrEnum):
    """How content entered Studio OS. Self-declared by the writer: a workflow
    guard, not a security boundary; the boundary is the role."""

    MANUAL = "manual"
    AI_PROPOSAL = "ai_proposal"
    IMPORT = "import"


class StepState(StrEnum):
    """Derived, never stored (except through `StepStateOverride`)."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    SKIPPED = "skipped"


class StepStateOverride(StrEnum):
    """The only stored step state: a manual milestone (`done`, e.g. a step
    with no Task) or an explicit exclusion (`skipped`)."""

    DONE = "done"
    SKIPPED = "skipped"


class TaskStatusValue(StrEnum):
    """Mirror of `TaskStatus` used for derivation, kept local so this module
    depends on no other domain contract."""

    CREATED = "created"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class RevisionKind(StrEnum):
    PROPOSAL = "proposal"
    SNAPSHOT = "snapshot"
    REVIEW = "review"


class RevisionStatus(StrEnum):
    """Proposal revisions only; `snapshot`/`review` rows carry no status."""

    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


# --- lifecycle (P0.5, DEC-0084 §5) -------------------------------------------
class RoadmapTransition(StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"
    ACTIVATE = "activate"
    COMPLETE = "complete"
    REOPEN = "reopen"
    ARCHIVE = "archive"


ROADMAP_TRANSITIONS: dict[tuple[RoadmapStatus, RoadmapTransition], RoadmapStatus] = {
    (RoadmapStatus.DRAFT, RoadmapTransition.SUBMIT): RoadmapStatus.PROPOSED,
    (RoadmapStatus.DRAFT, RoadmapTransition.ACTIVATE): RoadmapStatus.ACTIVE,
    (RoadmapStatus.DRAFT, RoadmapTransition.ARCHIVE): RoadmapStatus.ARCHIVED,
    (RoadmapStatus.PROPOSED, RoadmapTransition.APPROVE): RoadmapStatus.ACTIVE,
    (RoadmapStatus.PROPOSED, RoadmapTransition.REQUEST_CHANGES): RoadmapStatus.DRAFT,
    (RoadmapStatus.PROPOSED, RoadmapTransition.REJECT): RoadmapStatus.ARCHIVED,
    (RoadmapStatus.ACTIVE, RoadmapTransition.COMPLETE): RoadmapStatus.COMPLETED,
    (RoadmapStatus.ACTIVE, RoadmapTransition.ARCHIVE): RoadmapStatus.ARCHIVED,
    (RoadmapStatus.COMPLETED, RoadmapTransition.REOPEN): RoadmapStatus.ACTIVE,
    (RoadmapStatus.COMPLETED, RoadmapTransition.ARCHIVE): RoadmapStatus.ARCHIVED,
}
"""Closed table; any pair absent is `409 invalid_state`. `archived` is
terminal in v1. Re-applying `activate` to an already-active roadmap is a
successful no-op handled by the service, not a table entry."""

_WRITER_TRANSITIONS = {
    (RoadmapStatus.DRAFT, RoadmapTransition.SUBMIT),
    (RoadmapStatus.DRAFT, RoadmapTransition.ARCHIVE),
}
TRANSITIONS_REQUIRING_COMMENT = frozenset(
    {RoadmapTransition.REQUEST_CHANGES, RoadmapTransition.REJECT, RoadmapTransition.REOPEN}
)


def transition_target(status: RoadmapStatus, transition: RoadmapTransition) -> RoadmapStatus | None:
    return ROADMAP_TRANSITIONS.get((status, transition))


def transition_requires_provision(status: RoadmapStatus, transition: RoadmapTransition) -> bool:
    """`True` when the transition needs `ensure_can_provision`
    (`admin`/`developer`); `False` when any writer may perform it
    (`draft -> proposed`, `draft -> archived`). The `agent` role can therefore
    never activate, approve, reject, complete or archive an approved plan."""
    return (status, transition) not in _WRITER_TRANSITIONS


# --- provenance (P0.7, DEC-0084 §7) --------------------------------------------
class WriteProvenance(ContractModel):
    """Client-declared part of provenance. The server derives the rest from
    the authenticated `Principal` (actor = machine owner unless `agent_id` is
    set; an `agent_id` not attached to the machine -> `409 actor_not_owned`).
    Whether a write *is* an agent write is decided by `is_agent_write`, never
    by `origin` alone: a declared `manual` origin cannot downgrade it."""

    origin: RoadmapOrigin = RoadmapOrigin.MANUAL
    agent_id: UUID | None = None


class Provenance(ContractModel):
    """Read-side provenance. No harness/provider/model: joinable through
    `agent_id` -> `Agent` only."""

    origin: RoadmapOrigin
    actor_type: Literal["user", "agent"]
    actor_id: UUID
    agent_id: UUID | None = None
    machine_id: UUID | None = None
    at: datetime


def is_agent_write(role_is_agent: bool, provenance: WriteProvenance) -> bool:
    """A write is an agent write when the authenticated role is `agent`, or an
    `agent_id` is declared, or the origin is `ai_proposal`. Any one suffices;
    `origin=manual` never overrides the other two. On an `active` roadmap an
    agent *content* write becomes a pending proposal (DEC-0084 §6); this is a
    workflow guard, the security boundary stays the role
    (`transition_requires_provision`)."""
    return (
        role_is_agent
        or provenance.agent_id is not None
        or provenance.origin is RoadmapOrigin.AI_PROPOSAL
    )


class WriteKind(StrEnum):
    CONTENT = "content"
    PROGRESS = "progress"
    LINK = "link"
    HYDRATION_APPLY = "hydration_apply"
    PROPOSAL = "proposal"


ALLOWED_WRITES: dict[RoadmapStatus, frozenset[WriteKind]] = {
    RoadmapStatus.DRAFT: frozenset({WriteKind.CONTENT, WriteKind.PROGRESS, WriteKind.LINK}),
    RoadmapStatus.PROPOSED: frozenset(),
    RoadmapStatus.ACTIVE: frozenset(
        {
            WriteKind.CONTENT,
            WriteKind.PROGRESS,
            WriteKind.LINK,
            WriteKind.HYDRATION_APPLY,
            WriteKind.PROPOSAL,
        }
    ),
    RoadmapStatus.COMPLETED: frozenset(),
    RoadmapStatus.ARCHIVED: frozenset(),
}
"""Which writes each status accepts; anything else is `409 invalid_state`.
`proposed` is frozen for review (edit = `request_changes` first), `completed`
and `archived` are read-only (`reopen` first). Lifecycle transitions are
governed by `ROADMAP_TRANSITIONS`, not by this table."""


def write_allowed(status: RoadmapStatus, kind: WriteKind) -> bool:
    return kind in ALLOWED_WRITES[status]


# --- neutral document (P1.1, P1.4, P1.5, P1.6) --------------------------------
class TaskPlanItem(ContractModel):
    """A Task the step *would* create at hydration. `hydration_key` is unique
    within its step and is what makes hydration replay-safe: a step already
    linked to a Task with the same `hydration_key` is `reused`, never
    duplicated, even under a fresh `Idempotency-Key`."""

    hydration_key: Key
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    description: str | None = Field(default=None, max_length=MAX_CONTEXT)


class StepContent(ContractModel):
    key: Key
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    objective: str | None = Field(default=None, max_length=MAX_OBJECTIVE)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT)
    instructions: str | None = Field(default=None, max_length=MAX_INSTRUCTIONS)
    acceptance_criteria: list[Criterion] = Field(default_factory=list, max_length=MAX_CRITERIA)
    notes: str | None = Field(default=None, max_length=MAX_NOTES)
    metadata: BoundedMetadata = Field(default_factory=dict)
    depends_on: list[Key] = Field(default_factory=list, max_length=MAX_DEPENDENCIES_PER_STEP)
    tasks: list[TaskPlanItem] = Field(default_factory=list, max_length=MAX_TASK_PLAN_PER_STEP)


class PhaseContent(ContractModel):
    key: Key
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    objective: str | None = Field(default=None, max_length=MAX_OBJECTIVE)
    steps: list[StepContent] = Field(default_factory=list, max_length=MAX_STEPS_PER_PHASE)


class RoadmapDocument(ContractModel):
    """The neutral, versioned, portable roadmap: what import accepts, export
    returns and a proposal carries. List order *is* the stable order. It holds
    the plan only — no ids, no Task links to existing Tasks, no status, no
    secrets, no provenance — so it moves between projects and tools intact."""

    format: Literal["studio.roadmap/v1"] = "studio.roadmap/v1"
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    objective: str | None = Field(default=None, max_length=MAX_OBJECTIVE)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT)
    metadata: BoundedMetadata = Field(default_factory=dict)
    phases: list[PhaseContent] = Field(default_factory=list, max_length=MAX_PHASES)
    exported_at: datetime | None = None
    revision_no: int | None = None
    """`exported_at`/`revision_no` are informational export stamps: accepted on
    import, never interpreted, never stored as the new roadmap's revision."""


class RoadmapValidationReason(StrEnum):
    """Closed reasons of `422 invalid_roadmap`; each describes the caller's
    own submitted payload (never an existence oracle)."""

    DUPLICATE_PHASE_KEY = "duplicate_phase_key"
    DUPLICATE_STEP_KEY = "duplicate_step_key"
    DUPLICATE_HYDRATION_KEY = "duplicate_hydration_key"
    UNKNOWN_DEPENDENCY = "unknown_dependency"
    SELF_DEPENDENCY = "self_dependency"
    DEPENDENCY_CYCLE = "dependency_cycle"
    DUPLICATE_DEPENDENCY = "duplicate_dependency"
    LIMIT_EXCEEDED = "limit_exceeded"
    INVALID_REORDER = "invalid_reorder"


def _error(reason: RoadmapValidationReason, field: str) -> dict[str, str]:
    return {"reason": reason.value, "field": field}


def find_dependency_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """Anti-cycle rule (P1.2), shared by document validation (422) and edits
    of a persisted graph (409 `dependency_cycle`). `edges[step]` lists the
    steps it depends on. Deterministic (sorted traversal, iterative — no
    recursion limit): returns one cycle as `[a, b, ..., a]` or `None`."""
    color: dict[str, int] = {}
    for start in sorted(edges):
        if color.get(start, 0) != 0:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = []
        while stack:
            node, index = stack.pop()
            if index == 0:
                if color.get(node, 0) == 2:
                    continue
                color[node] = 1
                path.append(node)
            targets = sorted(edges.get(node, []))
            if index < len(targets):
                stack.append((node, index + 1))
                target = targets[index]
                state = color.get(target, 0)
                if state == 1:
                    return [*path[path.index(target) :], target]
                if state == 0 and target in edges:
                    stack.append((target, 0))
            else:
                color[node] = 2
                path.pop()
    return None


def roadmap_document_errors(document: RoadmapDocument) -> list[dict[str, str]]:
    """Semantic validation of a `RoadmapDocument`, on top of its schema.
    Pure and deterministic (input order never changes the verdict's *reason*
    ordering): returns the first failure as `[{reason, field}]`, empty when
    valid. Schema-shape failures stay the framework's own 422."""
    phase_keys: set[str] = set()
    step_keys: set[str] = set()
    total_steps = 0
    total_tasks = 0
    for phase in document.phases:
        if phase.key in phase_keys:
            return [_error(RoadmapValidationReason.DUPLICATE_PHASE_KEY, f"phases.{phase.key}")]
        phase_keys.add(phase.key)
        for step in phase.steps:
            if step.key in step_keys:
                return [_error(RoadmapValidationReason.DUPLICATE_STEP_KEY, f"steps.{step.key}")]
            step_keys.add(step.key)
            total_steps += 1
            total_tasks += len(step.tasks)
            hydration_keys = [item.hydration_key for item in step.tasks]
            if len(set(hydration_keys)) != len(hydration_keys):
                return [
                    _error(
                        RoadmapValidationReason.DUPLICATE_HYDRATION_KEY, f"steps.{step.key}.tasks"
                    )
                ]
    if total_steps > MAX_STEPS or total_tasks > MAX_TASK_PLAN:
        return [_error(RoadmapValidationReason.LIMIT_EXCEEDED, "steps")]

    edges: dict[str, list[str]] = {}
    for phase in document.phases:
        for step in phase.steps:
            if len(set(step.depends_on)) != len(step.depends_on):
                return [
                    _error(
                        RoadmapValidationReason.DUPLICATE_DEPENDENCY,
                        f"steps.{step.key}.depends_on",
                    )
                ]
            for dependency in step.depends_on:
                if dependency == step.key:
                    return [
                        _error(
                            RoadmapValidationReason.SELF_DEPENDENCY,
                            f"steps.{step.key}.depends_on",
                        )
                    ]
                if dependency not in step_keys:
                    return [
                        _error(
                            RoadmapValidationReason.UNKNOWN_DEPENDENCY,
                            f"steps.{step.key}.depends_on",
                        )
                    ]
            edges[step.key] = list(step.depends_on)
    if find_dependency_cycle(edges) is not None:
        return [_error(RoadmapValidationReason.DEPENDENCY_CYCLE, "steps")]
    return []


def parse_roadmap_document(raw: dict[str, object]) -> tuple[RoadmapDocument | None, list[str]]:
    """Import helper: `(document, [])` or `(None, [json paths that failed])`."""
    try:
        return RoadmapDocument.model_validate(raw), []
    except ValidationError as error:
        return None, [".".join(str(part) for part in item["loc"]) for item in error.errors()]


# --- derived state and progress (P0.4, DEC-0084 §4) ---------------------------
def derive_step_state(
    override: StepStateOverride | None, task_statuses: list[TaskStatusValue]
) -> StepState:
    """The single derivation of a step's state. Override wins; otherwise from
    linked Task statuses: all `completed` -> done, any `blocked` -> blocked,
    any `in_progress` -> in_progress, else not_started (also when no Task)."""
    if override is StepStateOverride.SKIPPED:
        return StepState.SKIPPED
    if override is StepStateOverride.DONE:
        return StepState.DONE
    if task_statuses and all(s is TaskStatusValue.COMPLETED for s in task_statuses):
        return StepState.DONE
    if any(s is TaskStatusValue.BLOCKED for s in task_statuses):
        return StepState.BLOCKED
    if any(s is TaskStatusValue.IN_PROGRESS for s in task_statuses):
        return StepState.IN_PROGRESS
    return StepState.NOT_STARTED


def waiting_on(depends_on: list[str], states: dict[str, StepState]) -> list[str]:
    """Dependencies not yet `done`/`skipped`, sorted. A step is `available`
    when it is neither `done` nor `skipped` and this list is empty."""
    return sorted(
        key for key in depends_on if states.get(key) not in (StepState.DONE, StepState.SKIPPED)
    )


class Progress(ContractModel):
    """`done / total` over non-skipped steps; `ratio` in [0, 1], `1.0` when
    there is nothing left to do (`total == 0`). Derived at read time, never
    persisted, so API, MCP and Dashboard cannot drift."""

    done: int = Field(ge=0)
    total: int = Field(ge=0)
    skipped: int = Field(ge=0)
    ratio: float = Field(ge=0.0, le=1.0)


def compute_progress(states: list[StepState]) -> Progress:
    skipped = sum(1 for s in states if s is StepState.SKIPPED)
    counted = [s for s in states if s is not StepState.SKIPPED]
    done = sum(1 for s in counted if s is StepState.DONE)
    total = len(counted)
    return Progress(
        done=done, total=total, skipped=skipped, ratio=1.0 if total == 0 else done / total
    )


class TaskProgress(ContractModel):
    completed: int = Field(ge=0)
    total: int = Field(ge=0)


# --- read models (P1.1) --------------------------------------------------------
class LinkedTask(ContractModel):
    task_id: UUID
    hydration_key: str | None = None
    origin: RoadmapOrigin = RoadmapOrigin.MANUAL


class Step(VersionedModel):
    id: UUID
    roadmap_id: UUID
    phase_id: UUID
    key: str
    position: int
    title: str
    objective: str | None = None
    context: str | None = None
    instructions: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    criteria_checked: list[int] = Field(default_factory=list)
    notes: str | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    tasks: list[TaskPlanItem] = Field(default_factory=list)
    linked_tasks: list[LinkedTask] = Field(default_factory=list)
    state_override: StepStateOverride | None = None
    state_override_reason: str | None = None
    state: StepState = StepState.NOT_STARTED
    available: bool = False
    waiting_on: list[str] = Field(default_factory=list)
    task_progress: TaskProgress = Field(default_factory=lambda: TaskProgress(completed=0, total=0))
    provenance: Provenance | None = None


class Phase(VersionedModel):
    id: UUID
    roadmap_id: UUID
    key: str
    position: int
    title: str
    objective: str | None = None
    progress: Progress
    steps: list[Step] = Field(default_factory=list)


class RoadmapSummary(VersionedModel):
    id: UUID
    project_id: UUID
    title: str
    objective: str | None = None
    status: RoadmapStatus
    revision_no: int
    approved_revision_no: int | None = None
    progress: Progress
    current_step_key: str | None = None
    provenance: Provenance | None = None


class Roadmap(RoadmapSummary):
    """Detail view: `phases` are in stable order; `current_step_key` is the
    first `available` step in plan order (deterministic)."""

    context: str | None = None
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    phases: list[Phase] = Field(default_factory=list)


# --- write models ---------------------------------------------------------------
class RoadmapCreate(IdempotentCreate):
    """Empty draft skeleton. A full plan goes through `RoadmapImport`."""

    project_id: UUID
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    objective: str | None = Field(default=None, max_length=MAX_OBJECTIVE)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT)
    metadata: BoundedMetadata = Field(default_factory=dict)
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class RoadmapImport(IdempotentCreate):
    """Create a `draft` from a full document (import, AI proposal, project
    initialization). `submit=True` also moves it to `proposed` in the same
    atomic operation (the proposal flow). Never creates Tasks."""

    project_id: UUID
    document: RoadmapDocument
    submit: bool = False
    provenance: WriteProvenance = Field(
        default_factory=lambda: WriteProvenance(origin=RoadmapOrigin.IMPORT)
    )


class RoadmapUpdate(ContractModel):
    """Content edit of the roadmap header (`PATCH`, `If-Match-Version`). PATCH
    semantics for every `*Update` model: an omitted or `null` field is left
    unchanged; an empty string clears an optional text field and `{}` clears
    `metadata`."""

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    objective: str | None = Field(default=None, max_length=MAX_OBJECTIVE)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT)
    metadata: BoundedMetadata | None = None
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class PhaseCreate(IdempotentCreate):
    key: Key
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    objective: str | None = Field(default=None, max_length=MAX_OBJECTIVE)
    expected_roadmap_version: int
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class PhaseUpdate(ContractModel):
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    objective: str | None = Field(default=None, max_length=MAX_OBJECTIVE)
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class StepCreate(IdempotentCreate):
    """Adds a step at the end of a phase; ordering afterwards goes through
    `Reorder`. Moving a step across phases is not supported in v1 (remove and
    add, or a proposal)."""

    content: StepContent
    expected_roadmap_version: int
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class StepUpdate(ContractModel):
    """Content edit (`PATCH`, `If-Match-Version` = step version). On an
    `active` roadmap a *content* edit that `is_agent_write` becomes a pending
    proposal instead of being applied. Editing `tasks` never modifies or
    deletes existing Tasks or links: a removed plan item leaves its link (and
    its `hydration_key`) in place, and re-adding it makes it `reuse` again.
    Editing `acceptance_criteria` clears the step's `criteria_checked`."""

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    objective: str | None = Field(default=None, max_length=MAX_OBJECTIVE)
    context: str | None = Field(default=None, max_length=MAX_CONTEXT)
    instructions: str | None = Field(default=None, max_length=MAX_INSTRUCTIONS)
    acceptance_criteria: list[Criterion] | None = Field(default=None, max_length=MAX_CRITERIA)
    metadata: BoundedMetadata | None = None
    tasks: list[TaskPlanItem] | None = Field(default=None, max_length=MAX_TASK_PLAN_PER_STEP)
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class StepProgressUpdate(ContractModel):
    """Bounded progress-type update, applied directly even when the writer
    carries an agent provenance (P4.5): override, notes, checked criteria. It
    never changes the plan's structure or content and creates no snapshot
    revision. `criteria_checked` is the complete list of checked indices into
    the step's `acceptance_criteria` (replaces the previous list)."""

    state_override: StepStateOverride | None = None
    clear_state_override: bool = False
    state_override_reason: str | None = Field(default=None, max_length=MAX_COMMENT)
    notes: str | None = Field(default=None, max_length=MAX_NOTES)
    criteria_checked: list[Annotated[int, Field(ge=0, lt=MAX_CRITERIA)]] | None = Field(
        default=None, max_length=MAX_CRITERIA
    )
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)

    @model_validator(mode="after")
    def _consistent(self) -> StepProgressUpdate:
        if self.criteria_checked is not None and len(set(self.criteria_checked)) != len(
            self.criteria_checked
        ):
            raise ValueError("criteria_checked must not repeat an index")
        if self.clear_state_override and self.state_override is not None:
            raise ValueError("clear_state_override excludes state_override")
        return self


class Reorder(ContractModel):
    """Atomic reorder: the complete ordered list of sibling keys. It must be
    a permutation of the current siblings (`422 invalid_roadmap`,
    `invalid_reorder`); the roadmap version is checked and bumped."""

    ordered_keys: list[Key] = Field(min_length=1, max_length=MAX_STEPS)
    expected_roadmap_version: int
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class DependencyChange(ContractModel):
    """Add or remove `step_key -> depends_on_key`. Adding an existing edge or
    removing an absent one is a successful no-op; a cycle is
    `409 dependency_cycle` with the offending path."""

    step_key: Key
    depends_on_key: Key
    expected_roadmap_version: int
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class LinkTask(IdempotentCreate):
    """Link an existing Task (same project, else `422 task_project_mismatch`)
    to a step. Linking twice is a successful no-op. Unlinking never touches
    the Task."""

    task_id: UUID
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class TransitionRequest(ContractModel):
    """Lifecycle change of a *roadmap* (`ROADMAP_TRANSITIONS`). `approve` here
    is the initial validation of a `proposed` roadmap; approving a revision
    proposal of an approved roadmap is `ProposalReview`. Both emit
    `roadmap.approved` / `roadmap.changes_requested` / `roadmap.rejected` with
    `payload.scope` = `roadmap` or `revision`."""

    transition: RoadmapTransition
    expected_version: int
    comment: str | None = Field(default=None, max_length=MAX_COMMENT)
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)

    @model_validator(mode="after")
    def _comment_required(self) -> TransitionRequest:
        if self.transition in TRANSITIONS_REQUIRING_COMMENT and not (self.comment or "").strip():
            raise ValueError(f"comment is required for transition {self.transition.value}")
        return self


# --- revisions and proposals (P0.6) ----------------------------------------------
class RoadmapRevision(ContractModel):
    id: UUID
    roadmap_id: UUID
    revision_no: int
    kind: RevisionKind
    status: RevisionStatus | None = None
    base_revision_no: int | None = None
    summary: str | None = None
    content: RoadmapDocument | None = None
    provenance: Provenance
    reviewed_by_user_id: UUID | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None


class RoadmapRevisionSummary(ContractModel):
    """Revision history row without the (possibly large) neutral document:
    what a list of revisions returns. The full `RoadmapRevision` (with
    `content`) is what a single-revision read returns."""

    id: UUID
    roadmap_id: UUID
    revision_no: int
    kind: RevisionKind
    status: RevisionStatus | None = None
    base_revision_no: int | None = None
    summary: str | None = None
    provenance: Provenance
    reviewed_by_user_id: UUID | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None


class ProposalCreate(IdempotentCreate):
    """A structured change to an approved roadmap. `base_revision_no` is the
    revision the author read; if it is no longer current when reviewed, the
    approval fails `409 base_revision_stale`."""

    base_revision_no: int
    document: RoadmapDocument
    summary: str | None = Field(default=None, max_length=MAX_COMMENT)
    provenance: WriteProvenance = Field(
        default_factory=lambda: WriteProvenance(origin=RoadmapOrigin.AI_PROPOSAL)
    )


class ProposalReview(ContractModel):
    decision: ReviewDecision
    expected_version: int
    comment: str | None = Field(default=None, max_length=MAX_COMMENT)

    @model_validator(mode="after")
    def _comment_required(self) -> ProposalReview:
        if self.decision is not ReviewDecision.APPROVE and not (self.comment or "").strip():
            raise ValueError(f"comment is required for decision {self.decision.value}")
        return self


class DiffChange(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class DiffEntry(ContractModel):
    """One line of the human-readable diff, computed at read time by matching
    phases/steps on `key`; never stored."""

    scope: Literal["roadmap", "phase", "step", "dependency", "task_plan"]
    key: str | None = None
    change: DiffChange
    fields: list[str] = Field(default_factory=list)


class RoadmapDiff(ContractModel):
    base_revision_no: int | None
    proposal_revision_no: int
    entries: list[DiffEntry] = Field(default_factory=list)


# --- hydration (P1.5) ---------------------------------------------------------------
class HydrationRequest(ContractModel):
    """Preview request: `step_keys=None` means every hydratable step. Works on
    any non-archived status so a plan can be inspected before validation; a
    non-`active` roadmap answers `applicable=False`. Writes nothing."""

    step_keys: list[Key] | None = Field(default=None, max_length=MAX_HYDRATION_STEP_KEYS)


class HydrationApplyRequest(HydrationRequest):
    """Apply request (`Idempotency-Key`). Requires an `active` roadmap
    (`409 invalid_state` otherwise) and the `expected_version` read at preview:
    a roadmap changed since then is `409 version_conflict`."""

    expected_version: int
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


class HydrationAction(StrEnum):
    """`create` a Task for an unlinked plan item; `reuse` the Task already
    linked under the same `hydration_key`; `skip` a step that is `done` or
    `skipped`. Hydration never modifies or deletes an existing Task."""

    CREATE = "create"
    REUSE = "reuse"
    SKIP = "skip"


class HydrationReason(StrEnum):
    STEP_DONE = "step_done"
    STEP_SKIPPED = "step_skipped"
    ROADMAP_NOT_ACTIVE = "roadmap_not_active"


class HydrationItem(ContractModel):
    step_key: str
    hydration_key: str
    action: HydrationAction
    title: str
    task_id: UUID | None = None
    reason: HydrationReason | None = None


class HydrationCounts(ContractModel):
    create: int = 0
    reuse: int = 0
    skip: int = 0


class HydrationResult(ContractModel):
    """Same shape for preview (`applied=False`, nothing written) and apply
    (`applied=True`). On apply, `create` items carry the new `task_id`.
    `applicable=False` (preview of a non-`active` roadmap) carries
    `not_applicable_reason`; apply never returns it (it fails instead)."""

    roadmap_id: UUID
    roadmap_version: int
    applied: bool
    applicable: bool = True
    not_applicable_reason: HydrationReason | None = None
    items: list[HydrationItem] = Field(default_factory=list)
    counts: HydrationCounts = Field(default_factory=HydrationCounts)


def count_hydration(items: list[HydrationItem]) -> HydrationCounts:
    actions = [item.action for item in items]
    return HydrationCounts(
        create=actions.count(HydrationAction.CREATE),
        reuse=actions.count(HydrationAction.REUSE),
        skip=actions.count(HydrationAction.SKIP),
    )


# --- structured errors (P1.7) ---------------------------------------------------------
class RoadmapErrorCode(StrEnum):
    """`error_code` values of `{"detail": {"error_code": ...}}` for Roadmap
    routes/tools. `version_conflict`, `forbidden` and the idempotency codes
    are the existing platform codes, reused unchanged."""

    NOT_FOUND = "not_found"  # 404
    REFERENCE_NOT_FOUND = "reference_not_found"  # 404 (task_id, step key)
    VERSION_CONFLICT = "version_conflict"  # 409 + server_version
    BASE_REVISION_STALE = "base_revision_stale"  # 409 + server_revision_no
    ACTIVE_ROADMAP_EXISTS = "active_roadmap_exists"  # 409
    INVALID_STATE = "invalid_state"  # 409 + status, transition
    DEPENDENCY_CYCLE = "dependency_cycle"  # 409 + path
    STEP_HAS_LINKS = "step_has_links"  # 409
    DUPLICATE_KEY = "duplicate_key"  # 409 + field
    IDEMPOTENCY_KEY_PAYLOAD_MISMATCH = "idempotency_key_payload_mismatch"  # 409 (existing)
    ACTOR_NOT_OWNED = "actor_not_owned"  # 409 (existing)
    FORBIDDEN = "forbidden"  # 403 (existing)
    INVALID_ROADMAP = "invalid_roadmap"  # 422 + reason, field
    TASK_PROJECT_MISMATCH = "task_project_mismatch"  # 422
    LIMIT_EXCEEDED = "limit_exceeded"  # 422 + limit


class RoadmapErrorDetail(ContractModel):
    """Typed view of `HTTPException.detail` for Roadmap errors; optional
    members appear only for the codes documented on `RoadmapErrorCode`."""

    error_code: RoadmapErrorCode
    message: str | None = None
    reason: str | None = None
    field: str | None = None
    server_version: int | None = None
    server_revision_no: int | None = None
    status: RoadmapStatus | None = None
    transition: RoadmapTransition | None = None
    path: list[str] | None = None
    limit: str | None = None


# --- context slice (consumed by P6) -----------------------------------------------------
class ContextStep(ContractModel):
    key: str
    title: str
    state: StepState
    available: bool
    waiting_on: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    linked_task_ids: list[UUID] = Field(default_factory=list)


class RoadmapContext(ContractModel):
    """Bounded roadmap slice for `studio_prepare_context` (P6): never the whole
    roadmap. Absent when the project has no `active` roadmap; then
    `draft_pending` alone signals unapproved drafts/proposals."""

    roadmap_id: UUID
    title: str
    progress: Progress
    current_phase_key: str | None = None
    current_step: ContextStep | None = None
    upcoming_steps: list[ContextStep] = Field(default_factory=list, max_length=5)
    blocking: list[str] = Field(default_factory=list)
    draft_pending: int = Field(default=0, ge=0)
