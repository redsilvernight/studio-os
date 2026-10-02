from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client.harness.base import STUDIO_MCP_SERVER_NAME, AdapterRefusal, HarnessContext
from studio_client.harness.opencode import OpenCodeAdapter

from tests.harness.support import MCP_URL, base_env, install_fake

TOKEN = "dedicated-token-value"  # noqa: S105 — test value


def make_ctx(tmp_path: Path) -> HarnessContext:
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    bin_dir = tmp_path / "bin"
    install_fake(bin_dir, "opencode", "1.2.3")
    return HarnessContext(
        workspace_root=workspace,
        mcp_url=MCP_URL,
        env=base_env(bin_dir),
        probe_cwd=tmp_path,
        home=home,
    )


def configure(ctx: HarnessContext, adapter: OpenCodeAdapter) -> Path:
    adapter.write_user_entry(ctx, adapter.build_entry(MCP_URL, TOKEN))
    config_file = ctx.home / ".config" / "opencode" / "opencode.json"
    document = json.loads(config_file.read_text(encoding="utf-8"))
    document["mcp"]["obsidian-memory"] = {"type": "local", "command": ["x"]}
    document["model"] = "provider/unusable"
    config_file.write_text(json.dumps(document), encoding="utf-8")
    plugins = config_file.parent / "plugins"
    plugins.mkdir()
    (plugins / "studio-os.js").write_text("// plugin", encoding="utf-8")
    return config_file


def test_environment_forces_the_model_and_keeps_only_the_studio_mcp(tmp_path: Path) -> None:
    adapter = OpenCodeAdapter()
    ctx = make_ctx(tmp_path)
    configure(ctx, adapter)
    isolation = tmp_path / "isolation"
    isolation.mkdir()

    overrides = adapter.headless_environment(ctx, model="anthropic/sonnet", isolation_dir=isolation)

    inline = json.loads(overrides["OPENCODE_CONFIG_CONTENT"])
    assert inline["model"] == "anthropic/sonnet"
    assert list(inline["mcp"]) == [STUDIO_MCP_SERVER_NAME]
    assert inline["mcp"][STUDIO_MCP_SERVER_NAME]["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert overrides["XDG_CONFIG_HOME"] == str(isolation)
    assert overrides["STUDIO_CLIENT_MACHINE_TOKEN"] == TOKEN
    assert list(isolation.rglob("opencode.json")) == []
    assert (isolation / "opencode" / "plugins" / "studio-os.js").read_text() == "// plugin"


def test_environment_without_model_leaves_the_default(tmp_path: Path) -> None:
    adapter = OpenCodeAdapter()
    ctx = make_ctx(tmp_path)
    configure(ctx, adapter)
    isolation = tmp_path / "isolation"
    isolation.mkdir()

    overrides = adapter.headless_environment(ctx, model=None, isolation_dir=isolation)

    assert "model" not in json.loads(overrides["OPENCODE_CONFIG_CONTENT"])


def test_environment_refuses_without_the_studio_entry(tmp_path: Path) -> None:
    adapter = OpenCodeAdapter()
    ctx = make_ctx(tmp_path)
    isolation = tmp_path / "isolation"
    isolation.mkdir()

    with pytest.raises(AdapterRefusal) as refusal:
        adapter.headless_environment(ctx, model="m", isolation_dir=isolation)

    assert refusal.value.reason == "mcp_entry_missing"
