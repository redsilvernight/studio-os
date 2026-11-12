from __future__ import annotations

import hashlib
import re
from collections import deque
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, TypeAdapter, ValidationError, model_validator

from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel
from studio_contracts.local.common import contains_secret_material


class LibraryKind(StrEnum):
    """Closed studio taxonomy (our own domain, not a vendor catalog):
    what kind of reusable definition a library resource is."""

    RULE = "rule"
    SKILL = "skill"
    AGENT_DEFINITION = "agent_definition"
    MODEL_PROFILE = "model_profile"
    WORKFLOW = "workflow"
    HOOK = "hook"


class LibraryScope(StrEnum):
    STUDIO = "studio"
    PROJECT = "project"
    USER = "user"


class LibraryStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class BindingRelation(StrEnum):
    """Closed vocabulary of Library Binding types.

    Every allowed `(source kind, target kind)` couple maps to exactly one
    relation (see `_BINDING_MATRIX`) — the relation is a label on that
    couple, never a free-form string. Unknown values are rejected by
    Pydantic before any existence check runs."""

    REQUIRES_MODEL_PROFILE = "requires_model_profile"
    USES_SKILL = "uses_skill"
    APPLIES_RULE = "applies_rule"
    COMPOSES_AGENT = "composes_agent"
    REFERENCES_WORKFLOW = "references_workflow"
    REFINES_SKILL_RULE = "refines_skill_rule"
    USES_HOOK = "uses_hook"


class DependencyPin(ContractModel):
    """A version-pinned reference to another library resource version.

    `relation` names the Library Binding type. When omitted it
    is inferred server-side from the unique matrix mapping for the
    `(source kind, target kind)` couple; an explicitly wrong relation for an
    otherwise allowed couple is rejected with `422 invalid_binding`."""

    kind: LibraryKind
    stable_key: str
    version: int
    relation: BindingRelation | None = None


class ResourceDependencyPin(DependencyPin):
    resource_id: UUID


DependencySelection = ResourceDependencyPin | DependencyPin
_DEPENDENCY_SELECTION: TypeAdapter[DependencySelection] = TypeAdapter(DependencySelection)


def parse_dependency_selection(raw: object) -> DependencySelection:
    return _DEPENDENCY_SELECTION.validate_python(raw)


class DependencyUpdate(ContractModel):
    resource_id: UUID
    scope: LibraryScope
    pinned_version: int
    active_version: int
    deprecated: bool
    update_available: bool
    suggested_pin: ResourceDependencyPin


class DependencyUpdates(ContractModel):
    resource_id: UUID
    version: int
    mutates: Literal[False] = False
    items: list[DependencyUpdate] = Field(max_length=100)
    additional_available: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)


_BINDING_MATRIX: dict[tuple[LibraryKind, LibraryKind], BindingRelation] = {
    (LibraryKind.AGENT_DEFINITION, LibraryKind.RULE): BindingRelation.APPLIES_RULE,
    (LibraryKind.AGENT_DEFINITION, LibraryKind.SKILL): BindingRelation.USES_SKILL,
    (LibraryKind.AGENT_DEFINITION, LibraryKind.MODEL_PROFILE): (
        BindingRelation.REQUIRES_MODEL_PROFILE
    ),
    (LibraryKind.AGENT_DEFINITION, LibraryKind.AGENT_DEFINITION): BindingRelation.COMPOSES_AGENT,
    (LibraryKind.AGENT_DEFINITION, LibraryKind.WORKFLOW): BindingRelation.REFERENCES_WORKFLOW,
    (LibraryKind.SKILL, LibraryKind.RULE): BindingRelation.REFINES_SKILL_RULE,
    (LibraryKind.WORKFLOW, LibraryKind.RULE): BindingRelation.APPLIES_RULE,
    (LibraryKind.WORKFLOW, LibraryKind.SKILL): BindingRelation.USES_SKILL,
    (LibraryKind.WORKFLOW, LibraryKind.AGENT_DEFINITION): BindingRelation.COMPOSES_AGENT,
    (LibraryKind.AGENT_DEFINITION, LibraryKind.HOOK): BindingRelation.USES_HOOK,
    (LibraryKind.WORKFLOW, LibraryKind.HOOK): BindingRelation.USES_HOOK,
}
"""Single source of truth for allowed Library Binding couples (P5/DEC-0067).

`rule`, `model_profile` and `hook` never source a binding; every listed couple maps
to exactly one relation, so an omitted pin relation is inferred without
ambiguity and the `(from_version_id, to_resource_id)` uniqueness stays
sufficient (no relaxation needed)."""


def binding_relation_for(
    source_kind: LibraryKind, target_kind: LibraryKind
) -> BindingRelation | None:
    """Returns the unique relation for an allowed couple, `None` when the
    couple is forbidden. Pure function of the two kinds — no existence
    oracle, safe to call before or after resolution."""

    return _BINDING_MATRIX.get((source_kind, target_kind))


def binding_scope_allows(
    source_scope: LibraryScope,
    source_owner: UUID | None,
    target_scope: LibraryScope,
    target_owner: UUID | None,
) -> bool:
    """Structural scope rule for Library Bindings (P5/DEC-0067, DEC-0063).

    A shared definition (studio/project) must never depend on a private
    (user) one — other readers would fail the whole resolution. A user
    definition may only bind a user target owned by the same user. Every
    other combination is allowed here; target visibility itself (`_can_read`
    filter-first, 404 on invisible) is enforced separately before this runs,
    so a `False` here only ever concerns resources visible to the caller."""

    if target_scope == LibraryScope.USER:
        return (
            source_scope == LibraryScope.USER
            and source_owner is not None
            and source_owner == target_owner
        )
    return True


class LibraryResource(VersionedModel):
    """The active pointer of one reusable definition.
    `active_version == 0` means no version has been activated yet.
    Never confused with `Agent` provenance identity."""

    id: UUID
    kind: LibraryKind
    stable_key: str
    scope: LibraryScope
    status: LibraryStatus = LibraryStatus.DRAFT
    active_version: int = 0
    owner_user_id: UUID | None = None
    project_id: UUID | None = None
    created_by_user_id: UUID | None = None
    base_update_available: bool = False
    """Read-only alert for a User-scope override (P60): the common version its
    active version derives from (`derived_from`) is no longer the active one.
    Purely informational — nothing is re-based or re-applied automatically."""
    base_active_version: int | None = None
    """Active version of that common base when the alert is raised; `None`
    when the resource has no derived base or no update to report."""


class LibraryVersionRef(ContractModel):
    resource_id: UUID
    version: int = Field(ge=1)


class LibraryResourceCreate(IdempotentCreate):
    """Creates the resource row plus its draft version 1 (which never moves
    `active_version` by itself — activation is a separate explicit operation,
    `project_id` is required for project scope and
    forbidden otherwise; `owner_user_id` is always server-derived, never
    client-supplied."""

    kind: LibraryKind
    stable_key: str = Field(min_length=1, max_length=200)
    scope: LibraryScope
    project_id: UUID | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    content: dict[str, object] = {}
    dependencies: list[DependencySelection] = []
    derived_from: LibraryVersionRef | None = None


class LibraryVersion(ContractModel):
    """One immutable snapshot of a resource version."""

    id: UUID
    resource_id: UUID
    version: int
    title: str
    description: str | None = None
    content: dict[str, object] = {}
    dependencies: list[DependencyPin] = []
    derived_from: LibraryVersionRef | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime


LIBRARY_VERSION_BATCH_MAX = 500


class LibraryVersionBatchGet(ContractModel):
    """Bounded read of exact versions; duplicates are collapsed server-side."""

    items: list[LibraryVersionRef] = Field(min_length=1, max_length=LIBRARY_VERSION_BATCH_MAX)


class LibraryVersionBatchItem(ContractModel):
    resource_id: UUID
    version: int
    status: Literal["ok", "not_found"]
    detail: LibraryVersion | None = None


class LibraryVersionBatchResult(ContractModel):
    """Items aligned with the request; `not_found` hides absent resources,
    other users' User-scope resources and absent versions alike."""

    items: list[LibraryVersionBatchItem]


class LibraryVersionCreate(IdempotentCreate):
    title: str = Field(min_length=1)
    description: str | None = None
    content: dict[str, object] = {}
    dependencies: list[DependencySelection] = []
    derived_from: LibraryVersionRef | None = None


class LibraryActivate(ContractModel):
    """Explicit activation: moves `active_version`
    only. `expected_resource_version` is the optimistic-concurrency guard
    (409 `version_conflict` on stale)."""

    version: int = Field(ge=1)
    expected_resource_version: int


class LibraryDeprecate(ContractModel):
    """Deprecation replaces deletion: flips `status`, keeps
    history and `active_version`. Same optimistic-concurrency guard."""

    expected_resource_version: int


class VersionOrigin(StrEnum):
    """How an effective version was picked: P2 shadowing selection yields
    `lock`/`active`; an exact version-pinned dependency edge yields `pin`.
    Only the P5 resolved output emits `pin` — `LibraryResolution` (P2) still
    emits `lock`/`active` alone (P5, additive)."""

    LOCK = "lock"
    ACTIVE = "active"
    PIN = "pin"


class LibraryResolution(ContractModel):
    """Minimal scope-resolution outcome: which definition/version is
    effective for a caller, where the version came from, and whether it is
    deprecated. Provenance names the effective resource only, never the
    discarded invisible candidates."""

    resource_id: UUID
    kind: LibraryKind
    stable_key: str
    scope: LibraryScope
    version: int
    version_origin: VersionOrigin
    deprecated: bool = False


class LibraryProjectLock(ContractModel):
    """A project pins `(resource_id, locked_version)`: the lock key is the
    canonical resource UUID, never `stable_key` alone."""

    id: UUID
    project_id: UUID
    resource_id: UUID
    locked_version: int
    created_by_user_id: UUID | None = None
    created_at: datetime


class LibraryLockCreate(IdempotentCreate):
    project_id: UUID
    resource_id: UUID
    locked_version: int


class CapabilityRequirement(ContractModel):
    """Vendor-neutral model requirements (gate P0 deliverable, enforced from
    P3). All dimensions are open strings/numbers, never vendor enums,
    whitelists or commercial rankings. A `ModelProfile` resource carries one
    of these in its version `content` (see `ModelProfileContent`)."""

    reasoning: str | None = None
    coding: bool = False
    context_window_min: int | None = None
    tools_required: list[str] = []
    multimodal: str | None = None
    local_compatible: bool = False
    cost: str | None = None
    latency: str | None = None


class RuntimeCapabilities(ContractModel):
    """Abstract capability surface the P6 Runtime Registry will satisfy.
    Open strings, same vocabulary as `CapabilityRequirement`, never a vendor
    catalog."""

    reasoning: str | None = None
    coding: bool = False
    context_window: int | None = None
    tools: list[str] = []
    multimodal: str | None = None
    local: bool = False
    cost: str | None = None
    latency: str | None = None


def check_compatibility(
    requirement: CapabilityRequirement, capabilities: RuntimeCapabilities
) -> list[str]:
    """Pure conservative matcher (gate precision 4): returns the list of
    unsatisfied reasons, `[]` when satisfied. A required dimension the
    capabilities do not describe (`None`) is a non-match — unknown is never
    implicitly compatible. Open-string dimensions compare by equality: with
    no defined ordering, any other comparison would be a silent ranking."""

    unsatisfied: list[str] = []
    if requirement.reasoning is not None and capabilities.reasoning != requirement.reasoning:
        unsatisfied.append(f"reasoning: required {requirement.reasoning!r}")
    if requirement.coding and not capabilities.coding:
        unsatisfied.append("coding: required")
    if requirement.context_window_min is not None and (
        capabilities.context_window is None
        or capabilities.context_window < requirement.context_window_min
    ):
        unsatisfied.append(f"context_window_min: required {requirement.context_window_min}")
    missing_tools = [t for t in requirement.tools_required if t not in capabilities.tools]
    if missing_tools:
        unsatisfied.append(f"tools_required: missing {missing_tools}")
    if requirement.multimodal is not None and capabilities.multimodal != requirement.multimodal:
        unsatisfied.append(f"multimodal: required {requirement.multimodal!r}")
    if requirement.local_compatible and not capabilities.local:
        unsatisfied.append("local_compatible: required")
    if requirement.cost is not None and capabilities.cost != requirement.cost:
        unsatisfied.append(f"cost: required {requirement.cost!r}")
    if requirement.latency is not None and capabilities.latency != requirement.latency:
        unsatisfied.append(f"latency: required {requirement.latency!r}")
    return unsatisfied


RULE_SKILL_TEXT_MAX_LENGTH = 65_536
"""Max characters for a rule/skill version body (P3/DEC-0066).

Own Library budget, unrelated to the DEC-0057 256 Kio Context Package budget
(which bounds a composed package, never a single stored version).
"""


class RuleContent(ContractModel):
    """Semantic shape of a `rule` version (P3/DEC-0066): free prose, nothing
    else. Never a provider, model, harness or capability reference."""

    content_schema: Literal["studio.library.rule/v1"]
    text: str = Field(min_length=1, max_length=RULE_SKILL_TEXT_MAX_LENGTH)


class RuleContentV2(ContractModel):
    """Additive `rule/v2` (P40): v1 plus `applies_to` globs (empty = global
    rule). Still prose only; `extra="forbid"` rejects any other key."""

    content_schema: Literal["studio.library.rule/v2"]
    text: str = Field(min_length=1, max_length=RULE_SKILL_TEXT_MAX_LENGTH)
    applies_to: list[Annotated[str, StringConstraints(min_length=1)]] = Field(default_factory=list)


SKILL_FILES_MAX = 64
SKILL_FILE_TEXT_MAX_LENGTH = RULE_SKILL_TEXT_MAX_LENGTH
SKILL_FILES_TOTAL_MAX_LENGTH = 524_288
_SKILL_FILE_SEGMENT = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9._ -]{0,127}$|^\.[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$"
)


def skill_file_path_error(path: str) -> str | None:
    """Why `path` cannot be an auxiliary skill file path (None if safe).

    Relative POSIX only: no absolute path, drive, backslash, `.`/`..` segment,
    reserved name or trailing dot/space; `SKILL.md` is the main file."""

    if not path or path.startswith("/") or "\\" in path or ":" in path or "\x00" in path:
        return "must be a relative POSIX path"
    segments = path.split("/")
    for segment in segments:
        if segment in {"", ".", ".."} or not _SKILL_FILE_SEGMENT.match(segment):
            return "unsafe path segment"
        if segment.endswith((".", " ")) or segment.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
            return "reserved or non-portable name"
    if path.lower() == "skill.md":
        return "SKILL.md is the main file"
    return None


_WINDOWS_RESERVED = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class SkillFile(ContractModel):
    """One auxiliary text file of a multi-file skill: relative path, UTF-8
    text and the SHA-256 of that text (verified on write)."""

    path: str = Field(min_length=1, max_length=512)
    text: str = Field(max_length=SKILL_FILE_TEXT_MAX_LENGTH)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _check(self) -> SkillFile:
        error = skill_file_path_error(self.path)
        if error:
            raise ValueError(f"skill file {self.path!r}: {error}")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError(f"skill file {self.path!r}: sha256 mismatch")
        return self


class SkillContent(ContractModel):
    """Semantic shape of a `skill` version (P3/DEC-0066): free prose plus
    optional auxiliary text files (additive, absent = historical single-file
    skill). Never a provider, model, harness or capability reference."""

    content_schema: Literal["studio.library.skill/v1"]
    text: str = Field(min_length=1, max_length=RULE_SKILL_TEXT_MAX_LENGTH)
    files: list[SkillFile] = Field(default_factory=list, max_length=SKILL_FILES_MAX)

    @model_validator(mode="after")
    def _check_files(self) -> SkillContent:
        _check_skill_files(self.files)
        return self


def _check_skill_files(files: list[SkillFile]) -> None:
    seen: set[str] = set()
    for file in files:
        folded = file.path.casefold()
        if folded in seen:
            raise ValueError(f"duplicate skill file path {file.path!r}")
        seen.add(folded)
    for a in seen:
        if any(b.startswith(a + "/") for b in seen):
            raise ValueError(f"skill file path {a!r} is also a directory")
    if sum(len(f.text) for f in files) > SKILL_FILES_TOTAL_MAX_LENGTH:
        raise ValueError("skill files exceed the total size limit")


class SkillContentV2(ContractModel):
    """Additive `skill/v2`: v1 plus `disable_model_invocation`, the neutral
    "invoked only by the user, never by the model" flag that harnesses
    project in their own syntax. Still prose and files only; `extra="forbid"`
    rejects any other key."""

    content_schema: Literal["studio.library.skill/v2"]
    text: str = Field(min_length=1, max_length=RULE_SKILL_TEXT_MAX_LENGTH)
    files: list[SkillFile] = Field(default_factory=list, max_length=SKILL_FILES_MAX)
    disable_model_invocation: bool = False

    @model_validator(mode="after")
    def _check_files(self) -> SkillContentV2:
        _check_skill_files(self.files)
        return self


class ModelProfileContent(ContractModel):
    """Semantic shape of a `model_profile` version (P3/DEC-0066):
    vendor-neutral requirements only. No concrete provider, model, harness,
    endpoint, secret, vendor family, vendor API version, ranking or
    provider/model whitelist — `extra="forbid"` rejects them all. The
    concrete runtime/model choice belongs to P4 bindings and P10 adapters,
    never to the canonical domain."""

    content_schema: Literal["studio.library.model_profile/v1"]
    requirements: CapabilityRequirement
    description: str | None = None


class AgentDefinitionContent(ContractModel):
    """Semantic shape of an `agent_definition` version (P3/DEC-0066): a
    logical definition, never an execution instance. Descriptive and
    observability metadata only — no inline capabilities (requirements come
    exclusively through a version-pinned link to a `model_profile`, and an
    agent definition without one simply expresses no requirement), no
    provider, model, harness or concrete runtime. `extra="forbid"` rejects
    them all."""

    content_schema: Literal["studio.library.agent_definition/v1"]
    summary: str | None = None
    intended_use: str | None = None


AGENT_TOOL_NAME_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
"""Harness-neutral tool-need vocabulary for `agent_definition/v2` (P31):
lowercase labels such as `read`, `grep`, `bash`. Open vocabulary validated by
pattern; adapters map labels to harness-specific names."""


class AgentDefinitionContentV2(ContractModel):
    """Additive `agent_definition/v2` (P31): v1 plus the agent's instructions,
    triggers, edit policy and neutral tool needs. Still no provider, model,
    harness or inline capabilities; `extra="forbid"` rejects them."""

    content_schema: Literal["studio.library.agent_definition/v2"]
    summary: str | None = None
    intended_use: str | None = None
    instructions: str | None = Field(default=None, max_length=RULE_SKILL_TEXT_MAX_LENGTH)
    triggers: list[Annotated[str, StringConstraints(min_length=1)]] = Field(default_factory=list)
    edit_policy: Literal["deny", "ask", "allow"] | None = None
    tools: list[Annotated[str, StringConstraints(pattern=AGENT_TOOL_NAME_PATTERN)]] = Field(
        default_factory=list
    )


WORKFLOW_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,127}$"
"""Portable, harness-neutral identifier syntax for workflow-declared names
(P11/DEC-0075). Anchored, ASCII-only, no path separator, no dot and no UUID
shape — a participant id or an I/O name is a stable logical label, never a
filesystem path, a runtime handle or a provider/model identifier."""


class WorkflowIOSource(ContractModel):
    """Where a declared participant input is fed from, as a *declaration*.

    `participant_id is None` names a workflow-level input; otherwise it names
    another participant's declared output. This is a static dataflow edge
    only: P11 validates that the referenced declaration exists, never a
    runtime value, never a transport between participants (that belongs to
    the harness)."""

    participant_id: str | None = Field(default=None, pattern=WORKFLOW_NAME_PATTERN)
    name: str = Field(pattern=WORKFLOW_NAME_PATTERN)


class WorkflowIODeclaration(ContractModel):
    """One declarative input or output of a workflow or a participant.

    Describes *what is needed/produced*, never a value: no `value`, no
    `generated_file`, no `model_response`, no execution status. `required`
    is meaningful for inputs; `source` is a static dataflow declaration for
    participant inputs (optional — absent means harness/external) and for
    workflow outputs (required — they always expose a participant output)."""

    name: str = Field(pattern=WORKFLOW_NAME_PATTERN)
    description: str | None = None
    required: bool = True
    type: str | None = Field(default=None, max_length=200)
    source: WorkflowIOSource | None = None


class WorkflowParticipant(ContractModel):
    """One logical role in a workflow definition, never a runtime instance.

    `participant_id` is local and stable within the definition (the same
    `AgentDefinition` may play several roles under distinct ids), so the
    binding is by `agent_stable_key` to one version-pinned `composes_agent`
    dependency of the same workflow version — the pin lives in
    `library_resource_links`, never duplicated here. `depends_on` names the
    participant ids this role waits for (a DAG, statically validated).
    `description`/`inputs`/`outputs` describe the role; no status, no
    timestamps, no attempt/retry counter, no pid/process id, no `provider`
    or `model` (runtime selection belongs to P4/P5/P6)."""

    participant_id: str = Field(pattern=WORKFLOW_NAME_PATTERN)
    description: str | None = None
    agent_stable_key: str = Field(min_length=1, max_length=200)
    depends_on: list[str] = []
    inputs: list[WorkflowIODeclaration] = []
    outputs: list[WorkflowIODeclaration] = []


class WorkflowContent(ContractModel):
    """Semantic shape of a `workflow` version (P11/DEC-0075): a canonical
    *declarative* definition, never an execution.

    It owns participant identity, the dependency graph and the input/output
    declarations. It never owns the concrete runtime (P4/P5/P6), execution
    state or run data (the harness): no `status`, no `started_at`, no
    `finished_at`, no `retry_policy`, no `timeout`, no `machine_id`, no
    `runtime_id`, no `provider`/`model`. `extra="forbid"` rejects them all.

    Library references (AgentDefinition through `composes_agent`, Rule
    through `applies_rule`, Skill through `uses_skill`) are owned by the
    version's pinned `dependencies`/`library_resource_links`, versioned by
    the Library, never copied into this document."""

    content_schema: Literal["studio.library.workflow/v1"]
    summary: str | None = None
    participants: list[WorkflowParticipant] = Field(min_length=1)
    inputs: list[WorkflowIODeclaration] = []
    outputs: list[WorkflowIODeclaration] = []


class WorkflowValidationReason(StrEnum):
    """Closed vocabulary of static workflow-definition failures
    (`422 invalid_workflow`). Every reason describes the caller's own
    submitted payload; none is an existence oracle over stored resources."""

    DUPLICATE_PARTICIPANT = "duplicate_participant"
    UNKNOWN_DEPENDENCY = "unknown_dependency"
    DEPENDENCY_CYCLE = "dependency_cycle"
    UNKNOWN_PARTICIPANT_AGENT = "unknown_participant_agent"
    UNUSED_AGENT_DEPENDENCY = "unused_agent_dependency"
    DUPLICATE_IO_DECLARATION = "duplicate_io_declaration"
    INVALID_IO_REFERENCE = "invalid_io_reference"


def _workflow_error(reason: WorkflowValidationReason, field: str) -> dict[str, str]:
    return {"reason": reason.value, "field": field}


def _workflow_has_cycle(participants: list[WorkflowParticipant]) -> bool:
    """Kahn topological sort over `depends_on` edges (`dependency → dependent`).
    Pure and deterministic: ids are processed in sorted order, so the verdict
    never depends on declaration order. A non-empty remainder is a cycle."""

    adjacency: dict[str, list[str]] = {p.participant_id: [] for p in participants}
    indegree: dict[str, int] = {p.participant_id: 0 for p in participants}
    for participant in participants:
        for dependency in participant.depends_on:
            adjacency[dependency].append(participant.participant_id)
            indegree[participant.participant_id] += 1
    ready = deque(sorted(name for name, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        node = ready.popleft()
        visited += 1
        for dependent in sorted(adjacency[node]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    return visited != len(participants)


def workflow_validation_errors(
    content: dict[str, object],
    dependencies: Sequence[DependencyPin],
) -> list[dict[str, str]]:
    """Static workflow validation (P11/DEC-0075), on top of the P3 schema.

    Validates only what is decidable from the submitted definition: unique
    participant ids and I/O names, known `depends_on` targets, an acyclic
    dependency graph, participant agent keys matching the version's
    `composes_agent` pins, and well-formed static dataflow references.

    Pure: reads only `content` and the caller's `dependencies`, never a
    stored resource — so it is never an existence oracle and its verdict is
    deterministic. Returns the first failure as `[{reason, field}]` (empty
    list when valid); schema-shape failures stay owned by
    `content_validation_errors` (`422 invalid_content`)."""

    try:
        workflow = WorkflowContent.model_validate(dict(content))
    except ValidationError:
        return []

    participants = workflow.participants
    by_id: dict[str, WorkflowParticipant] = {}
    for participant in participants:
        if participant.participant_id in by_id:
            return [
                _workflow_error(
                    WorkflowValidationReason.DUPLICATE_PARTICIPANT,
                    f"participants.{participant.participant_id}",
                )
            ]
        by_id[participant.participant_id] = participant

    for participant in participants:
        for dependency in participant.depends_on:
            if dependency not in by_id:
                return [
                    _workflow_error(
                        WorkflowValidationReason.UNKNOWN_DEPENDENCY,
                        f"participants.{participant.participant_id}.depends_on",
                    )
                ]

    if _workflow_has_cycle(participants):
        return [_workflow_error(WorkflowValidationReason.DEPENDENCY_CYCLE, "participants")]

    for label, declarations in (
        ("inputs", workflow.inputs),
        ("outputs", workflow.outputs),
    ):
        names = [declaration.name for declaration in declarations]
        if len(set(names)) != len(names):
            return [
                _workflow_error(
                    WorkflowValidationReason.DUPLICATE_IO_DECLARATION, f"workflow.{label}"
                )
            ]

    for participant in participants:
        for label, declarations in (
            ("inputs", participant.inputs),
            ("outputs", participant.outputs),
        ):
            names = [declaration.name for declaration in declarations]
            if len(set(names)) != len(names):
                return [
                    _workflow_error(
                        WorkflowValidationReason.DUPLICATE_IO_DECLARATION,
                        f"participants.{participant.participant_id}.{label}",
                    )
                ]

    agent_keys = {
        pin.stable_key for pin in dependencies if pin.kind == LibraryKind.AGENT_DEFINITION
    }
    used_agent_keys: set[str] = set()
    for participant in participants:
        if participant.agent_stable_key not in agent_keys:
            return [
                _workflow_error(
                    WorkflowValidationReason.UNKNOWN_PARTICIPANT_AGENT,
                    f"participants.{participant.participant_id}.agent_stable_key",
                )
            ]
        used_agent_keys.add(participant.agent_stable_key)
    unused = sorted(agent_keys - used_agent_keys)
    if unused:
        return [
            _workflow_error(
                WorkflowValidationReason.UNUSED_AGENT_DEPENDENCY, f"dependencies.{unused[0]}"
            )
        ]

    workflow_inputs = {declaration.name for declaration in workflow.inputs}
    for declaration in workflow.inputs:
        if declaration.source is not None:
            return [
                _workflow_error(
                    WorkflowValidationReason.INVALID_IO_REFERENCE,
                    f"workflow.inputs.{declaration.name}.source",
                )
            ]
    for declaration in workflow.outputs:
        source = declaration.source
        field = f"workflow.outputs.{declaration.name}.source"
        if source is None or source.participant_id is None:
            return [_workflow_error(WorkflowValidationReason.INVALID_IO_REFERENCE, field)]
        producer = by_id.get(source.participant_id)
        if producer is None or source.name not in {o.name for o in producer.outputs}:
            return [_workflow_error(WorkflowValidationReason.INVALID_IO_REFERENCE, field)]

    for participant in participants:
        for declaration in participant.outputs:
            if declaration.source is not None:
                return [
                    _workflow_error(
                        WorkflowValidationReason.INVALID_IO_REFERENCE,
                        f"participants.{participant.participant_id}.outputs.{declaration.name}.source",
                    )
                ]
        for declaration in participant.inputs:
            source = declaration.source
            if source is None:
                continue
            field = f"participants.{participant.participant_id}.inputs.{declaration.name}.source"
            if source.participant_id is None:
                if source.name not in workflow_inputs:
                    return [_workflow_error(WorkflowValidationReason.INVALID_IO_REFERENCE, field)]
                continue
            if source.participant_id == participant.participant_id:
                return [_workflow_error(WorkflowValidationReason.INVALID_IO_REFERENCE, field)]
            producer = by_id.get(source.participant_id)
            if producer is None or source.name not in {o.name for o in producer.outputs}:
                return [_workflow_error(WorkflowValidationReason.INVALID_IO_REFERENCE, field)]

    return []


HOOK_SCRIPT_MAX_LENGTH = 65_536
"""Max characters for one hook script body (same budget as rule/skill text)."""


class HookEvent(StrEnum):
    """Closed, harness-neutral hook trigger vocabulary. Each local adapter
    maps it to its harness event (e.g. `PreToolUse`,
    `tool.execute.before`, ...); an event a harness cannot express is skipped
    for that harness and reported, never approximated."""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_PROMPT = "user_prompt"
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    STOP = "stop"
    SUBAGENT_STOP = "subagent_stop"
    NOTIFICATION = "notification"
    PRE_COMPACT = "pre_compact"


class HookMode(StrEnum):
    """`blocking`: a non-zero exit may veto the action (only meaningful on
    `pre_tool` / `user_prompt` / `stop`); `advisory`: output is informative,
    failures never block."""

    BLOCKING = "blocking"
    ADVISORY = "advisory"


class HookOs(StrEnum):
    ANY = "any"
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"


class HookShell(StrEnum):
    PWSH = "pwsh"
    BASH = "bash"
    SH = "sh"
    PYTHON = "python"
    NODE = "node"


class HookScript(ContractModel):
    """One platform variant of a hook: the script body is stored inline
    (never a path, never a URL) so its fingerprint covers what runs."""

    os: HookOs = HookOs.ANY
    shell: HookShell
    body: str = Field(min_length=1, max_length=HOOK_SCRIPT_MAX_LENGTH)


class HookContent(ContractModel):
    """Semantic shape of a `hook` version (`studio.library.hook/v1`): a
    script run locally by a harness on an abstract event. Never a secret
    (rejected by `hook_validation_errors`), never a harness-specific event
    name, never a provider or model reference. Executing it locally always
    requires an explicit per-machine consent on the content fingerprint
    (client side); the server only stores and distributes it."""

    content_schema: Literal["studio.library.hook/v1"]
    event: HookEvent
    matcher: str | None = Field(default=None, min_length=1, max_length=200)
    mode: HookMode = HookMode.ADVISORY
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    scripts: list[HookScript] = Field(min_length=1, max_length=8)
    description: str | None = Field(default=None, max_length=1000)


class HookValidationReason(StrEnum):
    """Closed vocabulary of static hook-definition failures (`422 invalid_hook`)."""

    DUPLICATE_SCRIPT_TARGET = "duplicate_script_target"
    MATCHER_NOT_SUPPORTED = "matcher_not_supported"
    BLOCKING_NOT_SUPPORTED = "blocking_not_supported"
    SECRET_MATERIAL = "secret_material"


_HOOK_MATCHER_EVENTS = frozenset({HookEvent.PRE_TOOL, HookEvent.POST_TOOL})
_HOOK_BLOCKING_EVENTS = frozenset({HookEvent.PRE_TOOL, HookEvent.USER_PROMPT, HookEvent.STOP})


def hook_validation_errors(content: dict[str, object]) -> list[dict[str, str]]:
    """Static hook validation on top of the schema: unique `(os, shell)`
    variants, matcher only on tool events, blocking only where a harness can
    veto, and no secret material in any script body. Returns `[]` when valid
    (or when the schema itself fails — reported by `content_validation_errors`)."""

    try:
        hook = HookContent.model_validate(dict(content))
    except ValidationError:
        return []
    seen: set[tuple[HookOs, HookShell]] = set()
    for index, script in enumerate(hook.scripts):
        target = (script.os, script.shell)
        if target in seen:
            return [_hook_error(HookValidationReason.DUPLICATE_SCRIPT_TARGET, f"scripts.{index}")]
        seen.add(target)
        if contains_secret_material(script.body):
            return [_hook_error(HookValidationReason.SECRET_MATERIAL, f"scripts.{index}.body")]
    if hook.matcher is not None and hook.event not in _HOOK_MATCHER_EVENTS:
        return [_hook_error(HookValidationReason.MATCHER_NOT_SUPPORTED, "matcher")]
    if hook.mode is HookMode.BLOCKING and hook.event not in _HOOK_BLOCKING_EVENTS:
        return [_hook_error(HookValidationReason.BLOCKING_NOT_SUPPORTED, "mode")]
    return []


def _hook_error(reason: HookValidationReason, field: str) -> dict[str, str]:
    return {"field": field, "reason": reason.value}


_CONTENT_SCHEMAS: dict[LibraryKind, type[ContractModel]] = {
    LibraryKind.RULE: RuleContent,
    LibraryKind.SKILL: SkillContent,
    LibraryKind.MODEL_PROFILE: ModelProfileContent,
    LibraryKind.AGENT_DEFINITION: AgentDefinitionContent,
    LibraryKind.WORKFLOW: WorkflowContent,
    LibraryKind.HOOK: HookContent,
}
"""Per-kind semantic validators (P3/DEC-0066, P11/DEC-0075). `workflow` now
has a schema (`studio.library.workflow/v1`); its cross-field structure
(participants, DAG, I/O) is validated separately by
`workflow_validation_errors`."""


def content_validation_errors(
    kind: LibraryKind, content: dict[str, object]
) -> list[dict[str, str]]:
    """Validates a version `content` against its per-kind P3/P11 schema.

    Returns `[]` when valid. Otherwise returns JSON-safe `[{field, reason}]`
    entries describing only the submitted payload, never any other stored
    resource (validation is not an existence oracle). Cross-field workflow
    structure (participants, DAG, I/O references) is validated separately by
    `workflow_validation_errors`.
    """

    model = _CONTENT_SCHEMAS.get(kind)
    if model is None:
        return []
    if (
        kind is LibraryKind.AGENT_DEFINITION
        and content.get("content_schema") == "studio.library.agent_definition/v2"
    ):
        model = AgentDefinitionContentV2
    elif kind is LibraryKind.RULE and content.get("content_schema") == "studio.library.rule/v2":
        model = RuleContentV2
    elif kind is LibraryKind.SKILL and content.get("content_schema") == "studio.library.skill/v2":
        model = SkillContentV2
    try:
        model.model_validate(dict(content))
    except ValidationError as exc:
        details: list[dict[str, str]] = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "(root)"
            details.append({"field": field, "reason": str(error["msg"])})
        return details
    return []


def parse_rule_content(content: dict[str, object]) -> RuleContent | RuleContentV2:
    """The typed rule content, whichever additive version it declares."""

    if content.get("content_schema") == "studio.library.rule/v2":
        return RuleContentV2.model_validate(dict(content))
    return RuleContent.model_validate(dict(content))


def parse_skill_content(content: dict[str, object]) -> SkillContent | SkillContentV2:
    """The typed skill content, whichever additive version it declares."""

    if content.get("content_schema") == "studio.library.skill/v2":
        return SkillContentV2.model_validate(dict(content))
    return SkillContent.model_validate(dict(content))


def validate_library_content(kind: LibraryKind, content: dict[str, object]) -> None:
    """Raises `ValueError` carrying the `content_validation_errors` details
    when a version `content` violates its per-kind P3 schema."""

    errors = content_validation_errors(kind, content)
    if errors:
        raise ValueError(f"invalid {kind.value} content: {errors}")
