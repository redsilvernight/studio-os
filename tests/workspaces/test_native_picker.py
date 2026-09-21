"""P3 ↔ P5: the native folder picker adapter feeding the P5 flows and store."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from studio_contracts.local.workspace import WorkspaceSaveConfigRequest
from studio_workspaces import (
    FlowKind,
    NativeFolderPicker,
    NativePickStatus,
    RootConfirmationService,
    WorkspaceStore,
    parse_native_pick,
    run_flow,
)
from studio_workspaces.root_confirmation import ConfirmationMismatch, ConfirmationReused

from .factories import PROFILE, PROJECT_ID, make_config

WS = UUID("11111111-1111-4111-8111-111111111111")


def _selected(path: Path | str) -> dict[str, str]:
    return {"status": "selected", "path": str(path), "display_name": Path(str(path)).name}


def _store(tmp_path: Path) -> tuple[WorkspaceStore, RootConfirmationService]:
    confirmations = RootConfirmationService()
    return WorkspaceStore(tmp_path / "registry", confirmations), confirmations


def test_selection_returns_the_folder_the_user_chose(tmp_path: Path) -> None:
    folder = tmp_path / "game"
    folder.mkdir()
    picker = NativeFolderPicker(lambda: _selected(folder), nonce_factory=lambda: "n-1")
    selected = picker.select_folder(hint="ignored")
    assert selected is not None
    assert selected.path == str(folder)
    assert selected.confirmation_nonce == "n-1"
    assert picker.last is not None
    assert picker.last.status is NativePickStatus.SELECTED


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"status": "cancelled"}, NativePickStatus.CANCELLED),
        ({"status": "unavailable"}, NativePickStatus.UNAVAILABLE),
        ({"status": "error", "code": "dialog_failed"}, NativePickStatus.ERROR),
    ],
)
def test_no_selection_selects_nothing_and_flow_changes_nothing(
    tmp_path: Path, payload: dict[str, str], status: NativePickStatus
) -> None:
    store, _ = _store(tmp_path)
    picker = NativeFolderPicker(lambda: payload)
    result = run_flow(FlowKind.ASSOCIATE_LOCAL_FOLDER, store, picker, PROFILE, PROJECT_ID, WS)
    assert picker.last is not None
    assert picker.last.status is status
    assert "annulée" in result.message
    assert store.current_roots(WS, PROFILE) is None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "C:/x",
        {},
        {"status": "selected"},
        {"status": "selected", "path": ""},
        {"status": "selected", "path": "relative/dir"},
        {"status": "selected", "path": "/ok\nbad"},
        {"status": "selected", "path": "/" + "a" * 5000},
        {"status": "selected", "path": 42},
        {"status": "granted", "path": "/x"},
    ],
)
def test_a_malformed_shell_answer_is_never_a_selection(payload: object) -> None:
    assert parse_native_pick(payload).status is NativePickStatus.ERROR
    assert NativeFolderPicker(lambda: payload).select_folder() is None


def test_a_failing_shell_is_never_a_selection() -> None:
    def broken() -> object:
        raise RuntimeError("dialog crashed")

    picker = NativeFolderPicker(broken)
    assert picker.select_folder() is None
    assert picker.last is not None
    assert picker.last.code == "picker_failed"


def test_a_folder_that_does_not_exist_is_refused_by_the_flow(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    picker = NativeFolderPicker(lambda: _selected(tmp_path / "missing"))
    result = run_flow(FlowKind.EXISTING_PROJECT_WITH_FOLDER, store, picker, PROFILE, PROJECT_ID, WS)
    assert result.message.startswith("Dossier refusé")
    assert result.workspace_id is None
    assert store.current_roots(WS, PROFILE) is None


def test_first_association_needs_a_root_confirmation_bound_to_the_pick(tmp_path: Path) -> None:
    store, confirmations = _store(tmp_path)
    folder = tmp_path / "game"
    folder.mkdir()
    picker = NativeFolderPicker(lambda: _selected(folder))
    flow = run_flow(FlowKind.NEW_PROJECT_WITH_FOLDER, store, picker, PROFILE, PROJECT_ID, WS)
    assert flow.workspace_id == WS
    config = make_config(WS, str(folder))
    # No confirmation: the store refuses (validated by the contract itself).
    with pytest.raises(ValueError, match="requires root_confirmation_id"):
        WorkspaceSaveConfigRequest(config=config, current_roots=None)
    cid = confirmations.issue(config.roots)
    store.create(
        WorkspaceSaveConfigRequest(config=config, current_roots=None, root_confirmation_id=cid),
        PROFILE,
    )
    assert store.current_roots(WS, PROFILE) == config.roots
    # Single use: the same id cannot be replayed.
    with pytest.raises(ConfirmationReused):
        confirmations.consume(cid, None, config.roots)


def test_a_confirmation_is_bound_to_the_roots_the_user_picked(tmp_path: Path) -> None:
    store, confirmations = _store(tmp_path)
    picked = tmp_path / "picked"
    other = tmp_path / "other"
    picked.mkdir()
    other.mkdir()
    cid = confirmations.issue(make_config(WS, str(picked)).roots)
    forged = make_config(WS, str(other))
    with pytest.raises(ConfirmationMismatch):
        store.create(
            WorkspaceSaveConfigRequest(config=forged, current_roots=None, root_confirmation_id=cid),
            PROFILE,
        )
    assert store.current_roots(WS, PROFILE) is None


def test_root_modification_re_picks_and_needs_a_new_confirmation(tmp_path: Path) -> None:
    store, confirmations = _store(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    initial = make_config(WS, str(first))
    store.create(
        WorkspaceSaveConfigRequest(
            config=initial,
            current_roots=None,
            root_confirmation_id=confirmations.issue(initial.roots),
        ),
        PROFILE,
    )
    picker = NativeFolderPicker(lambda: _selected(second))
    moved_flow = run_flow(FlowKind.ASSOCIATE_LOCAL_FOLDER, store, picker, PROFILE, PROJECT_ID, WS)
    assert moved_flow.workspace_id == WS
    moved = make_config(WS, str(second))
    # The old confirmation (first root) does not authorise the new root.
    with pytest.raises(ConfirmationMismatch):
        store.save(
            WorkspaceSaveConfigRequest(
                config=moved,
                current_roots=initial.roots,
                root_confirmation_id=confirmations.issue(initial.roots),
            ),
            PROFILE,
        )
    store.save(
        WorkspaceSaveConfigRequest(
            config=moved,
            current_roots=initial.roots,
            root_confirmation_id=confirmations.issue(moved.roots),
        ),
        PROFILE,
    )
    assert store.current_roots(WS, PROFILE) == moved.roots
