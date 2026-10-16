from __future__ import annotations

import json
from pathlib import Path

from studio_client.harness.base import HarnessContext, entry_with_credential
from studio_client.harness.claude_code import ClaudeCodeAdapter

ISSUER = "http://127.0.0.1:8865/mcp"


def test_entry_with_credential_points_at_issuing_server() -> None:
    entry = {
        "type": "http",
        "url": "https://elsewhere.example/mcp",
        "headers": {"Authorization": "Bearer durable", "X-Keep": "1"},
    }

    replaced = entry_with_credential(entry, "ephemeral", url=ISSUER)

    assert replaced["url"] == ISSUER
    assert replaced["headers"] == {"Authorization": "Bearer ephemeral", "X-Keep": "1"}
    assert entry["url"] == "https://elsewhere.example/mcp"


def test_claude_code_isolation_config_uses_launch_server(tmp_path: Path) -> None:
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "studio-os": {
                        "type": "http",
                        "url": "https://elsewhere.example/mcp",
                        "headers": {"Authorization": "Bearer durable"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    ctx = HarnessContext(
        workspace_root=tmp_path, mcp_url=ISSUER, env={}, probe_cwd=tmp_path, home=tmp_path
    )
    isolation = tmp_path / "isolation"

    ClaudeCodeAdapter().headless_environment(
        ctx, model=None, isolation_dir=isolation, credential="ephemeral"
    )

    written = json.loads((isolation / "studio-mcp.json").read_text(encoding="utf-8"))
    server = written["mcpServers"]["studio-os"]
    assert server["url"] == ISSUER
    assert server["headers"]["Authorization"] == "Bearer ephemeral"
