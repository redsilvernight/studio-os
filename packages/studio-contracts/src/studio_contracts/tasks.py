from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel


class TaskStatus(StrEnum):
    """Mirrors the task.* event types in TECH/03_EVENT_CONTRACT.md."""

    CREATED = "created"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class Task(VersionedModel):
    id: UUID
    readable_id: str | None = None
    project_id: UUID
    title: str
    description: str | None = None
    status: TaskStatus = TaskStatus.CREATED
    claimed_by_machine_id: UUID | None = None
    claimed_by_agent_id: UUID | None = None


class TaskCreate(IdempotentCreate):
    project_id: UUID
    title: str
    description: str | None = None


class TaskUpdate(ContractModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
