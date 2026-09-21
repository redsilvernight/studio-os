from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from studio_contracts.local.common import LocalErrorCode
from studio_contracts.local.workspace import (
    LocalWorkspaceConfig,
    WorkspaceMarker,
    WorkspaceRoots,
    WorkspaceSaveConfigRequest,
)
from studio_workspaces.root_confirmation import RootConfirmationService
from studio_workspaces.store import WorkspaceStore, WorkspaceStoreError

from .factories import OTHER_PROFILE, OTHER_PROJECT_ID, PROFILE, PROJECT_ID, make_config

WS_A = UUID("11111111-1111-4111-8111-111111111111")
WS_B = UUID("22222222-2222-4222-8222-222222222222")


def _store(tmp_path: Path) -> WorkspaceStore:
    return WorkspaceStore(tmp_path / "registry", RootConfirmationService())


def _initial(config: LocalWorkspaceConfig, store: WorkspaceStore) -> WorkspaceSaveConfigRequest:
    cid = store._confirmations.issue(config.roots)
    return WorkspaceSaveConfigRequest(config=config, current_roots=None, root_confirmation_id=cid)


def _moved_roots(path: str) -> WorkspaceRoots:
    return WorkspaceRoots(workspace_root=path, repo_roots=[])


def test_create_first_config(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = tmp_path / "demo"
    root.mkdir()
    config = make_config(WS_A, str(root))
    stored = store.create(_initial(config, store), PROFILE)
    assert stored.workspace_id == WS_A
    assert store.config_path(WS_A).exists()
    text = store.config_path(WS_A).read_text(encoding="utf-8")
    assert "root_confirmation_id" not in text
    assert store.load(WS_A, PROFILE) == config


def test_create_without_confirmation_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = make_config(WS_A, str(tmp_path / "demo"))
    with pytest.raises(ValidationError, match="requires root_confirmation_id"):
        store.create(WorkspaceSaveConfigRequest(config=config, current_roots=None), PROFILE)


def test_create_with_unknown_confirmation_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = make_config(WS_A, str(tmp_path / "demo"))
    request = WorkspaceSaveConfigRequest(
        config=config, current_roots=None, root_confirmation_id="rc-unknown"
    )
    with pytest.raises(ValueError, match="unknown root confirmation"):
        store.create(request, PROFILE)


def test_save_root_change_with_confirmation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    config = make_config(WS_A, str(old))
    store.create(_initial(config, store), PROFILE)
    moved = config.model_copy(update={"roots": _moved_roots(str(new))})
    cid = store._confirmations.issue(moved.roots)
    request = WorkspaceSaveConfigRequest(
        config=moved, current_roots=config.roots, root_confirmation_id=cid
    )
    saved = store.save(request, PROFILE)
    assert saved.roots.workspace_root == str(new)


def test_save_root_change_without_confirmation_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = tmp_path / "old"
    old.mkdir()
    config = make_config(WS_A, str(old))
    store.create(_initial(config, store), PROFILE)
    moved = config.model_copy(update={"roots": _moved_roots("C:/Work/elsewhere")})
    with pytest.raises(ValidationError, match="requires root_confirmation_id"):
        store.save(WorkspaceSaveConfigRequest(config=moved, current_roots=config.roots), PROFILE)


def test_save_stable_config_with_confirmation_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = tmp_path / "demo"
    root.mkdir()
    config = make_config(WS_A, str(root))
    store.create(_initial(config, store), PROFILE)
    with pytest.raises(ValueError, match="only valid on a root transition"):
        store.save(
            WorkspaceSaveConfigRequest(
                config=config, current_roots=config.roots, root_confirmation_id="rc-stray"
            ),
            PROFILE,
        )


def test_save_with_wrong_current_roots_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = tmp_path / "demo"
    root.mkdir()
    config = make_config(WS_A, str(root))
    store.create(_initial(config, store), PROFILE)
    other = config.model_copy(update={"roots": _moved_roots("C:/Work/other")})
    cid = store._confirmations.issue(other.roots)
    liar = WorkspaceRoots(workspace_root="C:/Work/liar", repo_roots=[])
    with pytest.raises(WorkspaceStoreError) as exc:
        store.save(
            WorkspaceSaveConfigRequest(config=other, current_roots=liar, root_confirmation_id=cid),
            PROFILE,
        )
    assert exc.value.code == LocalErrorCode.INVALID_REQUEST


def test_save_stale_timestamp_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = tmp_path / "demo"
    root.mkdir()
    config = make_config(WS_A, str(root))
    store.create(_initial(config, store), PROFILE)
    touched = config.model_copy(update={"project_slug": "renamed"})
    with pytest.raises(WorkspaceStoreError) as exc:
        store.save(
            WorkspaceSaveConfigRequest(
                config=touched,
                current_roots=config.roots,
                expected_updated_at=datetime(2020, 1, 1, tzinfo=UTC),
            ),
            PROFILE,
        )
    assert exc.value.code == LocalErrorCode.INVALID_REQUEST


def test_wrong_profile_is_never_silent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = make_config(WS_A, str(tmp_path / "demo"))
    with pytest.raises(WorkspaceStoreError) as exc:
        store.create(_initial(config, store), OTHER_PROFILE)
    assert exc.value.code == LocalErrorCode.WRONG_PROFILE
    root = tmp_path / "demo"
    root.mkdir()
    store.create(_initial(config, store), PROFILE)
    with pytest.raises(WorkspaceStoreError) as exc:
        store.load(WS_A, OTHER_PROFILE)
    assert exc.value.code == LocalErrorCode.WORKSPACE_CONFIG_INVALID
    assert store.list_workspaces(OTHER_PROFILE) == []
    assert len(store.list_workspaces(PROFILE)) == 1


def test_same_folder_incompatible_association_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = tmp_path / "demo"
    root.mkdir()
    store.create(_initial(make_config(WS_A, str(root)), store), PROFILE)
    other = make_config(WS_B, str(root), project_id=OTHER_PROJECT_ID)
    with pytest.raises(WorkspaceStoreError) as exc:
        store.create(_initial(other, store), PROFILE)
    assert exc.value.code == LocalErrorCode.INVALID_REQUEST
    third = make_config(WS_B, str(root), profile=OTHER_PROFILE)
    with pytest.raises(WorkspaceStoreError):
        store.create(_initial(third, store), OTHER_PROFILE)


def test_dissociation_is_not_destructive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = tmp_path / "demo"
    root.mkdir()
    user_file = root / "notes.txt"
    user_file.write_text("precious", encoding="utf-8")
    config = make_config(WS_A, str(root))
    store.create(_initial(config, store), PROFILE)
    store.write_marker(str(root), WorkspaceMarker(workspace_id=WS_A, project_id=PROJECT_ID))
    result = store.dissociate(WS_A, PROFILE)
    assert not store.config_path(WS_A).exists()
    assert result.preserved_root == str(root)
    assert user_file.exists()
    assert (root / ".studio" / "workspace.json").exists()
    assert root.exists()


def test_features_disabled_validates_cleanly(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = tmp_path / "demo"
    root.mkdir()
    config = make_config(WS_A, str(root))
    assert config.features.knowledge is False
    assert config.knowledge is None
    store.create(_initial(config, store), PROFILE)
    status = store.validate(WS_A, PROFILE)
    assert status.health == "valid"
    assert status.config is not None


def test_newer_schema_is_refused_and_legacy_keeps_backup(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.config_path(WS_A)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(WorkspaceStoreError) as exc:
        store.migrate(WS_A)
    assert exc.value.code == LocalErrorCode.WORKSPACE_CONFIG_INVALID
    path.write_text(json.dumps({"schema_version": 0}), encoding="utf-8")
    with pytest.raises(WorkspaceStoreError):
        store.migrate(WS_A)
    assert path.with_name(path.name + ".bak").exists()


def test_moved_workspace_proposes_candidate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = tmp_path / "old"
    old.mkdir()
    config = make_config(WS_A, str(old))
    store.create(_initial(config, store), PROFILE)
    store.write_marker(str(old), WorkspaceMarker(workspace_id=WS_A, project_id=PROJECT_ID))
    new = tmp_path / "old-moved"
    old.rename(new)
    (new / ".studio" / "workspace.json").write_text(
        json.dumps({"workspace_id": str(WS_A), "project_id": str(PROJECT_ID)}),
        encoding="utf-8",
    )
    status = store.validate(WS_A, PROFILE)
    assert status.health == "moved"
    assert status.candidate_root == str(new)


def test_gone_workspace_is_inaccessible(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = tmp_path / "demo"
    root.mkdir()
    config = make_config(WS_A, str(root))
    store.create(_initial(config, store), PROFILE)
    root.rmdir()
    status = store.validate(WS_A, PROFILE)
    assert status.health == "inaccessible"


def test_unavailable_server_project(tmp_path: Path) -> None:
    store = WorkspaceStore(
        tmp_path / "registry", RootConfirmationService(), project_available=lambda _pid: False
    )
    root = tmp_path / "demo"
    root.mkdir()
    config = make_config(WS_A, str(root))
    store.create(_initial(config, store), PROFILE)
    status = store.validate(WS_A, PROFILE)
    assert status.health == "project_unavailable"
    assert status.action == "detach_workspace"


def test_missing_config_status(tmp_path: Path) -> None:
    store = _store(tmp_path)
    status = store.validate(WS_A, PROFILE)
    assert status.health == "config_missing"
    assert status.action == "create_config"


def test_raw_secret_field_is_rejected_at_parse(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.config_path(WS_A)
    path.parent.mkdir(parents=True, exist_ok=True)
    config = make_config(WS_A, str(tmp_path / "demo"))
    raw = config.model_dump(mode="json")
    raw["machine_token"] = "should-never-persist"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(WorkspaceStoreError) as exc:
        store.load(WS_A, PROFILE)
    assert exc.value.code == LocalErrorCode.WORKSPACE_CONFIG_INVALID


def test_validate_never_raises_on_broken_config(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.config_path(WS_A)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = make_config(WS_A, str(tmp_path / "demo")).model_dump(mode="json")
    assert isinstance(raw["roots"], dict)
    raw["roots"]["workspace_root"] = "C:/Work/./demo"
    path.write_text(json.dumps(raw), encoding="utf-8")
    status = store.validate(WS_A, PROFILE)
    assert status.health == "config_invalid"
    assert status.action == "repair_config"


def test_validate_never_raises_on_unreadable_config(tmp_path: Path) -> None:
    store = _store(tmp_path)
    path = store.config_path(WS_A)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    status = store.validate(WS_A, PROFILE)
    assert status.health == "inaccessible"
    assert status.action == "grant_access"


def test_marker_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    root = tmp_path / "demo"
    root.mkdir()
    marker = WorkspaceMarker(workspace_id=WS_A, project_id=PROJECT_ID)
    marker_path = store.write_marker(str(root), marker)
    assert marker_path.exists()
    assert store.read_marker(str(root)) == marker
    assert store.read_marker(str(tmp_path / "nope")) is None
