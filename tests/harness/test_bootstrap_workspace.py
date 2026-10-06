"""Bootstrap consumes the registered LocalWorkspaceConfig and HarnessService.detect,
and triggers the machine-local MCP wiring (end to end with the Codex adapter)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client import cli
from studio_client.bootstrap_workspace import (
    WorkspaceBootstrapError,
    build_harness_service,
    detect_harness_ids,
    find_workspace,
    wire_mcp,
)
from studio_client.harness.base import STUDIO_MCP_SERVER_NAME
from studio_client.harness.codex import CodexAdapter
from studio_client.harness.registry import HarnessRegistry
from studio_contracts.local.identity import ProfileRef
from studio_workspaces import register_workspace

from tests.harness.support import FakeProvisioner, base_env, install_fake

PROFILE = ProfileRef(profile_id="default", server_origin="https://studio.example")


class _Machine:
    def __init__(self, tmp_path: Path) -> None:
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.registry = tmp_path / "registry"
        bin_dir = tmp_path / "bin"
        install_fake(bin_dir, "codex", "codex-cli 0.46.0")
        self.env = base_env(bin_dir)
        self.provisioner = FakeProvisioner()
        register_workspace(self.registry, PROFILE, uuid4(), str(self.repo), project_slug="demo")
        self.config = find_workspace(self.registry, PROFILE, self.repo)
        self.service = build_harness_service(
            self.registry,
            self.config,
            registry=HarnessRegistry([CodexAdapter()]),
            provisioner=self.provisioner,
            env=lambda: self.env,
            home=lambda: self.home,
        )

    @property
    def codex_config(self) -> Path:
        return self.home / ".codex" / "config.toml"


def test_unregistered_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceBootstrapError, match="not a registered workspace"):
        find_workspace(tmp_path / "registry", PROFILE, tmp_path)


def test_detection_uses_the_harness_service(tmp_path: Path) -> None:
    machine = _Machine(tmp_path)
    assert detect_harness_ids(machine.service, machine.config) == ["codex"]


def test_wire_mcp_previews_without_confirmation(tmp_path: Path) -> None:
    machine = _Machine(tmp_path)
    (wiring,) = wire_mcp(machine.service, machine.config, ["codex"], confirm=False)
    assert not wiring.applied and wiring.plan.changes
    assert not machine.codex_config.exists()
    assert machine.provisioner.created == []


def test_wire_mcp_end_to_end_with_codex(tmp_path: Path) -> None:
    machine = _Machine(tmp_path)
    (wiring,) = wire_mcp(machine.service, machine.config, ["codex"], confirm=True)
    assert wiring.applied
    entry = tomllib.loads(machine.codex_config.read_text(encoding="utf-8"))["mcp_servers"][
        STUDIO_MCP_SERVER_NAME
    ]
    assert entry["url"] == "https://studio.example/mcp"
    (_, _, machine_id) = machine.provisioner.created[0]
    assert (
        entry["http_headers"]["Authorization"] == f"Bearer {machine.provisioner.tokens[machine_id]}"
    )
    (again,) = wire_mcp(machine.service, machine.config, ["codex"], confirm=True)
    assert not again.applied and not again.plan.changes
    assert len(machine.provisioner.created) == 1


def test_cli_init_detects_and_sync_wires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = _Machine(tmp_path)
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://studio.example")
    monkeypatch.setenv("PATH", machine.env["PATH"])
    monkeypatch.setenv("HOME", str(machine.home))
    monkeypatch.setenv("USERPROFILE", str(machine.home))
    common = ["--repo-root", str(machine.repo), "--registry-dir", str(machine.registry)]
    cli.main(
        ["bootstrap", "init", "--project-slug", "demo", "--project-name", "Demo", "--json", *common]
    )
    assert json.loads(capsys.readouterr().out)["harnesses"] == ["codex"]
    cli.main(["bootstrap", "sync", "--wire-mcp", "--json", *common])
    out = json.loads(capsys.readouterr().out)
    assert out["mcp"] == [{"adapter_id": "codex", "applied": False, "changes": 1}]
    assert not machine.codex_config.exists()


def test_cli_wire_mcp_needs_a_registered_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("STUDIO_CLIENT_API_BASE_URL", "https://studio.example")
    common = ["--repo-root", str(repo), "--registry-dir", str(tmp_path / "registry")]
    cli.main(
        [
            "bootstrap",
            "init",
            "--project-slug",
            "demo",
            "--project-name",
            "Demo",
            "--harness",
            "codex",
            *common,
        ]
    )
    with pytest.raises(SystemExit) as exc:
        cli.main(["bootstrap", "sync", "--wire-mcp", *common])
    assert exc.value.code == 1
