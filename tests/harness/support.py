from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from studio_client.harness.backup import BackupStore
from studio_client.harness.base import HarnessContext
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.credentials import CredentialStore, ProvisionError
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.registry import HarnessRegistry
from studio_client.harness.service import HarnessService, McpProbe, WorkspaceInfo

WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
ORIGIN = "https://studio.example"
MCP_URL = f"{ORIGIN}/mcp"
CLAUDE_VERSION_LINE = "2.1.272 (Claude Code)"
OPENCODE_VERSION_LINE = "1.18.31"
OPENCODE_CONFIG = ".config/opencode/opencode.json"


def install_fake(
    directory: Path,
    name: str,
    output: str,
    *,
    exit_code: int = 0,
    sleep_seconds: int = 0,
) -> Path:
    """A stand-in harness executable that prints `output` for any argument."""
    directory.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        path = directory / f"{name}.cmd"
        lines = ["@echo off"]
        if sleep_seconds:
            lines.append(f"ping -n {sleep_seconds + 1} 127.0.0.1 >nul")
        lines += [f"echo {output}", f"exit /b {exit_code}"]
        path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    else:
        path = directory / name
        lines = ["#!/bin/sh"]
        if sleep_seconds:
            lines.append(f"sleep {sleep_seconds}")
        lines += [f"echo '{output}'", f"exit {exit_code}"]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def base_env(*bin_dirs: Path) -> dict[str, str]:
    """An environment whose PATH holds only `bin_dirs` (plus what a process
    needs to start), so a test never sees the real machine's harnesses."""
    env = {key: value for key, value in os.environ.items() if key.upper() != "PATH"}
    system = os.environ.get("SystemRoot", "")
    entries = [str(directory) for directory in bin_dirs]
    if system:
        entries += [str(Path(system) / "System32")]
    env["PATH"] = os.pathsep.join(entries)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "STUDIO_MCP_MACHINE_TOKEN"):
        env.pop(name, None)
    for key in [key for key in env if key.upper() == "XDG_CONFIG_HOME"]:
        del env[key]
    return env


@dataclass
class FakeClaudeCli:
    """Plays `claude mcp add-json|remove --scope user` against `<home>/.claude.json`
    without spawning anything. Keeps only the verbs it was asked to run."""

    home: Path
    fail: bool = False
    calls: list[tuple[str, ...]] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return self.home / ".claude.json"

    def __call__(
        self, executable: Path, args: Sequence[str], env: Mapping[str, str], cwd: Path
    ) -> int:
        self.calls.append(tuple(args[:5]))
        if self.fail:
            return 1
        data = json.loads(self.path.read_text("utf-8")) if self.path.exists() else {}
        servers = data.setdefault("mcpServers", {})
        if list(args[:4]) == ["mcp", "add-json", "--scope", "user"]:
            if args[4] in servers:
                return 1
            servers[args[4]] = json.loads(args[5])
        elif list(args[:4]) == ["mcp", "remove", "--scope", "user"]:
            if servers.pop(args[4], None) is None:
                return 1
        else:
            return 2
        self.path.write_text(json.dumps(data, indent=2), "utf-8")
        return 0


@dataclass
class FakeProvisioner:
    """Creates dedicated machines in memory; `fail_create` / `fail_revoke`
    hold the ProvisionError reason to raise."""

    fail_create: str | None = None
    fail_revoke: str | None = None
    created: list[tuple[str, str, str]] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)
    tokens: dict[str, str] = field(default_factory=dict)

    def create(self, origin: str, display_name: str) -> tuple[str, str]:
        if self.fail_create:
            raise ProvisionError(self.fail_create)
        machine_id = str(uuid4())
        token = f"sk_test_{uuid4().hex}"
        self.created.append((origin, display_name, machine_id))
        self.tokens[machine_id] = token
        return machine_id, token

    def revoke(self, origin: str, machine_id: str) -> None:
        if self.fail_revoke:
            raise ProvisionError(self.fail_revoke)
        self.revoked.append(machine_id)

    @property
    def active(self) -> list[str]:
        return [m for _, _, m in self.created if m not in self.revoked]


@dataclass
class Rig:
    root: Path
    home: Path
    bin_dir: Path
    backups_root: Path
    env: dict[str, str]
    service: HarnessService
    flags: dict[str, bool]
    cli: FakeClaudeCli
    provisioner: FakeProvisioner
    credentials: CredentialStore

    @property
    def context(self) -> HarnessContext:
        return HarnessContext(
            workspace_root=self.root,
            mcp_url=MCP_URL,
            env=self.env,
            probe_cwd=self.root.parent,
            home=self.home,
        )

    @property
    def claude_config(self) -> Path:
        return self.home / ".claude.json"

    @property
    def opencode_config(self) -> Path:
        return self.home / OPENCODE_CONFIG

    def user_entry(self, adapter_id: str) -> dict[str, object] | None:
        path = self.claude_config if adapter_id == "claude-code" else self.opencode_config
        if not path.exists():
            return None
        data = json.loads(path.read_text("utf-8"))
        container = data.get("mcpServers" if adapter_id == "claude-code" else "mcp") or {}
        return container.get("studio-os")


def build_service(
    rig_root: Path,
    home: Path,
    backups_root: Path,
    env: dict[str, str],
    flags: dict[str, bool],
    cli: FakeClaudeCli,
    provisioner: FakeProvisioner,
    credentials: CredentialStore,
    probe_cwd: Path,
    mcp_probe: McpProbe | None = None,
) -> HarnessService:
    def lookup(workspace_id: UUID) -> WorkspaceInfo | None:
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(WORKSPACE_ID, rig_root, MCP_URL, flags["enabled"])

    return HarnessService(
        HarnessRegistry([ClaudeCodeAdapter(cli_runner=cli), OpenCodeAdapter()]),
        BackupStore(backups_root),
        lookup,
        credentials=credentials,
        provisioner=provisioner,
        env=lambda: env,
        home=lambda: home,
        probe_cwd=probe_cwd,
        mcp_probe=mcp_probe,
        host_name=lambda tool: f"TEST-HOST · {tool}",
    )


def make_rig(
    tmp_path: Path,
    *,
    claude: bool = True,
    opencode: bool = True,
    mcp_probe: McpProbe | None = None,
) -> Rig:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if claude:
        install_fake(bin_dir, "claude", CLAUDE_VERSION_LINE)
    if opencode:
        install_fake(bin_dir, "opencode", OPENCODE_VERSION_LINE)
    env = base_env(bin_dir)
    flags: dict[str, bool] = {"enabled": True}
    backups_root = tmp_path / "backups"
    cli = FakeClaudeCli(home)
    provisioner = FakeProvisioner()
    credentials = CredentialStore(tmp_path / "state" / "harness-credentials.json")
    service = build_service(
        root, home, backups_root, env, flags, cli, provisioner, credentials, tmp_path, mcp_probe
    )
    return Rig(
        root, home, bin_dir, backups_root, env, service, flags, cli, provisioner, credentials
    )


def restarted(rig: Rig) -> Rig:
    """The same machine after a daemon restart: fresh service, same disk."""
    service = build_service(
        rig.root,
        rig.home,
        rig.backups_root,
        rig.env,
        rig.flags,
        rig.cli,
        rig.provisioner,
        rig.credentials,  # reads the disk on every call
        rig.root.parent,
    )
    return Rig(
        rig.root,
        rig.home,
        rig.bin_dir,
        rig.backups_root,
        rig.env,
        service,
        rig.flags,
        rig.cli,
        rig.provisioner,
        rig.credentials,
    )


def env_with(env: Mapping[str, str], **extra: str) -> dict[str, str]:
    return {**env, **extra}


def fake_harness_env(
    tmp_path: Path, *, claude: bool = True, opencode: bool = True
) -> dict[str, str]:
    """The real process environment with PATH swapped for stand-in harness
    executables, so a scenario never depends on which harnesses (or which
    versions) happen to be installed on the machine running the suite."""
    bin_dir = tmp_path / "fake-bin"
    if claude:
        install_fake(bin_dir, "claude", CLAUDE_VERSION_LINE)
    if opencode:
        install_fake(bin_dir, "opencode", OPENCODE_VERSION_LINE)
    return base_env(bin_dir)
