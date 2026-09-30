from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel


class Role(StrEnum):
    """Account roles, weakest to strongest: `readonly` (reads plus heartbeat
    and self-service of its own machines, no business writes); `agent`
    (writes, but never project, machine or user provisioning); `developer`
    (writes, plus project creation); `admin` (everything, including
    machine/user provisioning for any user and work review resolution).
    The role always belongs to the machine owner's user, never to a
    harness, provider, model or profile."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    AGENT = "agent"
    READONLY = "readonly"


class MachineStatus(StrEnum):
    ONLINE = "online"
    IDLE = "idle"
    OFFLINE = "offline"


class AccountStatus(StrEnum):
    """Derived, never stored: `disabled` when `disabled_at` is set, else
    `pending` while `email_verified_at` is null, else `active`. Only an
    `active` account gets a principal; the state is orthogonal to project
    access."""

    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


class User(VersionedModel):
    """`email` is normalized (trimmed, lower-case) and unique regardless of
    case."""

    id: UUID
    display_name: str
    email: str
    role: Role
    status: AccountStatus = AccountStatus.ACTIVE
    email_verified_at: datetime | None = None
    disabled_at: datetime | None = None


class Machine(VersionedModel):
    """A machine owns its own revocable credential: an opaque token whose
    hash alone is stored server-side, so a leaked database never leaks
    access."""

    id: UUID
    owner_user_id: UUID
    display_name: str
    last_seen_at: datetime | None = None
    status: MachineStatus = MachineStatus.OFFLINE


class Agent(VersionedModel):
    """Provenance identity attached to one machine: who did the work, for
    audit and attribution. Never an authorization input — permissions come
    from the machine owner's role alone. `agent_profile`, `harness`,
    `provider` and `model` are optional additive observability metadata:
    open strings, never whitelisted, never a capability or compatibility
    condition, never read to make a decision. `stable_key` (AIB-I, additive)
    is the local stable key set by `agents ensure` (default
    `agents-ensure-{harness}`), unique per owning machine: the idempotent
    lookup key for session-start, never an authorization input, and never
    `AgentDefinition.stable_key` (a resolution parameter, not an identity)."""

    id: UUID
    machine_id: UUID | None = None
    display_name: str
    agent_kind: str
    agent_profile: str | None = None
    harness: str | None = None
    provider: str | None = None
    model: str | None = None
    stable_key: str | None = None


class AgentCreate(IdempotentCreate):
    """Public registration of a provenance identity: `machine_id` is always
    derived from the authenticated machine, never client-supplied.
    `display_name` and `agent_kind` are free-form metadata — never
    authorization inputs, never the canonical identity (the
    server-generated `Agent.id` is). `agent_profile`, `harness`, `provider`
    and `model` are optional open-string observability metadata: any value
    is accepted, unknown values are never rejected, and none of them is ever
    required. `stable_key` (AIB-I, additive, optional) is the local stable
    key for `POST /agents/ensure`: same machine + same key returns the
    existing agent, same key + different metadata is `409
    idempotency_key_payload_mismatch`. Never `AgentDefinition.stable_key`."""

    display_name: str
    agent_kind: str = ""
    agent_profile: str | None = None
    harness: str | None = None
    provider: str | None = None
    model: str | None = None
    stable_key: str | None = None


class AgentEnsureResult(ContractModel):
    """Result of `POST /agents/ensure` (AIB-I, additive): the caller's own
    machine's agent for `stable_key`, plus whether this call created it."""

    agent: Agent
    created: bool


class UserCreate(ContractModel):
    """Admin-only, non-replayable — no `Idempotency-Key` support, unlike
    task/claim/decision/transfer/project creation (a replayable user
    creation would persist sensitive material)."""

    display_name: str
    email: str
    role: Role = Role.DEVELOPER


class MachineCreate(ContractModel):
    """`owner_user_id` is optional (A5): absent, the machine belongs to the
    caller's own User. A non-admin may only name itself — the server never
    lets it choose another owner, and never looks that other User up. Only
    `admin` provisions a machine for someone else."""

    owner_user_id: UUID | None = None
    display_name: str


class MachineCreated(Machine):
    """Returned once, at creation time: the opaque credential in clear text.
    Never retrievable again afterwards — only its hash is stored."""

    credential: str


CapabilityToken = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")]
"""Opaque identifier or version string: no separator, whitespace or drive
letter, so a filesystem path cannot be represented."""


class HarnessReport(ContractModel):
    """One harness as reported by a machine (AIB R1, DEC-0171 extends the
    e1963627 report): `detected` (tool present) vs `configured` (wired for
    Studio OS). IDs and stable tokens only: never a path, secret,
    fingerprint or file listing."""

    harness_id: CapabilityToken
    version: CapabilityToken | None = None
    detected: bool = False
    configured: bool = False


class MachineCapabilities(ContractModel):
    """Machine-reported launch aptitude (AIB R1, additive). Ids only - never a
    path, hostname or secret. The server stores the latest report with its
    reception time and never presents a stale one as current."""

    harnesses: list[HarnessReport] = Field(default_factory=list, max_length=32)
    project_ids: list[UUID] = Field(default_factory=list, max_length=256)
    accepts_launches: bool = False
    running_launches: int = Field(default=0, ge=0)
    max_launches: int = Field(default=0, ge=0)


class HeartbeatRequest(ContractModel):
    """`capabilities` is optional and additive: absent, the previous report
    is kept untouched."""

    machine_id: UUID
    agent_id: UUID | None = None
    client_timestamp: datetime
    capabilities: MachineCapabilities | None = None


class HeartbeatResponse(ContractModel):
    machine_id: UUID
    status: MachineStatus
    last_seen_at: datetime
    server_timestamp: datetime
    capabilities: MachineCapabilities | None = None


class IneligibilityReason(StrEnum):
    """Deterministic, evaluated in this declaration order."""

    OFFLINE = "offline"
    NO_CAPABILITIES_REPORT = "no_capabilities_report"
    CAPABILITIES_STALE = "capabilities_stale"
    OWNER_NO_PROJECT_ACCESS = "owner_no_project_access"
    PROJECT_NOT_REGISTERED = "project_not_registered"
    LAUNCHES_NOT_ACCEPTED = "launches_not_accepted"
    HARNESS_INCOMPATIBLE = "harness_incompatible"
    AT_CAPACITY = "at_capacity"


class MachineEligibility(ContractModel):
    machine_id: UUID
    display_name: str
    status: MachineStatus
    eligible: bool
    reasons: list[IneligibilityReason] = Field(default_factory=list)
    harnesses: list[HarnessReport] = Field(default_factory=list)
    free_slots: int = 0
    reported_at: datetime | None = None


class EligibleMachines(ContractModel):
    task_id: UUID
    project_id: UUID
    harness_id: CapabilityToken | None = None
    machines: list[MachineEligibility]
