from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate


class DecisionStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


class Decision(ContractModel):
    """A DEC-XXXX record referenced by AI/01_AI_OPERATING_REFERENCE.md and
    .claude/rules/contracts.md."""

    id: UUID
    readable_id: str
    project_id: UUID | None = None
    task_id: UUID | None = None
    title: str
    body: str
    status: DecisionStatus = DecisionStatus.PROPOSED
    proposed_by_type: str
    proposed_by_id: UUID
    created_at: datetime


class DecisionCreate(IdempotentCreate):
    project_id: UUID | None = None
    task_id: UUID | None = None
    title: str
    body: str
    proposed_by_type: str
    proposed_by_id: UUID
