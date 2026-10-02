from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client.harness.base import STUDIO_MCP_SERVER_NAME, AdapterRefusal, HarnessContext
from studio_client.harness.claude_code import ClaudeCodeAdapter

from tests.harness.support import MCP_URL, base_env

TOKEN = "dedicated-token-value"  # noqa: S105 — test value


def make_ctx(tmp_path: Path) -> HarnessContext:
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return HarnessContext(
        workspace_root=workspace,
        mcp_url=MCP_URL,
        env=base_env(),
        probe_cwd=tmp_path,
        home=home,
    )


def configure(ctx: HarnessContext, adapter: ClaudeCodeAdapter) -> None:
    (ctx.home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    STUDIO_MCP_SERVER_NAME: adapter.build_entry(MCP_URL, TOKEN),
                    "obsidian-memory": {"command": "obsidian-mcp", "args": []},
                }
            }
        ),
        encoding="utf-8",
    )


def test_environment_writes_an_isolated_mcp_file_with_only_the_studio_entry(
    tmp_path: Path,
) -> None:
    adapter = ClaudeCodeAdapter()
    ctx = make_ctx(tmp_path)
    configure(ctx, adapter)
    isolation = tmp_path / "isolation"
    isolation.mkdir()

    overrides = adapter.headless_environment(ctx, model="sonnet", isolation_dir=isolation)

    assert overrides == {"STUDIO_CLIENT_MACHINE_TOKEN": TOKEN}
    mcp_file = isolation / "studio-mcp.json"
    payload = json.loads(mcp_file.read_text(encoding="utf-8"))
    assert list(payload["mcpServers"]) == [STUDIO_MCP_SERVER_NAME]
    entry = payload["mcpServers"][STUDIO_MCP_SERVER_NAME]
    assert entry["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert list(isolation.iterdir()) == [mcp_file]


def test_extra_argv_forces_the_model_and_locks_mcp_to_the_isolated_file(
    tmp_path: Path,
) -> None:
    adapter = ClaudeCodeAdapter()
    ctx = make_ctx(tmp_path)
    configure(ctx, adapter)
    isolation = tmp_path / "isolation"
    isolation.mkdir()
    adapter.headless_environment(ctx, model="sonnet", isolation_dir=isolation)

    extra = adapter.headless_extra_argv(ctx, model="sonnet", isolation_dir=isolation)

    assert extra == (
        "--mcp-config",
        str(isolation / "studio-mcp.json"),
        "--strict-mcp-config",
        "--allowedTools",
        f"Read,Edit,Write,Bash,Grep,Glob,mcp__{STUDIO_MCP_SERVER_NAME}",
        "--model",
        "sonnet",
    )


def test_extra_argv_without_model_keeps_the_harness_default(tmp_path: Path) -> None:
    adapter = ClaudeCodeAdapter()
    ctx = make_ctx(tmp_path)
    isolation = tmp_path / "isolation"
    isolation.mkdir()

    extra = adapter.headless_extra_argv(ctx, model=None, isolation_dir=isolation)

    assert "--model" not in extra
    assert "--strict-mcp-config" in extra
    allowed = extra[extra.index("--allowedTools") + 1]
    assert allowed.split(",")[:6] == ["Read", "Edit", "Write", "Bash", "Grep", "Glob"]
    assert allowed.endswith(f"mcp__{STUDIO_MCP_SERVER_NAME}")


def test_environment_refuses_without_the_studio_entry(tmp_path: Path) -> None:
    adapter = ClaudeCodeAdapter()
    ctx = make_ctx(tmp_path)
    isolation = tmp_path / "isolation"
    isolation.mkdir()

    with pytest.raises(AdapterRefusal) as refusal:
        adapter.headless_environment(ctx, model="sonnet", isolation_dir=isolation)

    assert refusal.value.reason == "mcp_entry_missing"
