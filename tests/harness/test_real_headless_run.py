"""A real headless run of an actually installed harness, skipped when its
binary is absent: the suite never assumes a harness exists on the machine."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from studio_client.harness.claude_code import ClaudeCodeAdapter

PROMPT = "Reply with exactly this word and nothing else: PING"
TIMEOUT_SECONDS = 180


def _claude() -> str | None:
    return shutil.which("claude")


def _needs_auth(output: str) -> bool:
    lowered = output.lower()
    return any(
        token in lowered
        for token in (
            "api key",
            "apikey",
            "not authenticated",
            "not logged in",
            "login",
            "unauthorized",
            "401",
            "oauth",
        )
    )


def test_real_claude_headless_run_with_strict_isolated_mcp(tmp_path: Path) -> None:
    executable = _claude()
    if executable is None:
        pytest.skip("claude is not installed on this machine")
    workdir = tmp_path / "work"
    workdir.mkdir()
    mcp_file = tmp_path / "studio-mcp.json"
    mcp_file.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    adapter = ClaudeCodeAdapter()
    argv = [
        *adapter.headless_argv(PROMPT),
        "--mcp-config",
        str(mcp_file),
        "--strict-mcp-config",
    ]
    try:
        completed = subprocess.run(
            [executable, *argv],
            cwd=workdir,
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("real claude headless run timed out")
    combined = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0 and _needs_auth(combined):
        pytest.skip("claude is installed but not authenticated on this machine")
    assert completed.returncode == 0, combined[-2000:]
    assert "PING" in (completed.stdout or "")
