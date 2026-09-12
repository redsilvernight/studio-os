from __future__ import annotations

from datetime import datetime
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate


class WorkSession(ContractModel):
    id: UUID
    task_id: UUID
    machine_id: UUID
    agent_id: UUID | None = None
    started_at: datetime
    ended_at: datetime | None = None


class WorkSessionCreate(IdempotentCreate):
    task_id: UUID
    machine_id: UUID
    agent_id: UUID | None = None
