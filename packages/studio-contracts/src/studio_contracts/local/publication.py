from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.local.common import (
    CapabilityName,
    ComponentId,
    ComponentState,
    Identifier,
    LocalContractModel,
    LocalError,
    OpaqueId,
    SemVer,
    Sha256Hex,
    UtcDatetime,
)


class LocalDataClass(StrEnum):
    PATHS = "paths"
    VAULT_CONTENT = "vault_content"
    INDEXES = "indexes"
    CODE_GRAPH = "code_graph"
    FILESYSTEM_DETAILS = "filesystem_details"
    HARNESS_CONFIG = "harness_config"
    SENSITIVE_DIAGNOSTICS = "sensitive_diagnostics"
    WORKSPACE_CONFIG = "workspace_config"
    SECRETS = "secrets"


class Visibility(StrEnum):
    LOCAL_ONLY = "local_only"
    SHAREABLE_SUMMARY = "shareable_summary"


class PublicationPolicy(LocalContractModel):
    """Local by default. Data classes are LOCAL_ONLY; only the cohesive
    SharedStatusSummary may leave the machine, never automatically, and only
    after the user has seen the exact payload."""

    classes: dict[LocalDataClass, Visibility]
    automatic_upload: Literal[False] = False
    requires_visible_preview: Literal[True] = True
    requires_explicit_confirmation: Literal[True] = True

    @model_validator(mode="after")
    def _all_classes_local(self) -> Self:
        missing = set(LocalDataClass) - set(self.classes)
        if missing:
            raise ValueError(f"policy misses data classes: {sorted(m.value for m in missing)}")
        shared = [k for k, v in self.classes.items() if v is not Visibility.LOCAL_ONLY]
        if shared:
            raise ValueError("no raw data class may be shared; only the summary can")
        return self


DEFAULT_PUBLICATION_POLICY = PublicationPolicy(
    classes=dict.fromkeys(LocalDataClass, Visibility.LOCAL_ONLY)
)


class ComponentStatusSummary(LocalContractModel):
    component: ComponentId
    state: ComponentState
    provider_id: Identifier | None = None
    item_count: int | None = Field(default=None, ge=0)


class SharedStatusSummary(LocalContractModel):
    """The only publishable shape: enumerated states, provider identifiers and
    counts. It has no free-text, path or content field, so it cannot leak what
    it does not have."""

    workspace_id: UUID
    project_id: UUID
    protocol_version: SemVer
    components: list[ComponentStatusSummary] = Field(default=[], max_length=16)
    generated_at: UtcDatetime


class PublicationPlan(LocalContractModel):
    plan_id: OpaqueId
    summary: SharedStatusSummary
    included: list[CapabilityName] = Field(default=[], max_length=16)
    plan_hash: Sha256Hex
    created_at: UtcDatetime
    expires_at: UtcDatetime
    excluded_classes: list[LocalDataClass]

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("a plan expires after it is created")
        if set(self.excluded_classes) != set(LocalDataClass):
            raise ValueError("a plan states that every raw data class is excluded")
        return self


class PublicationPreviewRequest(LocalContractModel):
    workspace_id: UUID


class PublicationPublishRequest(LocalContractModel):
    plan_id: OpaqueId
    plan_hash: Sha256Hex
    confirmed: Literal[True]


class PublicationOutcome(StrEnum):
    PUBLISHED = "published"
    REJECTED = "rejected"
    PLAN_EXPIRED = "plan_expired"
    TRANSPORT_UNAVAILABLE = "transport_unavailable"


class PublicationResult(LocalContractModel):
    plan_id: OpaqueId
    outcome: PublicationOutcome
    published_at: UtcDatetime | None = None
    error: LocalError | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        published = self.outcome is PublicationOutcome.PUBLISHED
        if published != (self.published_at is not None):
            raise ValueError("published_at is set exactly when the outcome is published")
        if published == (self.error is not None):
            raise ValueError("a failed publication carries an error, a published one does not")
        return self
