from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.local.common import (
    ComponentId,
    GlobPattern,
    Identifier,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
    OpaqueId,
    RelativePath,
    UtcDatetime,
    WorkspaceRootPath,
)
from studio_contracts.local.identity import ProfileRef, SecretReference

WORKSPACE_CONFIG_SCHEMA_VERSION = 1
WORKSPACE_CONFIG_USER_RELATIVE_PATH = "workspaces/{workspace_id}.json"
WORKSPACE_MARKER_RELATIVE_PATH = ".studio/workspace.json"
WORKSPACE_CONFIG_BACKUP_SUFFIX = ".bak"


class RepoRoot(LocalContractModel):
    name: Identifier
    path: WorkspaceRootPath


class WorkspaceRoots(LocalContractModel):
    workspace_root: WorkspaceRootPath
    repo_roots: list[RepoRoot] = Field(default=[], max_length=32)

    @model_validator(mode="after")
    def _unique_repos(self) -> Self:
        names = [repo.name for repo in self.repo_roots]
        if len(set(names)) != len(names):
            raise ValueError("repo root names must be unique")
        return self


class LocalFeatures(LocalContractModel):
    """Every optional local capability is off until the workspace turns it on."""

    knowledge: bool = False
    code_graph: bool = False
    harness: bool = False
    watchers: bool = False


class IndexLocation(LocalContractModel):
    """Where a derived index is stored, always inside the daemon's own cache
    directory and addressed by workspace and provider — never by an arbitrary
    path."""

    scope: Literal["workspace_cache"] = "workspace_cache"
    directory_name: Identifier


class KnowledgeConfig(LocalContractModel):
    provider_id: Identifier
    content_root: RelativePath
    index: IndexLocation
    include_globs: list[GlobPattern] = Field(default=["**/*.md"], max_length=32)
    exclude_globs: list[GlobPattern] = Field(default=[], max_length=64)
    integrations: list[Identifier] = Field(default=[], max_length=8)


class CodeGraphConfig(LocalContractModel):
    provider_id: Identifier
    repo_names: list[Identifier] = Field(default=[], max_length=32)
    languages: list[Identifier] = Field(default=[], max_length=32)
    include_globs: list[GlobPattern] = Field(default=[], max_length=64)
    exclude_globs: list[GlobPattern] = Field(default=[], max_length=64)
    index: IndexLocation


class WatcherConfig(LocalContractModel):
    debounce_ms: int = Field(default=500, ge=50, le=60_000)
    max_events_per_second: int = Field(default=200, ge=1, le=10_000)
    ignore_globs: list[GlobPattern] = Field(default=[".git/**", "node_modules/**"], max_length=64)
    follow_symlinks: Literal[False] = False


class LocalWorkspaceConfig(LocalContractModel):
    """Per-machine workspace configuration. Holds paths and toggles only; every
    credential appears as a SecretReference, so the file is safe to back up and
    to inspect. It is stored outside the repository (see
    WORKSPACE_CONFIG_USER_RELATIVE_PATH) and never synchronised."""

    schema_version: Literal[1] = 1
    workspace_id: UUID
    profile: ProfileRef
    project_id: UUID
    project_slug: Identifier | None = None
    roots: WorkspaceRoots
    features: LocalFeatures = LocalFeatures()
    knowledge: KnowledgeConfig | None = None
    code_graph: CodeGraphConfig | None = None
    watchers: WatcherConfig | None = None
    secret_references: list[SecretReference] = Field(default=[], max_length=8)
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _features_have_config(self) -> Self:
        if self.features.knowledge and self.knowledge is None:
            raise ValueError("knowledge feature enabled without knowledge configuration")
        if self.features.code_graph and self.code_graph is None:
            raise ValueError("code_graph feature enabled without code graph configuration")
        if self.features.watchers and self.watchers is None:
            raise ValueError("watchers feature enabled without watcher configuration")
        if self.code_graph is not None:
            known = {repo.name for repo in self.roots.repo_roots}
            unknown = set(self.code_graph.repo_names) - known
            if unknown:
                raise ValueError(f"code graph references unknown repos: {sorted(unknown)}")
        for reference in self.secret_references:
            if reference.profile != self.profile:
                raise ValueError("secret reference belongs to another profile")
        return self


class WorkspaceMarker(LocalContractModel):
    """Tiny in-repo file that lets a moved workspace be recognised. It carries
    identifiers only — no path, no profile secret."""

    schema_version: Literal[1] = 1
    workspace_id: UUID
    project_id: UUID


class WorkspaceHealth(StrEnum):
    VALID = "valid"
    CONFIG_MISSING = "config_missing"
    CONFIG_INVALID = "config_invalid"
    MOVED = "moved"
    INACCESSIBLE = "inaccessible"
    PROJECT_UNAVAILABLE = "project_unavailable"


class WorkspaceAction(StrEnum):
    NONE = "none"
    CREATE_CONFIG = "create_config"
    REPAIR_CONFIG = "repair_config"
    CONFIRM_RELOCATION = "confirm_relocation"
    GRANT_ACCESS = "grant_access"
    DETACH_WORKSPACE = "detach_workspace"


WORKSPACE_HEALTH_BEHAVIOR: dict[WorkspaceHealth, tuple[LocalErrorCode | None, WorkspaceAction]] = {
    WorkspaceHealth.VALID: (None, WorkspaceAction.NONE),
    WorkspaceHealth.CONFIG_MISSING: (
        LocalErrorCode.WORKSPACE_CONFIG_MISSING,
        WorkspaceAction.CREATE_CONFIG,
    ),
    WorkspaceHealth.CONFIG_INVALID: (
        LocalErrorCode.WORKSPACE_CONFIG_INVALID,
        WorkspaceAction.REPAIR_CONFIG,
    ),
    WorkspaceHealth.MOVED: (LocalErrorCode.WORKSPACE_MOVED, WorkspaceAction.CONFIRM_RELOCATION),
    WorkspaceHealth.INACCESSIBLE: (
        LocalErrorCode.WORKSPACE_INACCESSIBLE,
        WorkspaceAction.GRANT_ACCESS,
    ),
    WorkspaceHealth.PROJECT_UNAVAILABLE: (
        LocalErrorCode.PROJECT_UNAVAILABLE,
        WorkspaceAction.DETACH_WORKSPACE,
    ),
}


class WorkspaceStatus(LocalContractModel):
    """Result of validating a workspace. Anything but `valid` disables the
    local features of that workspace (fail-closed) and never touches Git or the
    server; the config is never rewritten automatically."""

    workspace_id: UUID
    health: WorkspaceHealth
    action: WorkspaceAction
    config: LocalWorkspaceConfig | None = None
    candidate_root: WorkspaceRootPath | None = None
    error: LocalError | None = None

    @model_validator(mode="after")
    def _matches_behavior(self) -> Self:
        code, action = WORKSPACE_HEALTH_BEHAVIOR[self.health]
        if self.action is not action:
            raise ValueError(f"health {self.health.value} implies action {action.value}")
        if code is None:
            if self.error is not None or self.config is None:
                raise ValueError("a valid workspace has a config and no error")
            return self
        if self.error is None or self.error.code is not code:
            raise ValueError(f"health {self.health.value} requires error {code.value}")
        if self.error.component is not ComponentId.WORKSPACE:
            raise ValueError("workspace errors are reported by the workspace component")
        if self.health is WorkspaceHealth.MOVED and self.candidate_root is None:
            raise ValueError("a moved workspace proposes the candidate root")
        if self.health is not WorkspaceHealth.MOVED and self.candidate_root is not None:
            raise ValueError("only a moved workspace proposes a candidate root")
        return self


class WorkspaceScope(LocalContractModel):
    workspace_id: UUID


class WorkspaceValidateRequest(LocalContractModel):
    workspace_id: UUID


class WorkspaceGetConfigRequest(LocalContractModel):
    workspace_id: UUID


class WorkspaceSaveConfigRequest(LocalContractModel):
    """Changing `roots` requires `root_confirmation_id`, an identifier the daemon
    issues only after a native folder selection confirmed by the user; the
    daemon refuses a root change that carries none."""

    config: LocalWorkspaceConfig
    expected_updated_at: UtcDatetime | None = None
    root_confirmation_id: OpaqueId | None = None


class WorkspaceMigrationPolicy(LocalContractModel):
    """A config older than the daemon's schema is migrated forward with a
    `.bak` copy; a newer one is refused (`workspace_config_invalid`) rather than
    guessed at."""

    current_version: int = WORKSPACE_CONFIG_SCHEMA_VERSION
    oldest_migratable_version: int = 1
    keeps_backup: Literal[True] = True
    refuses_newer: Literal[True] = True


def workspace_config_relative_path(workspace_id: UUID) -> str:
    return WORKSPACE_CONFIG_USER_RELATIVE_PATH.format(workspace_id=workspace_id)
