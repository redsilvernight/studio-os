from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import LocalWorkspaceConfig

from studio_workspaces.daemon_config import WatchPlan, daemon_watch_plan
from studio_workspaces.root_confirmation import RootConfirmationService
from studio_workspaces.store import WorkspaceStore


@dataclass(frozen=True)
class WorkspaceWatchEntry:
    workspace_id: UUID
    project_id: UUID
    plan: WatchPlan


WatchSource = Callable[[ProfileRef], list[WorkspaceWatchEntry]]
ConfigSource = Callable[[ProfileRef], list[LocalWorkspaceConfig]]


def registry_watch_source(registry_dir: Path) -> WatchSource:
    store = WorkspaceStore(registry_dir, RootConfirmationService())

    def source(profile: ProfileRef) -> list[WorkspaceWatchEntry]:
        return [
            WorkspaceWatchEntry(config.workspace_id, config.project_id, daemon_watch_plan(config))
            for config in store.list_workspaces(profile)
        ]

    return source


def registry_config_source(registry_dir: Path) -> ConfigSource:
    """The full stored configuration of each workspace of a profile, for the
    daemon's local features. Reads only the machine-local registry — never the
    server, never the repository."""
    store = WorkspaceStore(registry_dir, RootConfirmationService())

    def source(profile: ProfileRef) -> list[LocalWorkspaceConfig]:
        return list(store.list_workspaces(profile))

    return source
