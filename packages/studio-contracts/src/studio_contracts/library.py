from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

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
    """Vendor-neutral model requirements (gate P0 deliverable). All
    dimensions are open strings/numbers, never vendor enums, whitelists or
    commercial rankings. A `ModelProfile` resource carries one of
    these in its version `content` (shape enforced from P3 on)."""

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
