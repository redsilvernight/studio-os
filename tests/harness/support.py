from __future__ import annotations

import os
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from studio_client.harness.backup import BackupStore
from studio_client.harness.base import HarnessContext
from studio_client.harness.registry import HarnessRegistry
from studio_client.harness.service import HarnessService, WorkspaceInfo

WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
MCP_URL = "https://studio.example/mcp"
CLAUDE_VERSION_LINE = "2.1.272 (Claude Code)"
OPENCODE_VERSION_LINE = "1.18.31"


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
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    return env


@dataclass
class Rig:
    root: Path
    bin_dir: Path
    backups_root: Path
    env: dict[str, str]
    service: HarnessService
    flags: dict[str, bool]

    @property
    def context(self) -> HarnessContext:
        return HarnessContext(
            workspace_root=self.root, mcp_url=MCP_URL, env=self.env, probe_cwd=self.root.parent
        )


def make_rig(tmp_path: Path, *, claude: bool = True, opencode: bool = True) -> Rig:
    root = tmp_path / "workspace"
    root.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if claude:
        install_fake(bin_dir, "claude", CLAUDE_VERSION_LINE)
    if opencode:
        install_fake(bin_dir, "opencode", OPENCODE_VERSION_LINE)
    env = base_env(bin_dir)
    flags: dict[str, bool] = {"enabled": True}

    def lookup(workspace_id: UUID) -> WorkspaceInfo | None:
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(WORKSPACE_ID, root, MCP_URL, flags["enabled"])

    backups_root = tmp_path / "backups"
    service = HarnessService(
        HarnessRegistry(),
        BackupStore(backups_root),
        lookup,
        env=lambda: env,
        probe_cwd=tmp_path,
    )
    return Rig(root, bin_dir, backups_root, env, service, flags)


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
