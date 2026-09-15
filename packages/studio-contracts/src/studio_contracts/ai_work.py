from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate


class AIWorkStatus(StrEnum):
    """Work entry lifecycle. `approved` and `changes_requested` are the only
    valid exits from `review_requested`, and only a privileged role may set
    them — never the owning agent or machine (nobody approves their own
    work)."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    REVIEW_REQUESTED = "review_requested"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class AIWorkLog(ContractModel):
    """A work entry. `agent_profile`, `harness`, `provider` and `model` are
    optional additive observability metadata — open strings snapshotting the
    runtime that produced the work, never whitelisted, never an
    authorization or capability input."""

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
    agent_profile: str | None = None
    harness: str | None = None
    provider: str | None = None
    model: str | None = None


class AIWorkLogCreate(IdempotentCreate):
    task_id: UUID | None = None
    project_id: UUID
    agent_id: UUID
    machine_id: UUID | None = None
    summary: str
    agent_profile: str | None = None
    harness: str | None = None
    provider: str | None = None
    model: str | None = None


class AIWorkLogUpdate(ContractModel):
    summary: str | None = None
    status: AIWorkStatus | None = None
    changed_files: list[str] | None = None
    tests_run: list[str] | None = None
