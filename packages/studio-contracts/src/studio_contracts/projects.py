from __future__ import annotations

from uuid import UUID

from studio_contracts.common import IdempotentCreate, VersionedModel


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
