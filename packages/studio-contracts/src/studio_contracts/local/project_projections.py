from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from studio_contracts.local.common import LocalContractModel, RelativePath, UtcDatetime


class PendingProjectionFile(LocalContractModel):
    path: RelativePath
    state: Literal["absent", "obsolete", "modified"]


class PendingProjectionUpdate(LocalContractModel):
    """A project-scope Library change waiting for confirmation in one workspace
    repository. The repository is identified by its workspace, never by a path."""

    workspace_id: UUID
    project_id: UUID
    files: list[PendingProjectionFile] = Field(default=[], max_length=500)
    checked_at: UtcDatetime


class ProjectProjectionsStatus(LocalContractModel):
    updates: list[PendingProjectionUpdate] = Field(default=[], max_length=32)


class ProjectProjectionsApplyRequest(LocalContractModel):
    """Bound to one pending update by workspace; nothing is written without an
    explicit confirmation."""

    workspace_id: UUID
    confirmed: Literal[True]


class ProjectProjectionsApplyResult(LocalContractModel):
    workspace_id: UUID
    written: list[RelativePath] = Field(default=[], max_length=500)
    ignored: list[RelativePath] = Field(default=[], max_length=500)
