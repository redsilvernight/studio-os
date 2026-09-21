from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from studio_contracts.local.common import ComponentId, LocalError, LocalErrorCode
from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import (
    WORKSPACE_CONFIG_BACKUP_SUFFIX,
    WORKSPACE_CONFIG_SCHEMA_VERSION,
    WORKSPACE_MARKER_RELATIVE_PATH,
    LocalWorkspaceConfig,
    WorkspaceAction,
    WorkspaceHealth,
    WorkspaceMarker,
    WorkspaceRoots,
    WorkspaceSaveConfigRequest,
    WorkspaceStatus,
    workspace_config_relative_path,
)

from studio_workspaces.path_safety import check_readable, workspace_binding_key
from studio_workspaces.root_confirmation import RootConfirmationService
from studio_workspaces.secret_guard import assert_no_secrets, scan_studio_dir

ProjectAvailable = Callable[[UUID], bool]


class WorkspaceStoreError(Exception):
    def __init__(self, code: LocalErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MarkerHit:
    root: str
    marker: WorkspaceMarker


@dataclass(frozen=True)
class DissociateResult:
    workspace_id: UUID
    removed_config: str
    preserved_root: str | None


def _error(code: LocalErrorCode, message: str) -> LocalError:
    return LocalError(code=code, message=message, component=ComponentId.WORKSPACE, retryable=False)


_SAFE_VALIDATE_MESSAGES = {
    LocalErrorCode.WORKSPACE_CONFIG_INVALID: "workspace config is invalid",
    LocalErrorCode.WORKSPACE_INACCESSIBLE: "workspace config is inaccessible",
}


def _validate_error(exc: WorkspaceStoreError) -> LocalError:
    invalid = exc.code != LocalErrorCode.WORKSPACE_INACCESSIBLE
    code = (
        LocalErrorCode.WORKSPACE_CONFIG_INVALID
        if invalid
        else LocalErrorCode.WORKSPACE_INACCESSIBLE
    )
    return _error(code, _SAFE_VALIDATE_MESSAGES[code])


def _read_json(path: Path) -> dict[str, object]:
    try:
        return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise WorkspaceStoreError(LocalErrorCode.WORKSPACE_INACCESSIBLE, str(exc)) from exc
    except ValueError as exc:
        raise WorkspaceStoreError(LocalErrorCode.WORKSPACE_CONFIG_INVALID, str(exc)) from exc


class WorkspaceStore:
    def __init__(
        self,
        registry_dir: Path,
        confirmations: RootConfirmationService,
        project_available: ProjectAvailable = lambda _project_id: True,
    ) -> None:
        self._registry_dir = registry_dir
        self._confirmations = confirmations
        self._project_available = project_available

    def config_path(self, workspace_id: UUID) -> Path:
        return self._registry_dir / workspace_config_relative_path(workspace_id)

    def _parse(self, data: dict[str, object]) -> LocalWorkspaceConfig:
        version = data.get("schema_version")
        if version != WORKSPACE_CONFIG_SCHEMA_VERSION:
            if isinstance(version, int) and version > WORKSPACE_CONFIG_SCHEMA_VERSION:
                raise WorkspaceStoreError(
                    LocalErrorCode.WORKSPACE_CONFIG_INVALID,
                    "workspace config is newer than this daemon",
                )
            raise WorkspaceStoreError(
                LocalErrorCode.WORKSPACE_CONFIG_INVALID,
                "workspace config needs migration",
            )
        try:
            return LocalWorkspaceConfig.model_validate(data)
        except ValidationError as exc:
            raise WorkspaceStoreError(LocalErrorCode.WORKSPACE_CONFIG_INVALID, str(exc)) from exc

    def _check_profile(self, config: LocalWorkspaceConfig, profile: ProfileRef) -> None:
        if config.profile != profile:
            raise WorkspaceStoreError(
                LocalErrorCode.WORKSPACE_CONFIG_INVALID,
                "workspace config belongs to another profile",
            )
        for reference in config.secret_references:
            if reference.profile != profile:
                raise WorkspaceStoreError(
                    LocalErrorCode.WORKSPACE_CONFIG_INVALID,
                    "secret reference belongs to another profile",
                )

    def _write(self, config: LocalWorkspaceConfig) -> None:
        path = self.config_path(config.workspace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(payload + "\n", encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            raise WorkspaceStoreError(LocalErrorCode.WORKSPACE_INACCESSIBLE, str(exc)) from exc

    def _same_folder_conflict(self, config: LocalWorkspaceConfig) -> None:
        wanted = workspace_binding_key(config.roots.workspace_root)
        for path in sorted(self._registry_dir.glob("workspaces/*.json")):
            if path.name == f"{config.workspace_id}.json":
                continue
            try:
                other = self._parse(_read_json(path))
            except WorkspaceStoreError:
                continue
            if workspace_binding_key(other.roots.workspace_root) != wanted:
                continue
            if other.project_id != config.project_id or other.profile != config.profile:
                raise WorkspaceStoreError(
                    LocalErrorCode.INVALID_REQUEST,
                    "this folder is already linked to another project or profile",
                )

    def create(
        self, request: WorkspaceSaveConfigRequest, profile: ProfileRef
    ) -> LocalWorkspaceConfig:
        config = request.config
        if config.profile != profile:
            raise WorkspaceStoreError(LocalErrorCode.WRONG_PROFILE, "profile mismatch")
        if self.config_path(config.workspace_id).exists():
            raise WorkspaceStoreError(LocalErrorCode.INVALID_REQUEST, "workspace already exists")
        self._confirmations.consume(
            request.root_confirmation_id, request.current_roots, config.roots
        )
        assert_no_secrets(config.model_dump(mode="json"))
        self._same_folder_conflict(config)
        self._write(config)
        return config

    def save(
        self, request: WorkspaceSaveConfigRequest, profile: ProfileRef
    ) -> LocalWorkspaceConfig:
        config = request.config
        if config.profile != profile:
            raise WorkspaceStoreError(LocalErrorCode.WRONG_PROFILE, "profile mismatch")
        stored = self.load(config.workspace_id, profile)
        if request.current_roots != stored.roots:
            raise WorkspaceStoreError(
                LocalErrorCode.INVALID_REQUEST,
                "current_roots does not match the stored config",
            )
        if (
            request.expected_updated_at is not None
            and request.expected_updated_at != stored.updated_at
        ):
            raise WorkspaceStoreError(LocalErrorCode.INVALID_REQUEST, "stale workspace config")
        self._confirmations.consume(
            request.root_confirmation_id, request.current_roots, config.roots
        )
        assert_no_secrets(config.model_dump(mode="json"))
        self._same_folder_conflict(config)
        self._write(config)
        return config

    def load(self, workspace_id: UUID, profile: ProfileRef) -> LocalWorkspaceConfig:
        path = self.config_path(workspace_id)
        if not path.exists():
            raise WorkspaceStoreError(
                LocalErrorCode.WORKSPACE_CONFIG_MISSING, "no workspace config"
            )
        config = self._parse(_read_json(path))
        self._check_profile(config, profile)
        return config

    def list_workspaces(self, profile: ProfileRef) -> Sequence[LocalWorkspaceConfig]:
        configs: list[LocalWorkspaceConfig] = []
        for path in sorted(self._registry_dir.glob("workspaces/*.json")):
            try:
                config = self._parse(_read_json(path))
            except WorkspaceStoreError:
                continue
            if config.profile == profile:
                configs.append(config)
        return configs

    def migrate(self, workspace_id: UUID) -> LocalWorkspaceConfig:
        path = self.config_path(workspace_id)
        if not path.exists():
            raise WorkspaceStoreError(
                LocalErrorCode.WORKSPACE_CONFIG_MISSING, "no workspace config"
            )
        data = _read_json(path)
        version = data.get("schema_version")
        if version == WORKSPACE_CONFIG_SCHEMA_VERSION:
            return self._parse(data)
        if isinstance(version, int) and version > WORKSPACE_CONFIG_SCHEMA_VERSION:
            raise WorkspaceStoreError(
                LocalErrorCode.WORKSPACE_CONFIG_INVALID,
                "workspace config is newer than this daemon",
            )
        backup = path.with_name(path.name + WORKSPACE_CONFIG_BACKUP_SUFFIX)
        try:
            backup.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            raise WorkspaceStoreError(LocalErrorCode.WORKSPACE_INACCESSIBLE, str(exc)) from exc
        data["schema_version"] = WORKSPACE_CONFIG_SCHEMA_VERSION
        try:
            return self._parse(data)
        except ValidationError as exc:
            raise WorkspaceStoreError(LocalErrorCode.WORKSPACE_CONFIG_INVALID, str(exc)) from exc

    def validate(self, workspace_id: UUID, profile: ProfileRef) -> WorkspaceStatus:
        path = self.config_path(workspace_id)
        if not path.exists():
            return WorkspaceStatus(
                workspace_id=workspace_id,
                health=WorkspaceHealth.CONFIG_MISSING,
                action=WorkspaceAction.CREATE_CONFIG,
                error=_error(LocalErrorCode.WORKSPACE_CONFIG_MISSING, "no workspace config"),
            )
        try:
            config = self._parse(_read_json(path))
            self._check_profile(config, profile)
        except WorkspaceStoreError as exc:
            invalid = exc.code != LocalErrorCode.WORKSPACE_INACCESSIBLE
            return WorkspaceStatus(
                workspace_id=workspace_id,
                health=WorkspaceHealth.CONFIG_INVALID if invalid else WorkspaceHealth.INACCESSIBLE,
                action=WorkspaceAction.REPAIR_CONFIG if invalid else WorkspaceAction.GRANT_ACCESS,
                error=_validate_error(exc),
            )
        if not self._project_available(config.project_id):
            return WorkspaceStatus(
                workspace_id=workspace_id,
                health=WorkspaceHealth.PROJECT_UNAVAILABLE,
                action=WorkspaceAction.DETACH_WORKSPACE,
                error=_error(LocalErrorCode.PROJECT_UNAVAILABLE, "server project is unavailable"),
            )
        probe = check_readable(config.roots.workspace_root)
        if probe.ok:
            marker_issues = scan_studio_dir(Path(config.roots.workspace_root))
            if marker_issues:
                return WorkspaceStatus(
                    workspace_id=workspace_id,
                    health=WorkspaceHealth.CONFIG_INVALID,
                    action=WorkspaceAction.REPAIR_CONFIG,
                    error=_error(
                        LocalErrorCode.WORKSPACE_CONFIG_INVALID,
                        "the .studio folder carries secret-shaped data",
                    ),
                )
            return WorkspaceStatus(
                workspace_id=workspace_id,
                health=WorkspaceHealth.VALID,
                action=WorkspaceAction.NONE,
                config=config,
            )
        if probe.reason == "permission denied":
            return WorkspaceStatus(
                workspace_id=workspace_id,
                health=WorkspaceHealth.INACCESSIBLE,
                action=WorkspaceAction.GRANT_ACCESS,
                error=_error(LocalErrorCode.WORKSPACE_INACCESSIBLE, probe.reason),
            )
        hit = self.locate_by_marker(config.workspace_id, [config.roots.workspace_root])
        if hit is not None:
            return WorkspaceStatus(
                workspace_id=workspace_id,
                health=WorkspaceHealth.MOVED,
                action=WorkspaceAction.CONFIRM_RELOCATION,
                candidate_root=hit.root,
                error=_error(LocalErrorCode.WORKSPACE_MOVED, "workspace folder has moved"),
            )
        return WorkspaceStatus(
            workspace_id=workspace_id,
            health=WorkspaceHealth.INACCESSIBLE,
            action=WorkspaceAction.GRANT_ACCESS,
            error=_error(LocalErrorCode.WORKSPACE_INACCESSIBLE, probe.reason),
        )

    def dissociate(self, workspace_id: UUID, profile: ProfileRef) -> DissociateResult:
        config = self.load(workspace_id, profile)
        path = self.config_path(workspace_id)
        try:
            path.unlink()
        except OSError as exc:
            raise WorkspaceStoreError(LocalErrorCode.WORKSPACE_INACCESSIBLE, str(exc)) from exc
        return DissociateResult(
            workspace_id=workspace_id,
            removed_config=str(path),
            preserved_root=config.roots.workspace_root,
        )

    def write_marker(self, root: str, marker: WorkspaceMarker) -> Path:
        marker_path = Path(root) / WORKSPACE_MARKER_RELATIVE_PATH
        assert_no_secrets(marker.model_dump(mode="json"))
        try:
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(
                json.dumps(marker.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise WorkspaceStoreError(LocalErrorCode.WORKSPACE_INACCESSIBLE, str(exc)) from exc
        return marker_path

    def read_marker(self, root: str) -> WorkspaceMarker | None:
        marker_path = Path(root) / WORKSPACE_MARKER_RELATIVE_PATH
        if not marker_path.exists():
            return None
        try:
            return WorkspaceMarker.model_validate(_read_json(marker_path))
        except (WorkspaceStoreError, ValidationError):
            return None

    def locate_by_marker(self, workspace_id: UUID, search_dirs: Sequence[str]) -> MarkerHit | None:
        for search in search_dirs:
            base = Path(search)
            if not base.is_dir():
                parent = base.parent
                if not parent.is_dir():
                    continue
                base = parent
            try:
                candidates = [base, *sorted(p for p in base.iterdir() if p.is_dir())]
            except OSError:
                continue
            for candidate in candidates:
                marker = self.read_marker(str(candidate))
                if marker is not None and marker.workspace_id == workspace_id:
                    return MarkerHit(root=str(candidate), marker=marker)
        return None

    def current_roots(self, workspace_id: UUID, profile: ProfileRef) -> WorkspaceRoots | None:
        try:
            return self.load(workspace_id, profile).roots
        except WorkspaceStoreError as exc:
            if exc.code == LocalErrorCode.WORKSPACE_CONFIG_MISSING:
                return None
            raise
