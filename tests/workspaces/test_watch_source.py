from __future__ import annotations

from pathlib import Path
from uuid import UUID

from studio_contracts.local.workspace import (
    LocalFeatures,
    WatcherConfig,
    WorkspaceSaveConfigRequest,
)
from studio_workspaces import registry_watch_source
from studio_workspaces.root_confirmation import RootConfirmationService
from studio_workspaces.store import WorkspaceStore

from .factories import OTHER_PROFILE, PROFILE, make_config

WS_A = UUID("11111111-1111-4111-8111-111111111111")
WS_B = UUID("22222222-2222-4222-8222-222222222222")


def _seed(store: WorkspaceStore, workspace_id: UUID, root: Path, repos, profile=PROFILE):
    root.mkdir(parents=True, exist_ok=True)
    config = make_config(workspace_id, str(root), repos, profile=profile).model_copy(
        update={"features": LocalFeatures(watchers=True), "watchers": WatcherConfig()}
    )
    cid = store._confirmations.issue(config.roots)
    store.create(
        WorkspaceSaveConfigRequest(config=config, current_roots=None, root_confirmation_id=cid),
        profile,
    )
    return config


def test_the_source_describes_only_the_requested_profile(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    store = WorkspaceStore(registry, RootConfirmationService())
    repo = tmp_path / "game"
    _seed(store, WS_A, tmp_path / "a", [("game", str(repo))])
    _seed(store, WS_B, tmp_path / "b", [("other", str(tmp_path / "other"))], OTHER_PROFILE)
    source = registry_watch_source(registry)
    entries = source(PROFILE)
    assert [entry.workspace_id for entry in entries] == [WS_A]
    assert entries[0].plan.enabled
    assert [Path(p) for p in entries[0].plan.repo_paths] == [repo]
    assert [entry.workspace_id for entry in source(OTHER_PROFILE)] == [WS_B]


def test_another_server_origin_sees_nothing(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    store = WorkspaceStore(registry, RootConfirmationService())
    _seed(store, WS_A, tmp_path / "a", [])
    foreign = PROFILE.model_copy(update={"server_origin": "https://other.example.test"})
    assert registry_watch_source(registry)(foreign) == []


def test_an_empty_registry_yields_no_watch(tmp_path: Path) -> None:
    assert registry_watch_source(tmp_path / "nowhere")(PROFILE) == []


def test_the_source_reflects_a_removed_association(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    store = WorkspaceStore(registry, RootConfirmationService())
    _seed(store, WS_A, tmp_path / "a", [])
    source = registry_watch_source(registry)
    assert len(source(PROFILE)) == 1
    store.config_path(WS_A).unlink()
    assert source(PROFILE) == []
