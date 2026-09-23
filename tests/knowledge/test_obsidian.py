from __future__ import annotations

import json
from pathlib import Path

from studio_client.knowledge.obsidian import (
    OpenVaultOutcome,
    detect_obsidian,
    open_vault_in_obsidian,
    registered_vault_paths,
    vault_uri,
)
from studio_contracts.local.common import ComponentState

from tests.knowledge.conftest import NO_OBSIDIAN, build_provider
from tests.knowledge.factories import write


def test_detection_without_any_candidate(tmp_path: Path) -> None:
    probe = detect_obsidian(environ={}, platform="win32", which=lambda _: None)
    assert probe.state is ComponentState.NOT_INSTALLED
    assert probe.executable is None


def test_detection_finds_a_local_install(tmp_path: Path) -> None:
    executable = write(tmp_path / "Obsidian/Obsidian.exe", "binary")
    probe = detect_obsidian(
        environ={"LOCALAPPDATA": str(tmp_path)}, platform="win32", which=lambda _: None
    )
    assert probe.state is ComponentState.READY
    assert probe.executable == executable


def test_detection_falls_back_to_path_lookup(tmp_path: Path) -> None:
    executable = write(tmp_path / "bin/obsidian", "binary")
    probe = detect_obsidian(
        environ={},
        platform="linux",
        which=lambda name: str(executable) if name == "obsidian" else None,
    )
    assert probe.state is ComponentState.READY
    assert probe.executable == executable


def test_registered_vaults_are_read_only(tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    write(
        appdata / "obsidian/obsidian.json",
        json.dumps({"vaults": {"a": {"path": "D:/Work/vault"}, "b": {"path": "D:/Other"}}}),
    )
    assert registered_vault_paths({"APPDATA": str(appdata)}, "win32") == (
        "D:/Other",
        "D:/Work/vault",
    )
    write(appdata / "obsidian/obsidian.json", "{not json")
    assert registered_vault_paths({"APPDATA": str(appdata)}, "win32") == ()


def test_open_is_refused_when_the_editor_is_absent(tmp_path: Path) -> None:
    launched: list[str] = []
    result = open_vault_in_obsidian(tmp_path, probe=NO_OBSIDIAN, opener=launched.append)
    assert result.outcome is OpenVaultOutcome.NOT_INSTALLED
    assert result.launched is False
    assert launched == []


def test_open_uses_one_bounded_uri(tmp_path: Path) -> None:
    launched: list[str] = []
    probe = detect_obsidian(environ={}, platform="win32", which=lambda _: None)
    installed = probe.__class__(state=ComponentState.READY, executable=tmp_path / "obsidian.exe")
    result = open_vault_in_obsidian(tmp_path, probe=installed, opener=launched.append)
    assert result.outcome is OpenVaultOutcome.OPENED
    assert result.launched is True
    assert launched == [vault_uri(tmp_path)]
    assert launched[0].startswith("obsidian://open?path=")


def test_open_refuses_a_missing_vault(tmp_path: Path) -> None:
    launched: list[str] = []
    installed = NO_OBSIDIAN.__class__(state=ComponentState.READY, executable=tmp_path / "obsidian")
    result = open_vault_in_obsidian(tmp_path / "absent", probe=installed, opener=launched.append)
    assert result.outcome is OpenVaultOutcome.VAULT_MISSING
    assert launched == []


def test_open_degrades_when_the_opener_fails(tmp_path: Path) -> None:
    def failing(_uri: str) -> None:
        raise OSError("no handler")

    installed = NO_OBSIDIAN.__class__(state=ComponentState.READY, executable=tmp_path / "obsidian")
    result = open_vault_in_obsidian(tmp_path, probe=installed, opener=failing)
    assert result.outcome is OpenVaultOutcome.UNAVAILABLE
    assert result.launched is False


def test_open_never_writes_the_editor_configuration(tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    config = write(appdata / "obsidian/obsidian.json", json.dumps({"vaults": {}}))
    before = config.read_bytes()
    installed = NO_OBSIDIAN.__class__(state=ComponentState.READY, executable=tmp_path / "obsidian")
    open_vault_in_obsidian(tmp_path, probe=installed, opener=lambda _uri: None)
    assert config.read_bytes() == before


def test_knowledge_works_without_the_editor(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    assert provider.status().state is ComponentState.READY
    assert provider.status().integrations[0].state is ComponentState.NOT_INSTALLED
