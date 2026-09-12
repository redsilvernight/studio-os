from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate


class ResourceType(StrEnum):
    FILE = "file"
    FOLDER = "folder"


class ClaimStatus(StrEnum):
    """A claim past `expires_at` is not active regardless of stored status —
    see .claude/rules/database.md. It is a soft lock: it warns, it never
    blocks a Git operation or a file write."""

    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class ResourceClaim(ContractModel):
    id: UUID
    project_id: UUID
    task_id: UUID | None = None
    resource_path: str
    resource_type: ResourceType
    claimed_by_machine_id: UUID
    claimed_by_agent_id: UUID | None = None
    status: ClaimStatus = ClaimStatus.ACTIVE
    ttl_seconds: int
    created_at: datetime
    renewed_at: datetime | None = None
    expires_at: datetime
    released_at: datetime | None = None


class ResourceClaimCreate(IdempotentCreate):
    project_id: UUID
    task_id: UUID | None = None
    resource_path: str
    resource_type: ResourceType
    ttl_seconds: int
