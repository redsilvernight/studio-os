from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from studio_contracts.local.common import LocalErrorCode
from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import (
    DetectedRepositoryListResult,
    DetectedRepositoryView,
    GitState,
    LocalWorkspaceConfig,
    WorkspaceConfirmRootsRequest,
    WorkspaceConfirmRootsResult,
    WorkspaceGitStatus,
    WorkspaceListResult,
    WorkspaceSaveConfigRequest,
    WorkspaceScope,
    WorkspaceStatus,
)
from studio_contracts.repositories import normalize_remote_url

from studio_workspaces.detected import (
    forget_detected_repository,
    list_detected_repositories,
)
from studio_workspaces.git_detection import detect_git
from studio_workspaces.path_safety import check_readable
from studio_workspaces.root_confirmation import RootConfirmationService
from studio_workspaces.store import ProjectAvailable, WorkspaceStore, WorkspaceStoreError


class WorkspaceBridge:
    """Serve the P1 `workspace.*` commands from the machine-local registry.

    The bridge owns both the `WorkspaceStore` and the `RootConfirmationService`
    it was given, so a confirmation id issued by `confirm_roots` is always
    meaningful to the store that consumes it in `save_config`. Profiles,
    secrets and paths are enforced by the store and the P1 models themselves;
    this layer only maps store failures to their `LocalErrorCode` untouched, so
    the daemon can shape the bridge error without ever seeing a path.
    """

    def __init__(
        self,
        registry_dir: Path,
        confirmations: RootConfirmationService,
        project_available: ProjectAvailable = lambda _project_id: True,  # noqa: E731
    ) -> None:
        self._registry_dir = registry_dir
        self._store = WorkspaceStore(
            registry_dir, confirmations, project_available=project_available
        )
        self._confirmations = confirmations

    def validate(self, workspace_id: UUID, profile: ProfileRef) -> WorkspaceStatus:
        return self._store.validate(workspace_id, profile)

    def list(self, profile: ProfileRef) -> WorkspaceListResult:
        return WorkspaceListResult(
            items=[
                self._store.validate(config.workspace_id, profile).model_copy(
                    update={"config": config}
                )
                for config in self._store.list_workspaces(profile)
            ]
        )

    def list_detected(self, profile: ProfileRef) -> DetectedRepositoryListResult:
        """Repositories `resolve_workspace` saw but no workspace follows yet.

        Only entries of the active server origin, already followed folders
        excluded, remotes re-normalised (an invalid one is dropped, never
        stored), most recently seen first. Never raises for a bad entry:
        this registry is observability, not source of truth."""
        from pydantic import ValidationError

        from studio_workspaces.path_safety import workspace_binding_key

        followed = {
            workspace_binding_key(path)
            for config in self._store.all_workspaces()
            for path in (
                [config.roots.workspace_root] + [repo.path for repo in config.roots.repo_roots]
            )
        }
        items: list[DetectedRepositoryView] = []
        for entry in list_detected_repositories(self._registry_dir, profile):
            if workspace_binding_key(entry.root) in followed:
                continue
            remotes: list[str] = []
            for remote in entry.remotes:
                try:
                    normalized = normalize_remote_url(remote)
                except ValueError:
                    continue
                if normalized not in remotes:
                    remotes.append(normalized)
            try:
                items.append(
                    DetectedRepositoryView(
                        root=entry.root,
                        remotes=remotes,
                        reason=entry.reason,
                        last_seen_at=entry.last_seen_at,
                    )
                )
            except ValidationError:
                continue
        return DetectedRepositoryListResult(items=items)

    def get_config(self, workspace_id: UUID, profile: ProfileRef) -> LocalWorkspaceConfig:
        return self._store.load(workspace_id, profile)

    def save(
        self, request: WorkspaceSaveConfigRequest, profile: ProfileRef
    ) -> LocalWorkspaceConfig:
        try:
            self._store.load(request.config.workspace_id, profile)
        except WorkspaceStoreError as exc:
            if exc.code is not LocalErrorCode.WORKSPACE_CONFIG_MISSING:
                raise
            created = self._store.create(request, profile)
            self._forget_detected(profile, created.roots.workspace_root)
            return created
        saved = self._store.save(request, profile)
        self._forget_detected(profile, saved.roots.workspace_root)
        return saved

    def _forget_detected(self, profile: ProfileRef, root: str) -> None:
        """A followed repository leaves the detected list: `save_config` is
        the dashboard's link gesture, so the entry must not linger."""
        try:
            forget_detected_repository(self._registry_dir, profile, root)
        except OSError:
            pass

    def confirm(self, request: WorkspaceConfirmRootsRequest) -> WorkspaceConfirmRootsResult:
        verdict = check_readable(request.roots.workspace_root)
        if not verdict.ok:
            raise WorkspaceStoreError(
                LocalErrorCode.WORKSPACE_INACCESSIBLE, "workspace roots are not accessible"
            )
        for repo in request.roots.repo_roots:
            verdict = check_readable(repo.path)
            if not verdict.ok:
                raise WorkspaceStoreError(
                    LocalErrorCode.WORKSPACE_INACCESSIBLE, "workspace roots are not accessible"
                )
        confirmation_id = self._confirmations.issue(request.roots)
        # The contract bounds the lifetime (1..3600 s): clamp a deployment
        # TTL instead of surfacing it as a request refusal.
        return WorkspaceConfirmRootsResult(
            root_confirmation_id=confirmation_id,
            expires_in_s=min(3600, max(1, int(self._confirmations.ttl_seconds))),
        )

    def git_status(self, scope: WorkspaceScope, profile: ProfileRef) -> WorkspaceGitStatus:
        config = self._store.load(scope.workspace_id, profile)
        probed = detect_git(config.roots.workspace_root)
        try:
            return WorkspaceGitStatus(
                workspace_id=scope.workspace_id,
                state=GitState(probed.status.value),
                branch=probed.branch or None,
                remote=probed.remote or None,
                detached=probed.detached,
            )
        except ValidationError:
            # A branch or remote name the contract refuses (path-shaped,
            # credential-shaped) never blocks detection: report the state alone.
            return WorkspaceGitStatus(
                workspace_id=scope.workspace_id,
                state=GitState(probed.status.value),
                detached=probed.detached,
            )
