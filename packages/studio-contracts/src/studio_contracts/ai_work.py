from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate


class AIWorkStatus(StrEnum):
    """Mirrors ai_work.* event types in TECH/03_EVENT_CONTRACT.md."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    REVIEW_REQUESTED = "review_requested"


class AIWorkLog(ContractModel):
    id: UUID
    task_id: UUID | None = None
    project_id: UUID
    agent_id: UUID
    machine_id: UUID | None = None
    summary: str
    status: AIWorkStatus = AIWorkStatus.STARTED
    changed_files: list[str] = []
    tests_run: list[str] = []
    started_at: datetime
    ended_at: datetime | None = None


class AIWorkLogCreate(IdempotentCreate):
    task_id: UUID | None = None
    project_id: UUID
    agent_id: UUID
    machine_id: UUID | None = None
    summary: str


class AIWorkLogUpdate(ContractModel):
    summary: str | None = None
    status: AIWorkStatus | None = None
    changed_files: list[str] | None = None
    tests_run: list[str] | None = None
