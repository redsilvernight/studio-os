from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from studio_client.harness.base import (
    STUDIO_MCP_SERVER_NAME,
    AdapterRefusal,
    DetectionState,
    HarnessContext,
)
from studio_client.harness.codex import CodexAdapter
from studio_client.harness.registry import default_adapters

from tests.harness.support import MCP_URL, base_env, install_fake

TOKEN = "dedicated-token-value"  # noqa: S105 — test value
ENTRY_HEADER = f'[mcp_servers."{STUDIO_MCP_SERVER_NAME}"]'


def make_ctx(tmp_path: Path, *, installed: bool = True, **env_extra: str) -> HarnessContext:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    if installed:
        install_fake(bin_dir, "codex", "codex-cli 0.46.0")
    else:
        bin_dir.mkdir(exist_ok=True)
    env = {**base_env(bin_dir), **env_extra}
    return HarnessContext(
        workspace_root=workspace, mcp_url=MCP_URL, env=env, probe_cwd=tmp_path, home=home
    )


def config_path(ctx: HarnessContext) -> Path:
    return ctx.home / ".codex" / "config.toml"


def test_codex_is_a_default_adapter() -> None:
    assert "codex" in [adapter.adapter_id for adapter in default_adapters()]


def test_detect_states(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    assert adapter.detect(make_ctx(tmp_path, installed=False)).state is DetectionState.NOT_INSTALLED
    ctx = make_ctx(tmp_path)
    detection = adapter.detect(ctx)
    assert detection.state is DetectionState.CONFIGURATION_MISSING
    assert detection.version == "0.46.0"


def test_write_creates_the_config_and_detects_configured(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    ctx = make_ctx(tmp_path)
    plan = adapter.plan(ctx)
    assert plan.user_entry is not None and plan.user_entry.target == ".codex/config.toml"
    adapter.write_user_entry(ctx, adapter.build_entry(MCP_URL, TOKEN))
    data = tomllib.loads(config_path(ctx).read_text(encoding="utf-8"))
    assert data["mcp_servers"][STUDIO_MCP_SERVER_NAME] == {
        "url": MCP_URL,
        "http_headers": {"Authorization": f"Bearer {TOKEN}"},
    }
    detection = adapter.detect(ctx)
    assert detection.state is DetectionState.CONFIGURED
    assert adapter.plan(ctx).empty
    assert TOKEN not in repr(plan)


def test_write_preserves_comments_and_other_servers(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    ctx = make_ctx(tmp_path)
    path = config_path(ctx)
    path.parent.mkdir()
    original = (
        '# my codex\nmodel = "gpt-5"\n\n'
        '[mcp_servers.other]\ncommand = "x"  # keep\n\n'
        f'{ENTRY_HEADER}\nurl = "https://old.example/mcp"\n\n'
        f'[mcp_servers.other.env]\nA = "1"\n\n[profiles.p]\nmodel = "m"\n'
    )
    path.write_text(original, encoding="utf-8")
    adapter.write_user_entry(ctx, adapter.build_entry(MCP_URL, TOKEN))
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# my codex\n")
    assert 'command = "x"  # keep' in text
    data = tomllib.loads(text)
    assert data["model"] == "gpt-5"
    assert data["profiles"]["p"] == {"model": "m"}
    assert data["mcp_servers"]["other"] == {"command": "x", "env": {"A": "1"}}
    assert data["mcp_servers"][STUDIO_MCP_SERVER_NAME]["url"] == MCP_URL


def test_remove_only_drops_the_studio_entry(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    ctx = make_ctx(tmp_path)
    path = config_path(ctx)
    path.parent.mkdir()
    path.write_text('model = "m"\n\n[mcp_servers.other]\ncommand = "x"\n', encoding="utf-8")
    adapter.write_user_entry(ctx, adapter.build_entry(MCP_URL, TOKEN))
    adapter.remove_user_entry(ctx)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data == {"model": "m", "mcp_servers": {"other": {"command": "x"}}}
    assert adapter.read_user_entry(ctx) is None
    adapter.remove_user_entry(ctx)


def test_crlf_is_kept(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    ctx = make_ctx(tmp_path)
    path = config_path(ctx)
    path.parent.mkdir()
    path.write_bytes(b'model = "m"\r\n')
    adapter.write_user_entry(ctx, adapter.build_entry(MCP_URL, TOKEN))
    raw = path.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


@pytest.mark.parametrize(
    "content",
    [
        f'mcp_servers = {{ "{STUDIO_MCP_SERVER_NAME}" = {{ url = "u" }} }}\n',
        f'[mcp_servers]\n"{STUDIO_MCP_SERVER_NAME}".url = "u"\n',
    ],
)
def test_unsupported_layouts_are_refused_untouched(tmp_path: Path, content: str) -> None:
    adapter = CodexAdapter()
    ctx = make_ctx(tmp_path)
    path = config_path(ctx)
    path.parent.mkdir()
    path.write_text(content, encoding="utf-8")
    with pytest.raises(AdapterRefusal) as refusal:
        adapter.write_user_entry(ctx, adapter.build_entry(MCP_URL, TOKEN))
    assert refusal.value.reason == "unsupported_layout"
    assert path.read_text(encoding="utf-8") == content


def test_invalid_toml_is_refused(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    ctx = make_ctx(tmp_path)
    config_path(ctx).parent.mkdir()
    config_path(ctx).write_text("not = = toml", encoding="utf-8")
    assert adapter.detect(ctx).state is DetectionState.CONFIGURATION_INVALID
    with pytest.raises(AdapterRefusal):
        adapter.plan(ctx)


def test_codex_home_outside_home_is_refused(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    ctx = make_ctx(tmp_path, CODEX_HOME=str(tmp_path / "elsewhere"))
    assert adapter.detect(ctx).state is DetectionState.CONFIGURATION_INVALID
    inside = make_ctx(tmp_path, CODEX_HOME=str(tmp_path / "home" / "cx"))
    assert adapter.user_target(inside) == "cx/config.toml"
