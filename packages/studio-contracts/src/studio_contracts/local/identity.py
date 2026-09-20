from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import model_validator

from studio_contracts.local.common import (
    ComponentId,
    Identifier,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
    OpaqueId,
    ServerOrigin,
    ShortText,
    UtcDatetime,
)


class ProfileRef(LocalContractModel):
    """A local profile is one server origin on one machine. Two profiles never
    share a secret, an outbox partition or a daemon instance."""

    profile_id: Identifier
    server_origin: ServerOrigin


class HumanIdentity(LocalContractModel):
    """The person using the Desktop. Authenticated by a short-lived session
    that lives in the renderer/dashboard; its credential is never part of any
    local contract."""

    user_id: UUID
    display_name: ShortText
    profile: ProfileRef
    session_expires_at: UtcDatetime | None = None


class MachineIdentity(LocalContractModel):
    """The registered machine the daemon acts as. Its credential is held by the
    daemon through a SecretReference and never crosses the bridge."""

    machine_id: UUID
    machine_name: ShortText
    profile: ProfileRef
    registered_at: UtcDatetime


class SecretKind(StrEnum):
    MACHINE_CREDENTIAL = "machine_credential"


class SecretStore(StrEnum):
    OS_KEYRING = "os_keyring"
    PROCESS_ENVIRONMENT = "process_environment"


class SecretStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    INACCESSIBLE = "inaccessible"
    REVOKED = "revoked"
    WRONG_PROFILE = "wrong_profile"
    KEYRING_UNAVAILABLE = "keyring_unavailable"


SECRET_STATUS_ERROR: dict[SecretStatus, LocalErrorCode] = {
    SecretStatus.ABSENT: LocalErrorCode.SECRET_ABSENT,
    SecretStatus.INACCESSIBLE: LocalErrorCode.SECRET_INACCESSIBLE,
    SecretStatus.REVOKED: LocalErrorCode.SECRET_REVOKED,
    SecretStatus.WRONG_PROFILE: LocalErrorCode.WRONG_PROFILE,
    SecretStatus.KEYRING_UNAVAILABLE: LocalErrorCode.KEYRING_UNAVAILABLE,
}


class SecretReference(LocalContractModel):
    """Names where a secret lives; carries no secret material. `ref_id` is an
    opaque local handle, `lookup_key` is the store-side entry name."""

    ref_id: OpaqueId
    kind: SecretKind
    store: SecretStore
    lookup_key: OpaqueId
    profile: ProfileRef


class SecretReferenceStatus(LocalContractModel):
    reference: SecretReference
    status: SecretStatus
    checked_at: UtcDatetime
    error: LocalError | None = None

    @model_validator(mode="after")
    def _error_matches_status(self) -> Self:
        if self.status is SecretStatus.PRESENT:
            if self.error is not None:
                raise ValueError("a present secret carries no error")
            return self
        if self.error is None:
            raise ValueError(f"secret status {self.status.value} requires a structured error")
        if self.error.code is not SECRET_STATUS_ERROR[self.status]:
            raise ValueError("error code does not match secret status")
        if self.error.component is not ComponentId.SECRET_STORE:
            raise ValueError("secret errors are reported by the secret_store component")
        return self


class IdentityView(LocalContractModel):
    """Everything the renderer may know about identity: who, on which machine,
    and whether the secrets behind them are usable — never the secrets."""

    profile: ProfileRef
    human: HumanIdentity | None = None
    machine: MachineIdentity | None = None
    secrets: list[SecretReferenceStatus] = []

    @model_validator(mode="after")
    def _single_profile(self) -> Self:
        for identity in (self.human, self.machine):
            if identity is not None and identity.profile != self.profile:
                raise ValueError("identity belongs to a different profile")
        for entry in self.secrets:
            if entry.reference.profile != self.profile and entry.status not in (
                SecretStatus.WRONG_PROFILE,
            ):
                raise ValueError("secret belongs to a different profile")
        return self


class IdentityBinding(LocalContractModel):
    """The identity a piece of queued local work was created under. An outbox
    entry replays only under an identical binding."""

    server_origin: ServerOrigin
    profile_id: Identifier
    machine_id: UUID
    project_id: UUID | None = None
    workspace_id: UUID | None = None


def partition_key(binding: IdentityBinding) -> str:
    """Stable outbox partition and single-instance key: server, profile and
    machine only — project/workspace scoping is checked per entry."""
    material = "\n".join((binding.server_origin, binding.profile_id, str(binding.machine_id)))
    return hashlib.sha256(material.encode()).hexdigest()


def binding_mismatches(entry: IdentityBinding, active: IdentityBinding) -> list[str]:
    mismatched = [
        name
        for name in ("server_origin", "profile_id", "machine_id")
        if getattr(entry, name) != getattr(active, name)
    ]
    for name in ("project_id", "workspace_id"):
        entry_value = getattr(entry, name)
        if entry_value is not None and entry_value != getattr(active, name):
            mismatched.append(name)
    return mismatched
