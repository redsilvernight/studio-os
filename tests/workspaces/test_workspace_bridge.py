"""P11: the `WorkspaceBridge` serving the P1 `workspace.*` commands.

Covers the onboarding seam end to end at the store level: confirm a picked
folder, save the first config, re-validate, update without transition, and
every refusal (missing confirmation, replay, mismatch, expiration, stale
config, unknown workspace).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from studio_contracts.local.common import LocalErrorCode
from studio_contracts.local.workspace import (
    GitState,
    WorkspaceConfirmRootsRequest,
    WorkspaceHealth,
    WorkspaceSaveConfigRequest,
    WorkspaceScope,
)
from studio_workspaces.root_confirmation import (
    ConfirmationExpired,
    ConfirmationMismatch,
    ConfirmationReused,
    RootConfirmationService,
)
from studio_workspaces.store import WorkspaceStoreError
from studio_workspaces.workspace_bridge import WorkspaceBridge

from .factories import PROFILE, PROJECT_ID, make_config, make_roots

WS = UUID("11111111-1111-4111-8111-111111111111")


def _bridge(tmp_path, **kwargs) -> WorkspaceBridge:
    return WorkspaceBridge(tmp_path / "registry", RootConfirmationService(), **kwargs)


def test_confirm_then_create_then_validate(tmp_path) -> None:
    folder = tmp_path / "game"
    folder.mkdir()
    bridge = _bridge(tmp_path)
    config = make_config(WS, str(folder))

    confirmed = bridge.confirm(WorkspaceConfirmRootsRequest(roots=config.roots))
    assert confirmed.root_confirmation_id.startswith("rc-")
    assert 1 <= confirmed.expires_in_s <= 3600

    saved = bridge.save(
        WorkspaceSaveConfigRequest(
            config=config, current_roots=None, root_confirmation_id=confirmed.root_confirmation_id
        ),
        PROFILE,
    )
    assert saved.workspace_id == WS

    status = bridge.validate(WS, PROFILE)
    assert status.health is WorkspaceHealth.VALID
    assert status.config is not None
    assert status.config.workspace_id == WS

    assert bridge.get_config(WS, PROFILE).roots == config.roots


def test_save_without_confirmation_is_refused(tmp_path) -> None:
    folder = tmp_path / "game"
    folder.mkdir()
    config = make_config(WS, str(folder))
    with pytest.raises(ValueError, match="requires root_confirmation_id"):
        WorkspaceSaveConfigRequest(config=config, current_roots=None)


def test_confirmation_is_single_use(tmp_path) -> None:
    folder = tmp_path / "game"
    moved = tmp_path / "moved"
    folder.mkdir()
    moved.mkdir()
    bridge = _bridge(tmp_path)
    config = make_config(WS, str(folder))
    confirmed = bridge.confirm(WorkspaceConfirmRootsRequest(roots=config.roots))
    bridge.save(
        WorkspaceSaveConfigRequest(
            config=config, current_roots=None, root_confirmation_id=confirmed.root_confirmation_id
        ),
        PROFILE,
    )
    relocated = config.model_copy(update={"roots": make_roots(str(moved))})
    with pytest.raises(ConfirmationReused):
        bridge.save(
            WorkspaceSaveConfigRequest(
                config=relocated,
                current_roots=config.roots,
                root_confirmation_id=confirmed.root_confirmation_id,
            ),
            PROFILE,
        )


def test_confirmation_is_bound_to_the_picked_roots(tmp_path) -> None:
    picked = tmp_path / "picked"
    other = tmp_path / "other"
    picked.mkdir()
    other.mkdir()
    bridge = _bridge(tmp_path)
    confirmed = bridge.confirm(WorkspaceConfirmRootsRequest(roots=make_roots(str(picked))))
    forged = make_config(WS, str(other))
    with pytest.raises(ConfirmationMismatch):
        bridge.save(
            WorkspaceSaveConfigRequest(
                config=forged,
                current_roots=None,
                root_confirmation_id=confirmed.root_confirmation_id,
            ),
            PROFILE,
        )


def test_expired_confirmation_is_refused(tmp_path) -> None:
    folder = tmp_path / "game"
    folder.mkdir()
    now = [1000.0]
    confirmations = RootConfirmationService(ttl_seconds=10.0, clock=lambda: now[0])
    bridge = WorkspaceBridge(tmp_path / "registry", confirmations)
    config = make_config(WS, str(folder))
    confirmed = bridge.confirm(WorkspaceConfirmRootsRequest(roots=config.roots))
    now[0] += 60.0
    with pytest.raises(ConfirmationExpired):
        bridge.save(
            WorkspaceSaveConfigRequest(
                config=config,
                current_roots=None,
                root_confirmation_id=confirmed.root_confirmation_id,
            ),
            PROFILE,
        )


def test_confirm_refuses_an_unreadable_folder(tmp_path) -> None:
    bridge = _bridge(tmp_path)
    with pytest.raises(WorkspaceStoreError) as exc:
        bridge.confirm(WorkspaceConfirmRootsRequest(roots=make_roots(str(tmp_path / "missing"))))
    assert exc.value.code is LocalErrorCode.WORKSPACE_INACCESSIBLE


def test_update_without_transition_needs_no_confirmation(tmp_path) -> None:
    folder = tmp_path / "game"
    folder.mkdir()
    bridge = _bridge(tmp_path)
    config = make_config(WS, str(folder))
    confirmed = bridge.confirm(WorkspaceConfirmRootsRequest(roots=config.roots))
    saved = bridge.save(
        WorkspaceSaveConfigRequest(
            config=config, current_roots=None, root_confirmation_id=confirmed.root_confirmation_id
        ),
        PROFILE,
    )
    renamed = saved.model_copy(update={"project_slug": "renamed"})
    updated = bridge.save(
        WorkspaceSaveConfigRequest(config=renamed, current_roots=saved.roots),
        PROFILE,
    )
    assert updated.project_slug == "renamed"


def test_stale_config_is_refused(tmp_path) -> None:
    folder = tmp_path / "game"
    folder.mkdir()
    bridge = _bridge(tmp_path)
    config = make_config(WS, str(folder))
    confirmed = bridge.confirm(WorkspaceConfirmRootsRequest(roots=config.roots))
    saved = bridge.save(
        WorkspaceSaveConfigRequest(
            config=config, current_roots=None, root_confirmation_id=confirmed.root_confirmation_id
        ),
        PROFILE,
    )
    moved = make_config(WS, str(folder))
    other_root = tmp_path / "elsewhere"
    other_root.mkdir()
    moved_elsewhere = moved.model_copy(update={"roots": make_roots(str(other_root))})
    confirmed2 = bridge.confirm(WorkspaceConfirmRootsRequest(roots=moved_elsewhere.roots))
    with pytest.raises(WorkspaceStoreError) as exc:
        bridge.save(
            WorkspaceSaveConfigRequest(
                config=moved_elsewhere,
                current_roots=make_roots(str(tmp_path / "stale")),
                root_confirmation_id=confirmed2.root_confirmation_id,
            ),
            PROFILE,
        )
    assert exc.value.code is LocalErrorCode.INVALID_REQUEST
    assert saved.workspace_id == WS


def test_unknown_workspace_is_missing(tmp_path) -> None:
    bridge = _bridge(tmp_path)
    status = bridge.validate(WS, PROFILE)
    assert status.health is WorkspaceHealth.CONFIG_MISSING
    with pytest.raises(WorkspaceStoreError) as exc:
        bridge.get_config(WS, PROFILE)
    assert exc.value.code is LocalErrorCode.WORKSPACE_CONFIG_MISSING


def test_project_unavailable_is_reported(tmp_path) -> None:
    folder = tmp_path / "game"
    folder.mkdir()
    bridge = _bridge(tmp_path, project_available=lambda _pid: False)
    config = make_config(WS, str(folder), project_id=PROJECT_ID)
    confirmed = bridge.confirm(WorkspaceConfirmRootsRequest(roots=config.roots))
    bridge.save(
        WorkspaceSaveConfigRequest(
            config=config, current_roots=None, root_confirmation_id=confirmed.root_confirmation_id
        ),
        PROFILE,
    )
    status = bridge.validate(WS, PROFILE)
    assert status.health is WorkspaceHealth.PROJECT_UNAVAILABLE


def _save_first(bridge: WorkspaceBridge, folder) -> None:
    config = make_config(WS, str(folder))
    confirmed = bridge.confirm(WorkspaceConfirmRootsRequest(roots=config.roots))
    bridge.save(
        WorkspaceSaveConfigRequest(
            config=config, current_roots=None, root_confirmation_id=confirmed.root_confirmation_id
        ),
        PROFILE,
    )


def test_git_status_without_repo(tmp_path) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    bridge = _bridge(tmp_path)
    _save_first(bridge, folder)
    probed = bridge.git_status(WorkspaceScope(workspace_id=WS), PROFILE)
    assert probed.workspace_id == WS
    assert probed.state in (GitState.NOT_A_REPO, GitState.GIT_ABSENT)
    assert probed.branch is None


def test_git_status_inside_a_repo(tmp_path) -> None:
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git executable not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "note.md").write_text("# hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.t", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    bridge = _bridge(tmp_path)
    _save_first(bridge, repo)
    probed = bridge.git_status(WorkspaceScope(workspace_id=WS), PROFILE)
    assert probed.state is GitState.VALID
    assert probed.branch == "main"
    assert probed.detached is False


def test_git_status_unknown_workspace(tmp_path) -> None:
    bridge = _bridge(tmp_path)
    with pytest.raises(WorkspaceStoreError) as exc:
        bridge.git_status(WorkspaceScope(workspace_id=WS), PROFILE)
    assert exc.value.code is LocalErrorCode.WORKSPACE_CONFIG_MISSING
