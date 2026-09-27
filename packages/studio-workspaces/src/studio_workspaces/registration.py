from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from studio_contracts.local.common import LocalErrorCode
from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import (
    LocalWorkspaceConfig,
    WatcherConfig,
    WorkspaceRoots,
    WorkspaceSaveConfigRequest,
)

from studio_workspaces.path_safety import check_readable, workspace_binding_key
from studio_workspaces.root_confirmation import RootConfirmationService
from studio_workspaces.store import WorkspaceStore, WorkspaceStoreError


class RegistrationAction(StrEnum):
    CREATED = "created"
    WATCHERS_ENABLED = "watchers_enabled"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class WorkspaceRegistration:
    config: LocalWorkspaceConfig
    action: RegistrationAction


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def register_workspace(
    registry_dir: Path,
    profile: ProfileRef,
    project_id: UUID,
    path: str,
    *,
    project_slug: str | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> WorkspaceRegistration:
    """Links `path` to `project_id` in the machine-local registry with Git
    watching on, for a caller that already holds the user's explicit choice of
    folder (a project initialisation command line). Idempotent: an existing
    link of the same folder to the same project only gets its watchers turned
    on; a link to another project is refused."""
    verdict = check_readable(path)
    if not verdict.ok or verdict.normalized is None:
        raise WorkspaceStoreError(LocalErrorCode.WORKSPACE_INACCESSIBLE, verdict.reason)
    root = verdict.normalized
    confirmations = RootConfirmationService()
    store = WorkspaceStore(registry_dir, confirmations)
    wanted = workspace_binding_key(root)
    for existing in store.list_workspaces(profile):
        if workspace_binding_key(existing.roots.workspace_root) != wanted:
            continue
        if existing.project_id != project_id:
            raise WorkspaceStoreError(
                LocalErrorCode.INVALID_REQUEST,
                "this folder is already linked to another project",
            )
        return _enable_watchers(store, profile, existing, now)

    roots = WorkspaceRoots(workspace_root=root)
    stamp = now()
    config = LocalWorkspaceConfig(
        workspace_id=uuid4(),
        profile=profile,
        project_id=project_id,
        project_slug=project_slug,
        roots=roots,
        created_at=stamp,
        updated_at=stamp,
    )
    request = WorkspaceSaveConfigRequest(
        config=config, current_roots=None, root_confirmation_id=confirmations.issue(roots)
    )
    return WorkspaceRegistration(store.create(request, profile), RegistrationAction.CREATED)


def _enable_watchers(
    store: WorkspaceStore,
    profile: ProfileRef,
    existing: LocalWorkspaceConfig,
    now: Callable[[], datetime],
) -> WorkspaceRegistration:
    if existing.features.watchers and existing.watchers is not None:
        return WorkspaceRegistration(existing, RegistrationAction.UNCHANGED)
    updated = existing.model_copy(
        update={
            "features": existing.features.model_copy(update={"watchers": True}),
            "watchers": existing.watchers or WatcherConfig(),
            "updated_at": now(),
        }
    )
    request = WorkspaceSaveConfigRequest(
        config=LocalWorkspaceConfig.model_validate(updated.model_dump()),
        current_roots=existing.roots,
        expected_updated_at=existing.updated_at,
    )
    return WorkspaceRegistration(store.save(request, profile), RegistrationAction.WATCHERS_ENABLED)
