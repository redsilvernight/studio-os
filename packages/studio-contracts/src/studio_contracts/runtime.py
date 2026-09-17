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


class CapabilitySource(StrEnum):
    """Where registered capabilities come from (P6/DEC-0070).

    P6 MVP only ever stores `declared` (explicitly registered, no discovery,
    no detection, no adapter report). The enum — not a closed vendor list —
    is the extension point for future `detected` / `adapter-reported`
    sources; any other value is fail-closed until its semantics are defined."""

    DECLARED = "declared"


class RuntimeStatus(StrEnum):
    """Registry lifecycle (P6/DEC-0070): logical revocation only, never a
    physical delete — a revoked runtime stays readable (diagnostics) but
    resolves as non-live, so a binding toward it falls through instead of
    silently becoming another target."""

    ACTIVE = "active"
    REVOKED = "revoked"


_FORBIDDEN_METADATA_SUBSTRINGS = (
    "secret",
    "token",
    "password",
    "passwd",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "credential",
    "bearer",
    "authorization",
    "jwt",
)


def _reject_secret_metadata(metadata: dict[str, object], *, where: str) -> None:
    """The Registry is never a vault (P6/DEC-0070): no API key, bearer token,
    provider secret, password, private key, OAuth token or JWT — neither as
    a dedicated field (none exists by construction) nor smuggled inside free
    metadata. Best-effort fail-closed on key names (exact sensitive names
    plus sensitive substrings); values and free refs are never inspected, so
    this guard complements — but does not replace — the no-secret-columns
    schema rule."""
    for key in metadata:
        lowered = key.lower().replace("-", "_")
        if lowered in ("secret", "token", "password", "credentials", "authorization"):
            raise ValueError(f"{where}: secret field {key!r} is forbidden in runtime metadata")
        if any(part in lowered for part in _FORBIDDEN_METADATA_SUBSTRINGS):
            raise ValueError(f"{where}: secret field {key!r} is forbidden in runtime metadata")


def _open_ref(value: str | None, *, where: str) -> str | None:
    """Open-chain identifiers (P6/DEC-0070): harness, provider and model refs
    are validated minimally (non-empty, bounded) and never against a vendor
    catalog or enum — a new provider/harness/model needs no migration, no
    resolver change, no new type."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{where}: empty reference is not a valid open identifier")
    if len(value) > 200:
        raise ValueError(f"{where}: reference exceeds 200 characters")
    return value


class RuntimeRegistration(ContractModel):
    """Canonical persisted description of one declared runtime (P6/DEC-0070).

    Harness, provider, model and runtime are four different concepts, stored
    side by side but never fused: `harness_ref` names the consuming
    software, `provider_ref` the system exposing models, `model_ref` the
    concrete model, and the row identity (`id`, stable UUID) names the
    runtime itself. All refs are open strings. `owner_user_id` is always
    server-derived. `machine_id` is optional: local/attached runtimes point
    at an owned machine, remote/cloud runtimes leave it null — one
    abstraction, no per-locus architecture. `capabilities` are declared
    (`capability_source`) and feed the pure `check_compatibility` matcher;
    `unknown != compatible` still holds — a model name never proves a
    capability. No secret field exists by construction."""

    id: UUID
    owner_user_id: UUID
    machine_id: UUID | None = None
    harness_ref: str | None = Field(default=None, min_length=1, max_length=200)
    provider_ref: str | None = Field(default=None, min_length=1, max_length=200)
    model_ref: str | None = Field(default=None, min_length=1, max_length=200)
    capabilities: RuntimeCapabilities = RuntimeCapabilities()
    capability_source: CapabilitySource = CapabilitySource.DECLARED
    runtime_metadata: dict[str, object] = {}
    status: RuntimeStatus = RuntimeStatus.ACTIVE
    created_at: datetime
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_registry_row(self) -> RuntimeRegistration:
        if (
            self.machine_id is None
            and self.harness_ref is None
            and self.provider_ref is None
            and self.model_ref is None
        ):
            raise ValueError("at least one of machine_id, harness_ref, provider_ref, model_ref")
        for name in ("harness_ref", "provider_ref", "model_ref"):
            _open_ref(getattr(self, name), where=name)
        _reject_secret_metadata(self.runtime_metadata, where="runtime_metadata")
        return self


class RuntimeRegistrationCreate(ContractModel):
    """Registers one runtime. `owner_user_id` is never accepted (server
    derives it from the authenticated principal); `status` is always
    `active` at creation (revocation is a separate explicit operation).
    Only `declared` capabilities exist in P6 — any other source is
    fail-closed until defined."""

    machine_id: UUID | None = None
    harness_ref: str | None = Field(default=None, min_length=1, max_length=200)
    provider_ref: str | None = Field(default=None, min_length=1, max_length=200)
    model_ref: str | None = Field(default=None, min_length=1, max_length=200)
    capabilities: RuntimeCapabilities = RuntimeCapabilities()
    capability_source: CapabilitySource = CapabilitySource.DECLARED
    runtime_metadata: dict[str, object] = {}

    @model_validator(mode="after")
    def _validate_registry_create(self) -> RuntimeRegistrationCreate:
        if (
            self.machine_id is None
            and self.harness_ref is None
            and self.provider_ref is None
            and self.model_ref is None
        ):
            raise ValueError("at least one of machine_id, harness_ref, provider_ref, model_ref")
        if self.capability_source != CapabilitySource.DECLARED:
            raise ValueError("only declared capabilities are supported")
        for name in ("harness_ref", "provider_ref", "model_ref"):
            _open_ref(getattr(self, name), where=name)
        _reject_secret_metadata(self.runtime_metadata, where="runtime_metadata")
        return self


class RuntimeRegistrationUpdate(ContractModel):
    """Mutates the descriptors of one runtime without rotating its identity:
    changing capabilities (or refs) never creates a new runtime — `id` is
    the stable     identity, refs are mutable descriptors. Every field is
    optional; omitted fields are left untouched. `machine_id` can be
    attached or moved (a value sets a new locus); detaching uses the
    explicit `detach_machine` flag — an omitted `machine_id` (`None`)
    means "leave untouched", never "detach" — because the model cannot
    distinguish omitted from explicit `null`. The target machine must
    still be owned by the caller. `expected_version` (service call) guards
    against stale writes (409)."""

    machine_id: UUID | None = None
    detach_machine: bool = False
    harness_ref: str | None = Field(default=None, min_length=1, max_length=200)
    provider_ref: str | None = Field(default=None, min_length=1, max_length=200)
    model_ref: str | None = Field(default=None, min_length=1, max_length=200)
    capabilities: RuntimeCapabilities | None = None
    runtime_metadata: dict[str, object] | None = None

    @model_validator(mode="after")
    def _validate_registry_update(self) -> RuntimeRegistrationUpdate:
        for name in ("harness_ref", "provider_ref", "model_ref"):
            _open_ref(getattr(self, name), where=name)
        if self.runtime_metadata is not None:
            _reject_secret_metadata(self.runtime_metadata, where="runtime_metadata")
        return self


class RuntimeTarget(ContractModel):
    """A concrete, non-secret runtime choice.

    Two shapes, never mixed at input (P6/DEC-0070): either `runtime_id`
    references a registered runtime (canonical — identity, refs and
    capabilities then come from the Registry) or the inline anchors
    (`machine_id`, `harness_ref`, `provider_ref`, `model_ref`,
    `capabilities`) carry the choice directly (P4 legacy, still valid).
    The input exclusivity is enforced service-side (`invalid_runtime_binding`):
    the *resolved* effective target legitimately carries both the
    `runtime_id` (provenance) and the registry-resolved fields.
    Open references only: an owned machine locus, abstract harness/provider/model
    labels (same status as agent observability metadata — never a vendor
    catalog, never a whitelist), and a capability snapshot used for
    compatibility checks. No secret field exists on this model by
    construction: there is nowhere to put an API key, token or credential.
    At least one anchor is required."""

    runtime_id: UUID | None = None
    machine_id: UUID | None = None
    harness_ref: str | None = Field(default=None, min_length=1, max_length=200)
    provider_ref: str | None = Field(default=None, min_length=1, max_length=200)
    model_ref: str | None = Field(default=None, min_length=1, max_length=200)
    capabilities: RuntimeCapabilities = RuntimeCapabilities()

    @model_validator(mode="after")
    def _require_anchor(self) -> RuntimeTarget:
        if (
            self.runtime_id is None
            and self.machine_id is None
            and self.harness_ref is None
            and self.provider_ref is None
            and self.model_ref is None
        ):
            raise ValueError(
                "at least one of runtime_id, machine_id, harness_ref, provider_ref, model_ref"
            )
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
