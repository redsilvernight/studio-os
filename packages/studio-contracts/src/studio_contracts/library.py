from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, ValidationError

from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel


class LibraryKind(StrEnum):
    """Closed studio taxonomy (our own domain, not a vendor catalog):
    what kind of reusable definition a library resource is."""

    RULE = "rule"
    SKILL = "skill"
    AGENT_DEFINITION = "agent_definition"
    MODEL_PROFILE = "model_profile"
    WORKFLOW = "workflow"


class LibraryScope(StrEnum):
    STUDIO = "studio"
    PROJECT = "project"
    USER = "user"


class LibraryStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class DependencyPin(ContractModel):
    """A version-pinned reference to another library resource version
    ."""

    kind: LibraryKind
    stable_key: str
    version: int


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
    dependencies: list[DependencyPin] = []


class LibraryVersion(ContractModel):
    """One immutable snapshot of a resource version."""

    id: UUID
    resource_id: UUID
    version: int
    title: str
    description: str | None = None
    content: dict[str, object] = {}
    dependencies: list[DependencyPin] = []
    created_by_user_id: UUID | None = None
    created_at: datetime


class LibraryVersionCreate(IdempotentCreate):
    title: str = Field(min_length=1)
    description: str | None = None
    content: dict[str, object] = {}
    dependencies: list[DependencyPin] = []


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
    LOCK = "lock"
    ACTIVE = "active"


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
    P3/DEC-0066). All dimensions are open strings/numbers, never vendor enums,
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


class SkillContent(ContractModel):
    """Semantic shape of a `skill` version (P3/DEC-0066): free prose, nothing
    else. Never a provider, model, harness or capability reference."""

    content_schema: Literal["studio.library.skill/v1"]
    text: str = Field(min_length=1, max_length=RULE_SKILL_TEXT_MAX_LENGTH)


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


_CONTENT_SCHEMAS: dict[LibraryKind, type[ContractModel]] = {
    LibraryKind.RULE: RuleContent,
    LibraryKind.SKILL: SkillContent,
    LibraryKind.MODEL_PROFILE: ModelProfileContent,
    LibraryKind.AGENT_DEFINITION: AgentDefinitionContent,
}
"""Per-kind semantic validators (P3/DEC-0066). `workflow` is deliberately
absent: its shape is deferred to P11 and its content stays free-form."""


def content_validation_errors(
    kind: LibraryKind, content: dict[str, object]
) -> list[dict[str, str]]:
    """Validates a version `content` against its per-kind P3 schema.

    Returns `[]` when valid — or when the kind has no P3 schema yet
    (`workflow`, deferred to P11). Otherwise returns JSON-safe
    `[{field, reason}]` entries describing only the submitted payload, never
    any other stored resource (P3 validation is not an existence oracle).
    """

    model = _CONTENT_SCHEMAS.get(kind)
    if model is None:
        return []
    try:
        model.model_validate(dict(content))
    except ValidationError as exc:
        details: list[dict[str, str]] = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "(root)"
            details.append({"field": field, "reason": str(error["msg"])})
        return details
    return []


def validate_library_content(kind: LibraryKind, content: dict[str, object]) -> None:
    """Raises `ValueError` carrying the `content_validation_errors` details
    when a version `content` violates its per-kind P3 schema."""

    errors = content_validation_errors(kind, content)
    if errors:
        raise ValueError(f"invalid {kind.value} content: {errors}")
