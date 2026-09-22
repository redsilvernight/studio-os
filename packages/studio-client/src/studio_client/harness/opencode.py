"""OpenCode: project-scoped MCP servers under `mcp` in `<workspace>/opencode.json[c]`."""

from __future__ import annotations

import re
from typing import Any

from studio_client.harness.base import STUDIO_MCP_TOKEN_ENV
from studio_client.harness.json_mcp import JsonMcpAdapter


class OpenCodeAdapter(JsonMcpAdapter):
    adapter_id = "opencode"
    harness_id = "opencode"
    display_name = "OpenCode"
    executable_names = ("opencode",)
    identity = re.compile(r"^(?P<version>\d+\.\d+\.\d+)$")
    supported_major = 1
    candidate_files = ("opencode.json", "opencode.jsonc")
    container_path = ("mcp",)
    comments = True
    trailing_commas = True

    def build_entry(self, mcp_url: str) -> dict[str, Any]:
        return {
            "type": "remote",
            "url": mcp_url,
            "enabled": True,
            "headers": {"Authorization": "Bearer {env:" + STUDIO_MCP_TOKEN_ENV + "}"},
        }
