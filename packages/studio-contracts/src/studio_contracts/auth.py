from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, VersionedModel


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


class HeartbeatRequest(ContractModel):
    machine_id: UUID
    agent_id: UUID | None = None
    client_timestamp: datetime


class HeartbeatResponse(ContractModel):
    machine_id: UUID
    status: MachineStatus
    last_seen_at: datetime
    server_timestamp: datetime
