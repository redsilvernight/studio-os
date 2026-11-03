"""`agents ensure --harness-credential` (DEC-0104/DEC-0226): the session-start
hook must register the agent under the machine the harness itself talks to.

Each (workstation, tool) pair owns its own Studi'OS machine, and the Desktop
writes that machine's credential into the tool's own MCP entry. Reading the
Desktop's credential instead registered the agent under a machine the harness
never uses, so `studio_start_work` refused it with `actor_not_owned` and a new
agent appeared at every conversation. The credential is adopted only for the
origin the session is bound to, is never written, and never appears in a repr.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client.harness.base import STUDIO_MCP_SERVER_NAME
from studio_client.harness.session_credential import read_session_credential

ORIGIN = "https://studio.example.test"
OTHER_ORIGIN = "https://other.example.test"


def _mcp_url(origin: str = ORIGIN) -> str:
    return f"{origin}/mcp"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _opencode_config(origin: str = ORIGIN, token: str = "opencode-credential") -> str:
    return (
        "// commentaire utilisateur, conserve\n"
        "{\n"
        '  "theme": "dark",\n'
        '  "mcp": {\n'
        f'    "{STUDIO_MCP_SERVER_NAME}": {{\n'
        '      "type": "remote",\n'
        f'      "url": "{_mcp_url(origin)}",\n'
        '      "enabled": true,\n'
        '      "headers": { "Authorization": "Bearer ' + token + '" },\n'
        "    },\n"
        "  },\n"
        "}\n"
    )


def _claude_config(origin: str = ORIGIN, token: str = "claude-credential") -> str:
    return json.dumps(
        {
            "mcpServers": {
                STUDIO_MCP_SERVER_NAME: {
                    "type": "http",
                    "url": _mcp_url(origin),
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            }
        }
    )


def _codex_config(origin: str = ORIGIN, token: str = "codex-credential") -> str:
    return (
        "[launch_models]\n"
        'opencode = "opencode/big-pickle"\n'
        "\n"
        f"[mcp_servers.{STUDIO_MCP_SERVER_NAME}]\n"
        f'url = "{_mcp_url(origin)}"\n'
        "\n"
        f"[mcp_servers.{STUDIO_MCP_SERVER_NAME}.http_headers]\n"
        f'Authorization = "Bearer {token}"\n'
    )


def _home_with(tmp_path: Path, harness: str, text: str) -> Path:
    targets = {
        "opencode": Path(".config") / "opencode" / "opencode.jsonc",
        "claude-code": Path(".claude.json"),
        "codex": Path(".codex") / "config.toml",
    }
    _write(tmp_path / targets[harness], text)
    return tmp_path


@pytest.mark.parametrize(
    ("harness", "rendered", "token"),
    [
        ("opencode", _opencode_config(), "opencode-credential"),
        ("claude-code", _claude_config(), "claude-credential"),
        ("codex", _codex_config(), "codex-credential"),
    ],
)
def test_reads_the_harness_own_credential(
    tmp_path: Path, harness: str, rendered: str, token: str
) -> None:
    home = _home_with(tmp_path, harness, rendered)

    credential = read_session_credential(harness, home=home, origin=ORIGIN)

    assert credential is not None
    assert credential.harness == harness
    assert credential.origin == ORIGIN
    assert credential.token == token
    assert token not in repr(credential)


@pytest.mark.parametrize("harness", ["opencode", "claude-code", "codex"])
def test_another_server_is_never_adopted(tmp_path: Path, harness: str) -> None:
    rendered = {
        "opencode": _opencode_config(origin=OTHER_ORIGIN),
        "claude-code": _claude_config(origin=OTHER_ORIGIN),
        "codex": _codex_config(origin=OTHER_ORIGIN),
    }[harness]
    home = _home_with(tmp_path, harness, rendered)

    assert read_session_credential(harness, home=home, origin=ORIGIN) is None


@pytest.mark.parametrize("harness", ["opencode", "claude-code", "codex"])
def test_missing_config_is_a_miss(tmp_path: Path, harness: str) -> None:
    assert read_session_credential(harness, home=tmp_path, origin=ORIGIN) is None


@pytest.mark.parametrize("harness", ["opencode", "claude-code", "codex"])
def test_entry_without_bearer_is_a_miss(tmp_path: Path, harness: str) -> None:
    rendered = {
        "opencode": _opencode_config().replace('"Bearer opencode-credential"', '""'),
        "claude-code": _claude_config().replace("Bearer claude-credential", ""),
        "codex": _codex_config().replace("Bearer codex-credential", ""),
    }[harness]
    home = _home_with(tmp_path, harness, rendered)

    assert read_session_credential(harness, home=home, origin=ORIGIN) is None


def test_unknown_harness_is_a_miss(tmp_path: Path) -> None:
    assert read_session_credential("not-a-harness", home=tmp_path, origin=ORIGIN) is None


def test_unparsable_config_never_blocks_a_session(tmp_path: Path) -> None:
    home = _home_with(tmp_path, "opencode", "{ this is not json")

    assert read_session_credential("opencode", home=home, origin=ORIGIN) is None
