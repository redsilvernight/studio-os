"""Claude Code: Studi'OS is a user-scoped MCP server, set through the official
CLI (`claude mcp add-json --scope user`), which owns `~/.claude.json`.

`~/.claude.json` is only ever *read* here, and only for the `studio-os` entry.
A project-scoped entry in `<workspace>/.mcp.json` shadows the user one and is
migrated away; a local-scope entry (kept per project inside `~/.claude.json`)
also shadows it and is reported for the user to remove.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from studio_client.harness.base import (
    STUDIO_MCP_SERVER_NAME,
    AdapterRefusal,
    HarnessContext,
    machine_token_env,
)
from studio_client.harness.fsafe import read_document, resolve_target
from studio_client.harness.json_mcp import JsonMcpAdapter
from studio_client.harness.probe import ProbeFailure, locate_executable, run_probe
from studio_client.hooks import GUARD_REL, HARNESSES

_USER_CONFIG = ".claude.json"
_ISOLATION_MCP_FILENAME = "studio-mcp.json"
_MAX_USER_CONFIG_BYTES = 16 * 1024 * 1024
_CLI_TIMEOUT_SECONDS = 30.0
_CLAUDE_SPEC = next(spec for spec in HARNESSES if spec.harness == "claude-code")


def _hook_command(script: Path) -> dict[str, object]:
    return {"type": "command", "command": f'pwsh -NoProfile -File "{script}"', "timeout": 10}


CliRunner = Callable[[Path, Sequence[str], Mapping[str, str], Path], int]
"""Runs `executable args` (no shell, scrubbed env) and returns its exit code.
Its output is never kept: a command line may carry the credential."""


def run_cli(executable: Path, args: Sequence[str], env: Mapping[str, str], cwd: Path) -> int:
    if executable.suffix.lower() in (".cmd", ".bat"):
        # cmd.exe re-parses its command line: a JSON argument is not safe there.
        raise AdapterRefusal("unsupported_launcher")
    try:
        return run_probe(executable, args, env=env, cwd=cwd, timeout=_CLI_TIMEOUT_SECONDS).exit_code
    except ProbeFailure as failure:
        raise AdapterRefusal("cli_" + failure.reason) from None


def _same_path(left: str, right: Path) -> bool:
    def norm(value: str) -> str:
        return os.path.normcase(os.path.normpath(value)).rstrip("\\/")

    return norm(left) == norm(str(right))


class ClaudeCodeAdapter(JsonMcpAdapter):
    adapter_id = "claude-code"
    harness_id = "claude-code"
    display_name = "Claude Code"
    executable_names = ("claude",)
    identity = re.compile(r"^(?P<version>\d+\.\d+\.\d+)\s+\(Claude Code\)$")
    supported_major = 2
    project_files = (".mcp.json",)
    container_path = ("mcpServers",)

    def __init__(self, cli_runner: CliRunner = run_cli) -> None:
        self._cli_runner = cli_runner

    def user_target(self, ctx: HarnessContext) -> str:
        return _USER_CONFIG

    def _user_config(self, ctx: HarnessContext) -> dict[str, Any] | None:
        document = read_document(
            resolve_target(ctx.home, _USER_CONFIG), max_bytes=_MAX_USER_CONFIG_BYTES
        )
        if document is None:
            return None
        try:
            data = json.loads(document.text)
        except ValueError:
            raise AdapterRefusal("invalid_json") from None
        if not isinstance(data, dict):
            raise AdapterRefusal("unexpected_shape")
        return data

    def read_user_entry(self, ctx: HarnessContext) -> dict[str, Any] | None:
        data = self._user_config(ctx)
        servers = None if data is None else data.get("mcpServers")
        entry = servers.get(STUDIO_MCP_SERVER_NAME) if isinstance(servers, dict) else None
        if entry is not None and not isinstance(entry, dict):
            raise AdapterRefusal("unexpected_shape")
        return entry

    def local_override(self, ctx: HarnessContext) -> bool:
        data = self._user_config(ctx)
        projects = None if data is None else data.get("projects")
        if not isinstance(projects, dict):
            return False
        for path, project in projects.items():
            if not isinstance(project, dict) or not _same_path(str(path), ctx.workspace_root):
                continue
            servers = project.get("mcpServers")
            if isinstance(servers, dict) and STUDIO_MCP_SERVER_NAME in servers:
                return True
        return False

    def _executable(self, ctx: HarnessContext) -> Path:
        executable = locate_executable(
            self.executable_names,
            path_env=ctx.env_value("PATH"),
            excluded_dirs=[ctx.workspace_root],
        )
        if executable is None:
            raise AdapterRefusal("executable_not_found")
        return executable

    def _cli(self, ctx: HarnessContext, executable: Path, args: Sequence[str]) -> None:
        try:
            code = self._cli_runner(executable, args, ctx.env, ctx.probe_cwd)
        except AdapterRefusal:
            raise
        except Exception:  # noqa: BLE001 — the command line may hold the credential
            raise AdapterRefusal("cli_failed") from None
        if code != 0:
            raise AdapterRefusal("cli_failed")

    def write_user_entry(self, ctx: HarnessContext, entry: dict[str, object]) -> None:
        executable = self._executable(ctx)
        if self.read_user_entry(ctx) is not None:
            self._cli(ctx, executable, ("mcp", "remove", "--scope", "user", STUDIO_MCP_SERVER_NAME))
        payload = json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
        self._cli(
            ctx,
            executable,
            ("mcp", "add-json", "--scope", "user", STUDIO_MCP_SERVER_NAME, payload),
        )

    def remove_user_entry(self, ctx: HarnessContext) -> None:
        if self.read_user_entry(ctx) is None:
            return
        self._cli(
            ctx,
            self._executable(ctx),
            ("mcp", "remove", "--scope", "user", STUDIO_MCP_SERVER_NAME),
        )

    def build_entry(self, mcp_url: str, token: str) -> dict[str, object]:
        return {"type": "http", "url": mcp_url, "headers": {"Authorization": f"Bearer {token}"}}

    _BASE_TOOLS = "Read,Edit,Write,Bash,Grep,Glob"

    def headless_argv(self, prompt: str) -> tuple[str, ...]:
        return (
            "-p",
            prompt,
            "--output-format",
            "text",
            "--permission-mode",
            "acceptEdits",
        )

    def headless_environment(
        self, ctx: HarnessContext, *, model: str | None, isolation_dir: Path
    ) -> dict[str, str]:
        entry = self.read_user_entry(ctx)
        if entry is None:
            raise AdapterRefusal("mcp_entry_missing")
        payload = {"mcpServers": {STUDIO_MCP_SERVER_NAME: entry}}
        try:
            isolation_dir.mkdir(parents=True, exist_ok=True)
            self._isolation_mcp_path(isolation_dir).write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except OSError:
            raise AdapterRefusal("isolation_failed") from None
        return machine_token_env(entry)

    def headless_extra_argv(
        self, ctx: HarnessContext, *, model: str | None, isolation_dir: Path
    ) -> tuple[str, ...]:
        argv: tuple[str, ...] = (
            "--mcp-config",
            str(self._isolation_mcp_path(isolation_dir)),
            "--strict-mcp-config",
            "--allowedTools",
            f"{self._BASE_TOOLS},mcp__{STUDIO_MCP_SERVER_NAME}",
        )
        settings = self.isolation_settings(ctx)
        if settings is not None:
            argv += ("--setting-sources", "project", "--settings", settings)
        if model:
            argv += ("--model", model)
        return argv

    def isolation_settings(self, ctx: HarnessContext) -> str | None:
        """Minimal settings JSON keeping only the Studio session hook (agent
        identity) and the git guard. Combined with `--setting-sources project`
        it keeps a remotely launched harness from running the operator's own
        hooks (bonsai delegation, rtk, office hooks) that are meant for
        interactive local sessions. `None` when the Studio session hook is not
        deployed, leaving the previous behaviour unchanged."""
        session_hook = ctx.home / _CLAUDE_SPEC.hook_rel
        if not session_hook.is_file():
            return None
        hooks: dict[str, list[dict[str, object]]] = {
            "SessionStart": [{"hooks": [_hook_command(session_hook)]}]
        }
        guard = ctx.home / GUARD_REL
        if guard.is_file():
            hooks["PreToolUse"] = [{"matcher": "Bash|PowerShell", "hooks": [_hook_command(guard)]}]
        return json.dumps({"hooks": hooks})

    def _isolation_mcp_path(self, isolation_dir: Path) -> Path:
        return isolation_dir / _ISOLATION_MCP_FILENAME
