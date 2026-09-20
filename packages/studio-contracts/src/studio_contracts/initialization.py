"""Project initialization contracts (Roadmaps P5, DEC-0084/DEC-0087).

A *project initialization* is a single, neutral, agent-authored plan that one
human <-> agent alignment produces: the project itself, an **optional**
roadmap, a task plan, the Library resources the project should pin, and the
generic runtime choices its agents should use. Studio OS never decides any of
this on the agent's behalf: it validates a structured plan and applies it
idempotently (DEC-0084 §9 R1).

The roadmap is deliberately optional. Every combination is valid — project
alone, project + tasks, project + resources, project + roadmap + tasks — and
"no roadmap" is a perfectly normal state, never an error.

Nothing here knows a provider, a model or a harness: bindings reuse the
existing P6 `RuntimeTarget` (open references, never a vendor catalog), and no
field of this module names one. The plan describes Studio OS concepts only;
adapters and harnesses stay outside the core.

Frozen by P5: additive-only. A breaking change bumps `INITIALIZATION_FORMAT`
and goes through reconciliation (skill `contract-change`).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.common import ContractModel, IdempotentCreate
from studio_contracts.library import LibraryKind, LibraryScope
from studio_contracts.roadmaps import (
    MAX_CONTEXT,
    MAX_TITLE,
    Key,
    Provenance,
    RoadmapDocument,
    RoadmapValidationReason,
    WriteProvenance,
    roadmap_document_errors,
)
from studio_contracts.runtime import RuntimeLevel, RuntimeTarget

INITIALIZATION_FORMAT = "studio.initialization/v1"
"""Neutral plan format tag. Additive fields stay in v1; a reader older than the
writer rejects explicitly (`extra="forbid"`) rather than silently truncating."""

# --- bounds: every free-text and collection field is bounded ------------------
MAX_INITIALIZATION_TASKS = 500
MAX_INITIALIZATION_RESOURCES = 50
MAX_INITIALIZATION_BINDINGS = 50
MAX_STABLE_KEY = 200


class InitializationMode(StrEnum):
    """The human gate the agent requests. The server never chooses it.

    `draft` applies everything directly (a human-authored plan). `proposed`
    submits the roadmap for human validation (`roadmap.status=proposed`)
    instead of leaving it a free draft; standalone tasks are still created —
    they are ordinary units of work, there is no "task proposal" concept.
    """

    DRAFT = "draft"
    PROPOSED = "proposed"


class InitializationSection(StrEnum):
    PROJECT = "project"
    ROADMAP = "roadmap"
    TASKS = "tasks"
    RESOURCES = "resources"
    BINDINGS = "bindings"


class InitializationActionKind(StrEnum):
    """Same vocabulary as roadmap hydration (`create`/`reuse`/`skip`), applied
    to the whole plan: `create` allocates a new row, `reuse` finds an existing
    one (replay-safe), `skip` deliberately does nothing (optional item absent,
    or the section is empty)."""

    CREATE = "create"
    REUSE = "reuse"
    SKIP = "skip"


class InitializationReason(StrEnum):
    PROJECT_ALREADY_EXISTS = "project_already_exists"
    ROADMAP_ALREADY_EXISTS = "roadmap_already_exists"
    TASK_ALREADY_EXISTS = "task_already_exists"
    RESOURCE_OPTIONAL_MISSING = "resource_optional_missing"
    RESOURCE_REQUIRED_MISSING = "resource_required_missing"
    RESOURCE_ALREADY_ATTACHED = "resource_already_attached"
    BINDING_ALREADY_SET = "binding_already_set"
    BINDING_UNAVAILABLE = "binding_unavailable"
    NO_ROADMAP = "no_roadmap"
    NO_TASKS = "no_tasks"
    NO_RESOURCES = "no_resources"
    NO_BINDINGS = "no_bindings"


class InitializationProblemCode(StrEnum):
    """Closed vocabulary. `*_NOT_FOUND`/`*_FORBIDDEN` come from probing the
    server state and are non-oracle: a private Library resource the caller
    cannot see is reported as not found, never as forbidden."""

    DUPLICATE_TASK_KEY = "duplicate_task_key"
    DUPLICATE_RESOURCE_REF = "duplicate_resource_ref"
    DUPLICATE_BINDING = "duplicate_binding"
    UNKNOWN_ROADMAP_STEP = "unknown_roadmap_step"
    ROADMAP_STEP_WITHOUT_ROADMAP = "roadmap_step_without_roadmap"
    INVALID_ROADMAP = "invalid_roadmap"
    RESOURCE_NOT_FOUND = "resource_not_found"
    BINDING_TARGET_NOT_FOUND = "binding_target_not_found"
    BINDING_INCOMPATIBLE = "binding_incompatible"
    LIMIT_EXCEEDED = "limit_exceeded"


# --- plan ---------------------------------------------------------------------
class InitializationProjectSpec(ContractModel):
    """The project to reuse (by `slug`) or create. No metadata column exists
    on Project (DEC-0084 §1) so none is invented here."""

    slug: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=MAX_TITLE)
    description: str | None = Field(default=None, max_length=MAX_CONTEXT)


class InitializationTask(ContractModel):
    """A standalone task the plan asks for. `key` is a plan-local stable
    identifier (error reporting, duplicate detection), never persisted;
    replay-safety comes from the task `title` within the project (an existing
    task with the same title is `reused`, never duplicated). An optional
    `roadmap_step_key` links the task to a step of the plan's roadmap (the
    link is created through the roadmap link service, same project)."""

    key: Key
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    description: str | None = Field(default=None, max_length=MAX_CONTEXT)
    roadmap_step_key: Key | None = None


class InitializationResourceRef(ContractModel):
    """A Library definition the project should pin (project lock). `version`
    pins a version; omitted means the active one. `required=False` turns a
    missing definition into a reported `skip` instead of a blocking problem —
    that is how a plan degrades gracefully on a fresh studio."""

    kind: LibraryKind
    stable_key: str = Field(min_length=1, max_length=MAX_STABLE_KEY)
    scope: LibraryScope | None = None
    version: int | None = Field(default=None, ge=1)
    required: bool = True


class InitializationBindingRef(ContractModel):
    """A generic runtime choice for one logical `(kind, stable_key)`
    definition, without `project_id` (the project is created/applied in the
    same operation, so the server fills it). `session` is never persistable
    and is rejected here; it belongs to a single resolve call."""

    level: RuntimeLevel
    target_kind: LibraryKind
    target_stable_key: str = Field(min_length=1, max_length=MAX_STABLE_KEY)
    target: RuntimeTarget

    @model_validator(mode="after")
    def _persistable_level(self) -> InitializationBindingRef:
        if self.level is RuntimeLevel.SESSION:
            raise ValueError("session runtime level is ephemeral and cannot be part of a plan")
        return self


class ProjectInitializationPlan(ContractModel):
    """The whole neutral plan. `roadmap` is optional by design: a project with
    no roadmap is the common case and must never be blocked by its absence."""

    format: Literal["studio.initialization/v1"] = "studio.initialization/v1"
    mode: InitializationMode = InitializationMode.DRAFT
    project: InitializationProjectSpec
    roadmap: RoadmapDocument | None = None
    tasks: list[InitializationTask] = Field(
        default_factory=list, max_length=MAX_INITIALIZATION_TASKS
    )
    resources: list[InitializationResourceRef] = Field(
        default_factory=list, max_length=MAX_INITIALIZATION_RESOURCES
    )
    bindings: list[InitializationBindingRef] = Field(
        default_factory=list, max_length=MAX_INITIALIZATION_BINDINGS
    )


class ProjectInitializationRequest(IdempotentCreate):
    """Apply payload: the plan plus the client-declared part of provenance.
    The server derives the rest from the authenticated `Principal` (actor =
    machine owner unless `agent_id` is set; an `agent_id` not attached to the
    machine is `409 actor_not_owned`). Preview takes the bare plan."""

    plan: ProjectInitializationPlan
    provenance: WriteProvenance = Field(default_factory=WriteProvenance)


# --- results ------------------------------------------------------------------
class InitializationAction(ContractModel):
    section: InitializationSection
    key: str
    action: InitializationActionKind
    reason: InitializationReason | None = None
    resource_id: UUID | None = None


class InitializationSummary(ContractModel):
    """The `created/reused/skipped` roll-up that makes a preview and a replay
    readable at a glance."""

    created: int = 0
    reused: int = 0
    skipped: int = 0


class InitializationProblem(ContractModel):
    """One structured problem. `blocking=True` (the default) means the plan is
    not applicable as-is: preview answers `applicable=False` and apply refuses
    before writing anything. `blocking=False` describes an intentionally
    skipped optional item and is reported without failing the apply."""

    section: InitializationSection
    code: InitializationProblemCode
    key: str | None = None
    field: str | None = None
    blocking: bool = True
    message: str | None = None


class InitializationPreview(ContractModel):
    """Read-only outcome: exactly what would happen, with no side effect. It
    is valid and applicable even when the project does not exist yet."""

    valid: bool
    applicable: bool
    roadmap_present: bool
    roadmap_status: Literal["draft", "proposed"] | None = None
    actions: list[InitializationAction] = Field(default_factory=list)
    summary: InitializationSummary = Field(default_factory=InitializationSummary)
    problems: list[InitializationProblem] = Field(default_factory=list)


class InitializationResult(ContractModel):
    """Applied outcome. `project_id` is always set (reused or created) and
    `roadmap_id` only when the plan carried one. The same summary semantics as
    preview, so a replay that reuses everything reports `created=0`."""

    applied: bool
    project_id: UUID
    roadmap_id: UUID | None = None
    roadmap_status: Literal["draft", "proposed"] | None = None
    actions: list[InitializationAction] = Field(default_factory=list)
    summary: InitializationSummary = Field(default_factory=InitializationSummary)
    problems: list[InitializationProblem] = Field(default_factory=list)
    provenance: Provenance


# --- pure validation (plan-internal, no server state) -------------------------
def _problem(
    section: InitializationSection,
    code: InitializationProblemCode,
    *,
    key: str | None = None,
    field: str | None = None,
    blocking: bool = True,
    message: str | None = None,
) -> InitializationProblem:
    return InitializationProblem(
        section=section, code=code, key=key, field=field, blocking=blocking, message=message
    )


def initialization_plan_problems(plan: ProjectInitializationPlan) -> list[InitializationProblem]:
    """Validate the plan against itself only — never an existence oracle.
    Returns every problem (not just the first) so one round-trip shows the
    whole picture; empty means structurally sound. Server-state checks
    (Library visibility, runtime compatibility) run separately during
    preview/apply through the target port."""
    problems: list[InitializationProblem] = []

    if plan.roadmap is not None:
        for error in roadmap_document_errors(plan.roadmap):
            reason = error.get("reason", RoadmapValidationReason.LIMIT_EXCEEDED.value)
            problems.append(
                _problem(
                    InitializationSection.ROADMAP,
                    InitializationProblemCode.INVALID_ROADMAP,
                    field=error.get("field"),
                    message=reason,
                )
            )

    step_keys = {
        step.key
        for phase in (plan.roadmap.phases if plan.roadmap is not None else [])
        for step in phase.steps
    }

    task_keys: set[str] = set()
    for task in plan.tasks:
        if task.key in task_keys:
            problems.append(
                _problem(
                    InitializationSection.TASKS,
                    InitializationProblemCode.DUPLICATE_TASK_KEY,
                    key=task.key,
                )
            )
        task_keys.add(task.key)
        if task.roadmap_step_key is None:
            continue
        if plan.roadmap is None:
            problems.append(
                _problem(
                    InitializationSection.TASKS,
                    InitializationProblemCode.ROADMAP_STEP_WITHOUT_ROADMAP,
                    key=task.key,
                )
            )
        elif task.roadmap_step_key not in step_keys:
            problems.append(
                _problem(
                    InitializationSection.TASKS,
                    InitializationProblemCode.UNKNOWN_ROADMAP_STEP,
                    key=task.key,
                )
            )

    resource_refs: set[tuple[str, str, str]] = set()
    for ref in plan.resources:
        identity = (ref.kind.value, ref.stable_key, (ref.scope.value if ref.scope else ""))
        if identity in resource_refs:
            problems.append(
                _problem(
                    InitializationSection.RESOURCES,
                    InitializationProblemCode.DUPLICATE_RESOURCE_REF,
                    key=ref.stable_key,
                )
            )
        resource_refs.add(identity)

    binding_refs: set[tuple[str, str, str]] = set()
    for binding in plan.bindings:
        identity = (binding.level.value, binding.target_kind.value, binding.target_stable_key)
        if identity in binding_refs:
            problems.append(
                _problem(
                    InitializationSection.BINDINGS,
                    InitializationProblemCode.DUPLICATE_BINDING,
                    key=binding.target_stable_key,
                )
            )
        binding_refs.add(identity)

    return problems


def count_actions(actions: list[InitializationAction]) -> InitializationSummary:
    return InitializationSummary(
        created=sum(1 for a in actions if a.action is InitializationActionKind.CREATE),
        reused=sum(1 for a in actions if a.action is InitializationActionKind.REUSE),
        skipped=sum(1 for a in actions if a.action is InitializationActionKind.SKIP),
    )


def blocking_problems(problems: list[InitializationProblem]) -> list[InitializationProblem]:
    return [problem for problem in problems if problem.blocking]
