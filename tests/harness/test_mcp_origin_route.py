"""The MCP URL written into harness configs is `<origin>/mcp` (MCP_PATH).

The Desktop setup assistant derives it from the server origin (the dashboard
domain), so the production Caddyfile must serve `/mcp` on that domain too;
otherwise the request falls through to the dashboard nginx (405).
"""

from __future__ import annotations

import re
from pathlib import Path

from studio_client.harness.base import MCP_PATH

CADDYFILE = Path(__file__).resolve().parents[2] / "docker" / "Caddyfile"


def _site_block(text: str, address: str) -> str:
    start = text.index(address + " {")
    depth = 0
    for i in range(start + len(address), len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f"unterminated site block {address}")


def test_dashboard_origin_serves_the_mcp_path() -> None:
    assert MCP_PATH == "/mcp"
    block = _site_block(CADDYFILE.read_text(encoding="utf-8"), "{$DASHBOARD_DOMAIN}")
    route = re.search(r"route /mcp\* \{\s*reverse_proxy mcp:8100\s*\}", block)
    assert route, "{$DASHBOARD_DOMAIN} must proxy /mcp* to the mcp service"
    assert route.start() < block.index("reverse_proxy dashboard:80")
