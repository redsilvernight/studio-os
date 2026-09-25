from __future__ import annotations

from datetime import datetime
from uuid import UUID

from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel


class Project(VersionedModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    archived: bool = False


class ProjectCreate(IdempotentCreate):
    slug: str
    name: str
    description: str | None = None


class ProjectMember(ContractModel):
    """A User's access to a project: granted or removed, never
    modified — hence no `version`. `granted_by_user_id` is null only for the
    migration backfill."""

    project_id: UUID
    user_id: UUID
    granted_by_user_id: UUID | None = None
    created_at: datetime
