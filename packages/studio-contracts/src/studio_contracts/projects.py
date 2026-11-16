from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel


class Project(VersionedModel):
    id: UUID
    slug: str
    name: str
    description: str | None = None
    archived: bool = False
    repositories: list[str] = Field(default_factory=list)


class ProjectRead(Project):
    """Read shape of a project: `Project` plus the normalized remote URLs
    linked to it (`project_repositories`, Bloc A). Empty when none linked."""


class ProjectRepositoryCreate(ContractModel):
    """Link a remote repository to a project: any URL form is accepted, the
    server normalizes it via `studio_contracts.repositories.normalize_remote_url`
    (invalid URL: 422)."""

    url: str


class ProjectRepository(ContractModel):
    """One normalized remote URL linked to a project. `url` is the canonical
    form (globally unique: one URL belongs to at most one project)."""

    project_id: UUID
    url: str
    created_at: datetime
    created_by: UUID | None = None


class ProjectCreate(IdempotentCreate):
    slug: str
    name: str
    description: str | None = None


class ProjectMember(ContractModel):
    """A User's access to a project: granted or removed, never
    modified — hence no `version`. `granted_by_user_id` is null only for the
    migration backfill. `user_display_name` and `user_email` are read-only
    conveniences resolved from the member's User."""

    project_id: UUID
    user_id: UUID
    granted_by_user_id: UUID | None = None
    created_at: datetime
    user_display_name: str | None = None
    user_email: str | None = None
