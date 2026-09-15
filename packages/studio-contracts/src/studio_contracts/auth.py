from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel


class Role(StrEnum):
    """Minimum role set per TECH/04_AUTH_SYNC_CONTRACT.md."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    AGENT = "agent"
    READONLY = "readonly"


class MachineStatus(StrEnum):
    ONLINE = "online"
    IDLE = "idle"
    OFFLINE = "offline"


class User(VersionedModel):
    id: UUID
    display_name: str
    email: str
    role: Role


class Machine(VersionedModel):
    """A machine owns its own revocable credential (DEC-0003: opaque token,
    hashed server-side — see docs/DECISIONS.md)."""

    id: UUID
    owner_user_id: UUID
    display_name: str
    last_seen_at: datetime | None = None
    status: MachineStatus = MachineStatus.OFFLINE


class Agent(VersionedModel):
    """Keeps its own logical identity even when running under a machine's
    context (TECH/04_AUTH_SYNC_CONTRACT.md)."""

    id: UUID
    machine_id: UUID | None = None
    display_name: str
    agent_kind: str


class AgentCreate(IdempotentCreate):
    """Public registration of an operational provenance identity (CC-1,
    `TECH/02_API_CONTRACT.md`): `machine_id` is always derived from the
    authenticated machine, never client-supplied. `display_name` and
    `agent_kind` are free-form metadata — never authorization inputs, never
    the canonical identity (the server-generated `Agent.id` is)."""

    display_name: str
    agent_kind: str = ""


class UserCreate(ContractModel):
    """Admin-only, non-replayable (DEC-0011/DEC-0012) — no `Idempotency-Key`
    support, unlike task/claim/decision/transfer/project creation."""

    display_name: str
    email: str
    role: Role = Role.DEVELOPER


class MachineCreate(ContractModel):
    owner_user_id: UUID
    display_name: str


class MachineCreated(Machine):
    """Returned once, at creation time: the opaque credential in clear text.
    Never retrievable again afterwards — only its hash is stored (DEC-0003)."""

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
