from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.common import ContractModel
from studio_contracts.library import LibraryKind, RuntimeCapabilities


class RuntimeLevel(StrEnum):
    """Stored and ephemeral levels of runtime choice, strongest first.

    `session` is never persisted — it travels with the resolve call only.
    `project_override` beats a personal choice (explicit project pinning);
    `project_default` and `studio_default` only apply below it."""

    SESSION = "session"
    PROJECT_OVERRIDE = "project_override"
    USER = "user"
    PROJECT_DEFAULT = "project_default"
    STUDIO_DEFAULT = "studio_default"


class RuntimeTarget(ContractModel):
    """A concrete, non-secret runtime choice.

    Open references only: an owned machine locus, abstract provider/model
    labels (same status as agent observability metadata — never a vendor
    catalog, never a whitelist), and a capability snapshot used for
    compatibility checks. No secret field exists on this model by
    construction: there is nowhere to put an API key, token or credential.
    At least one of `machine_id`, `provider_ref`, `model_ref` is required."""

    machine_id: UUID | None = None
    provider_ref: str | None = Field(default=None, min_length=1, max_length=200)
    model_ref: str | None = Field(default=None, min_length=1, max_length=200)
    capabilities: RuntimeCapabilities = RuntimeCapabilities()

    @model_validator(mode="after")
    def _require_anchor(self) -> RuntimeTarget:
        if self.machine_id is None and self.provider_ref is None and self.model_ref is None:
            raise ValueError("at least one of machine_id, provider_ref, model_ref")
        return self


class RuntimeBinding(ContractModel):
    """One stored runtime choice for a logical `(kind, stable_key)` key.

    The key is logical (never a version pin): the preference follows the
    definition across versions. `owner_user_id` is always the creating user
    (server-derived, never client-supplied): for `user` bindings it is the
    beneficiary, for shared levels it is the creator (release rules mirror
    project locks)."""

    id: UUID
    level: RuntimeLevel
    owner_user_id: UUID
    project_id: UUID | None = None
    target_kind: LibraryKind
    target_stable_key: str
    target: RuntimeTarget
    created_at: datetime


class RuntimeBindingCreate(ContractModel):
    """Creates one stored runtime choice. `owner_user_id` is never accepted:
    the server derives it from the authenticated principal."""

    level: RuntimeLevel
    project_id: UUID | None = None
    target_kind: LibraryKind
    target_stable_key: str = Field(min_length=1, max_length=200)
    target: RuntimeTarget


class RuntimeResolution(ContractModel):
    """Deterministic outcome of runtime choice resolution.

    `target` is `None` when no level holds a live choice (valid outcome, not
    an error). `level`/`matched_kind`/`matched_stable_key` name the winning
    entry. `resource_id`/`version` name the effective library definition the
    choice was resolved for. `compatible`/`unsatisfied` report the
    `check_compatibility` verdict against the linked model profile
    requirements when any exist — an explicitly chosen but incompatible
    target stays reported incompatible, never silently compatible."""

    target: RuntimeTarget | None = None
    level: RuntimeLevel | None = None
    matched_kind: LibraryKind | None = None
    matched_stable_key: str | None = None
    resource_id: UUID
    version: int
    compatible: bool = True
    unsatisfied: list[str] = []
