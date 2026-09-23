from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from studio_contracts.local.workspace import WorkspaceMarker, WorkspaceSaveConfigRequest
from studio_workspaces.flows import FlowKind, run_flow, summarize_features
from studio_workspaces.git_detection import GitStatus
from studio_workspaces.picker import MockFolderPicker
from studio_workspaces.root_confirmation import RootConfirmationService
from studio_workspaces.store import WorkspaceStore

from .factories import PROFILE, PROJECT_ID, make_config

WS_A = UUID("11111111-1111-4111-8111-111111111111")


def _setup(tmp_path: Path) -> WorkspaceStore:
    return WorkspaceStore(tmp_path / "registry", RootConfirmationService())


def test_new_project_flow(tmp_path: Path) -> None:
    store = _setup(tmp_path)
    folder = tmp_path / "game"
    folder.mkdir()
    picker = MockFolderPicker([str(folder)])
    result = run_flow(FlowKind.NEW_PROJECT_WITH_FOLDER, store, picker, PROFILE, PROJECT_ID, WS_A)
    assert result.workspace_id == WS_A
    assert any("Dossier choisi" in step for step in result.steps)
    assert picker.calls == [None]


def test_cancelled_picker_changes_nothing(tmp_path: Path) -> None:
    store = _setup(tmp_path)
    picker = MockFolderPicker([])
    result = run_flow(FlowKind.ASSOCIATE_LOCAL_FOLDER, store, picker, PROFILE, PROJECT_ID, WS_A)
    assert "annulée" in result.message
    assert store.current_roots(WS_A, PROFILE) is None


def test_git_repo_flow_reports_branch(tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        return
    if git is None:
        return
    folder = tmp_path / "repo"
    folder.mkdir()
    subprocess.run([git, "init", "-b", "main"], cwd=folder, check=True, capture_output=True)
    (folder / "file.txt").write_text("data", encoding="utf-8")
    subprocess.run([git, "add", "."], cwd=folder, check=True, capture_output=True)
    subprocess.run(
        [git, "-c", "user.email=t@t.test", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=folder,
        check=True,
        capture_output=True,
    )
    store = _setup(tmp_path)
    result = run_flow(
        FlowKind.EXISTING_GIT_REPO,
        store,
        MockFolderPicker([]),
        PROFILE,
        PROJECT_ID,
        WS_A,
        folder_hint=str(folder),
    )
    assert result.git is not None
    assert result.git.status == GitStatus.VALID
    assert "branche main" in " ".join(result.steps)


def test_non_git_flow_is_explicit(tmp_path: Path) -> None:
    store = _setup(tmp_path)
    folder = tmp_path / "plain"
    folder.mkdir()
    result = run_flow(
        FlowKind.NON_GIT_FOLDER,
        store,
        MockFolderPicker([]),
        PROFILE,
        PROJECT_ID,
        WS_A,
        folder_hint=str(folder),
    )
    assert "sans Git" in " ".join(result.steps)


def test_project_without_folder_lists_links(tmp_path: Path) -> None:
    store = _setup(tmp_path)
    folder = tmp_path / "linked"
    folder.mkdir()
    config = make_config(WS_A, str(folder))
    cid = store._confirmations.issue(config.roots)
    store.create(
        WorkspaceSaveConfigRequest(config=config, current_roots=None, root_confirmation_id=cid),
        PROFILE,
    )
    result = run_flow(
        FlowKind.EXISTING_PROJECT_WITHOUT_FOLDER,
        store,
        MockFolderPicker([]),
        PROFILE,
        PROJECT_ID,
        WS_A,
    )
    assert "sans dossier local" in " ".join(result.steps)
    assert "1 dossier(s)" in " ".join(result.steps)


def test_moved_and_gone_flows(tmp_path: Path) -> None:
    store = _setup(tmp_path)
    folder = tmp_path / "ws"
    folder.mkdir()
    config = make_config(WS_A, str(folder))
    cid = store._confirmations.issue(config.roots)
    store.create(
        WorkspaceSaveConfigRequest(config=config, current_roots=None, root_confirmation_id=cid),
        PROFILE,
    )
    moved = run_flow(
        FlowKind.WORKSPACE_MOVED, store, MockFolderPicker([]), PROFILE, PROJECT_ID, WS_A
    )
    assert moved.status is not None and moved.status.health == "valid"
    folder.rmdir()
    gone = run_flow(FlowKind.WORKSPACE_GONE, store, MockFolderPicker([]), PROFILE, PROJECT_ID, WS_A)
    assert gone.status is not None and gone.status.health == "inaccessible"


def test_multi_workspace_flow(tmp_path: Path) -> None:
    store = _setup(tmp_path)
    for name in ("one", "two"):
        folder = tmp_path / name
        folder.mkdir()
    result = run_flow(
        FlowKind.MULTI_WORKSPACE, store, MockFolderPicker([]), PROFILE, PROJECT_ID, WS_A
    )
    assert "0 espace(s)" in " ".join(result.steps)


def test_summarize_features_disabled() -> None:
    lines = summarize_features(make_config(WS_A, "C:/Work/demo"))
    assert any("coupé" in line for line in lines)
    assert any("consultable" in line for line in lines)


def test_marker_only_needs_ids() -> None:
    marker = WorkspaceMarker(workspace_id=WS_A, project_id=PROJECT_ID)
    assert marker.model_dump(mode="json")["schema_version"] == 1
