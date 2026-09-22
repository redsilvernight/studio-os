"""Claude Code: project-scoped MCP servers in `<workspace>/.mcp.json`."""

from __future__ import annotations

import re
from typing import Any

from studio_client.harness.base import STUDIO_MCP_TOKEN_ENV
from studio_client.harness.json_mcp import JsonMcpAdapter


class ClaudeCodeAdapter(JsonMcpAdapter):
    adapter_id = "claude-code"
    harness_id = "claude-code"
    display_name = "Claude Code"
    executable_names = ("claude",)
    identity = re.compile(r"^(?P<version>\d+\.\d+\.\d+)\s+\(Claude Code\)$")
    supported_major = 2
    candidate_files = (".mcp.json",)
    container_path = ("mcpServers",)

    def build_entry(self, mcp_url: str) -> dict[str, Any]:
        return {
            "type": "http",
            "url": mcp_url,
            "headers": {"Authorization": "Bearer ${" + STUDIO_MCP_TOKEN_ENV + "}"},
        }
