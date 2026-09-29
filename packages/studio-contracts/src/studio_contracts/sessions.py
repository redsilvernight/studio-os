from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate


class SessionStatus(StrEnum):
    """Presence derived at read time (C1), never stored: `active`
    (recent activity), `idle` (no activity past the idle threshold),
    `expired` (no activity past the expire threshold — L2 closes these),
    `ended` (`ended_at` set). Same pattern as `MachineStatus` from
    `last_seen_at`, but driven by session-attached activity, never by a
    dedicated agent heartbeat."""

    ACTIVE = "active"
    IDLE = "idle"
    EXPIRED = "expired"
    ENDED = "ended"


class WorkSession(ContractModel):
    id: UUID
    task_id: UUID
    machine_id: UUID
    agent_id: UUID | None = None
    started_at: datetime
    ended_at: datetime | None = None
    last_activity_at: datetime | None = None
    sync_cursor_seq: int | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    expires_at: datetime | None = None


class WorkSessionCreate(IdempotentCreate):
    task_id: UUID
    machine_id: UUID
    agent_id: UUID | None = None
