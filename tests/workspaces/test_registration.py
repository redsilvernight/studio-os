from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client import cli
from studio_contracts.local.common import LocalErrorCode
from studio_contracts.local.workspace import LocalFeatures, WorkspaceSaveConfigRequest
from studio_workspaces import (
    RegistrationAction,
    RootConfirmationService,
    WorkspaceStore,
    WorkspaceStoreError,
    daemon_watch_plan,
    register_workspace,
)

from tests.workspaces.factories import OTHER_PROJECT_ID, PROFILE, PROJECT_ID, make_config


def _folder(tmp_path: Path, name: str = "game") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return folder


def _store(registry: Path) -> WorkspaceStore:
    return WorkspaceStore(registry, RootConfirmationService())


def test_a_new_folder_is_created_with_git_watching_on(tmp_path: Path) -> None:
    registry, folder = tmp_path / "registry", _folder(tmp_path)

    result = register_workspace(registry, PROFILE, PROJECT_ID, str(folder), project_slug="game")

    assert result.action is RegistrationAction.CREATED
    [stored] = _store(registry).list_workspaces(PROFILE)
    assert stored == result.config
    assert stored.project_slug == "game"
    assert stored.features.watchers is True
    plan = daemon_watch_plan(stored)
    assert plan.enabled
    assert plan.repo_paths == [str(folder)]


def test_registering_twice_changes_nothing(tmp_path: Path) -> None:
    registry, folder = tmp_path / "registry", _folder(tmp_path)
    first = register_workspace(registry, PROFILE, PROJECT_ID, str(folder))

    same_folder = str(folder).upper() if os.name == "nt" else str(folder)
    again = register_workspace(registry, PROFILE, PROJECT_ID, same_folder)

    assert again.action is RegistrationAction.UNCHANGED
    assert again.config == first.config
    assert len(_store(registry).list_workspaces(PROFILE)) == 1


def test_an_existing_link_without_watchers_gets_them(tmp_path: Path) -> None:
    registry, folder = tmp_path / "registry", _folder(tmp_path)
    confirmations = RootConfirmationService()
    config = make_config(uuid4(), str(folder)).model_copy(
        update={"features": LocalFeatures(watchers=False), "watchers": None}
    )
    WorkspaceStore(registry, confirmations).create(
        WorkspaceSaveConfigRequest(
            config=config,
            current_roots=None,
            root_confirmation_id=confirmations.issue(config.roots),
        ),
        PROFILE,
    )

    result = register_workspace(registry, PROFILE, PROJECT_ID, str(folder))

    assert result.action is RegistrationAction.WATCHERS_ENABLED
    [stored] = _store(registry).list_workspaces(PROFILE)
    assert stored.workspace_id == config.workspace_id
    assert stored.features.watchers is True
    assert stored.watchers is not None
    assert stored.roots == config.roots


def test_a_folder_linked_to_another_project_is_refused(tmp_path: Path) -> None:
    registry, folder = tmp_path / "registry", _folder(tmp_path)
    register_workspace(registry, PROFILE, OTHER_PROJECT_ID, str(folder))

    with pytest.raises(WorkspaceStoreError) as caught:
        register_workspace(registry, PROFILE, PROJECT_ID, str(folder))

    assert caught.value.code == LocalErrorCode.INVALID_REQUEST


def test_a_missing_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceStoreError) as caught:
        register_workspace(tmp_path / "registry", PROFILE, PROJECT_ID, str(tmp_path / "nope"))

    assert caught.value.code == LocalErrorCode.WORKSPACE_INACCESSIBLE


def test_the_cli_registers_for_the_configured_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://studio.example.test/api")
    monkeypatch.setenv("STUDIO_CLIENT_PROFILE_ID", PROFILE.profile_id)
    registry, folder = tmp_path / "registry", _folder(tmp_path)
    argv = [
        "workspaces",
        "register",
        "--path",
        str(folder),
        "--project-id",
        str(PROJECT_ID),
        "--registry-dir",
        str(registry),
        "--json",
    ]

    cli.main(argv)
    created = json.loads(capsys.readouterr().out)
    cli.main(argv)
    again = json.loads(capsys.readouterr().out)

    assert created["action"] == "created"
    assert created["watchers"] is True
    assert again == {**created, "action": "unchanged"}
    [stored] = _store(registry).list_workspaces(PROFILE)
    assert str(stored.workspace_id) == created["workspace_id"]


def test_the_cli_reports_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://studio.example.test")
    argv = ["workspaces", "register", "--path", str(tmp_path / "nope")]
    argv += ["--project-id", str(PROJECT_ID), "--registry-dir", str(tmp_path / "registry")]

    with pytest.raises(SystemExit) as caught:
        cli.main(argv)

    assert caught.value.code == 1
    assert "workspace_inaccessible" in capsys.readouterr().err
