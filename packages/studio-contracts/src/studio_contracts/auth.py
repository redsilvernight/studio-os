from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

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
    condition, never read to make a decision."""

    id: UUID
    machine_id: UUID | None = None
    display_name: str
    agent_kind: str
    agent_profile: str | None = None
    harness: str | None = None
    provider: str | None = None
    model: str | None = None


class AgentCreate(IdempotentCreate):
    """Public registration of a provenance identity: `machine_id` is always
    derived from the authenticated machine, never client-supplied.
    `display_name` and `agent_kind` are free-form metadata — never
    authorization inputs, never the canonical identity (the
    server-generated `Agent.id` is). `agent_profile`, `harness`, `provider`
    and `model` are optional open-string observability metadata: any value
    is accepted, unknown values are never rejected, and none of them is ever
    required."""

    display_name: str
    agent_kind: str = ""
    agent_profile: str | None = None
    harness: str | None = None
    provider: str | None = None
    model: str | None = None


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


class HeartbeatRequest(ContractModel):
    machine_id: UUID
    agent_id: UUID | None = None
    client_timestamp: datetime


class HeartbeatResponse(ContractModel):
    machine_id: UUID
    status: MachineStatus
    last_seen_at: datetime
    server_timestamp: datetime
