from __future__ import annotations

import os
from typing import Literal, get_args

from mcp.server.mcpserver import MCPServer

from studio_mcp.tools.events import studio_emit_event
from studio_mcp.tools.projects import studio_get_project_state, studio_get_projects

_Transport = Literal["stdio", "sse", "streamable-http"]


def create_server() -> MCPServer:
    server = MCPServer(name="studio-os")

    server.add_tool(
        studio_get_projects,
        name="studio_get_projects",
        description=(
            "List active Studio OS projects (id, slug, name) — use to discover "
            "which projects exist before targeting one."
        ),
    )
    server.add_tool(
        studio_get_project_state,
        name="studio_get_project_state",
        description=(
            "Get a project's active tasks and active resource claims by project_id "
            "(UUID string) — the bootstrap read before starting work on a project."
        ),
    )
    server.add_tool(
        studio_emit_event,
        name="studio_emit_event",
        description=(
            "Emit a Studio OS event (task/session/claim/decision/ai_work/... lifecycle) "
            "so other agents and the dashboard see it. event_type must match "
            "TECH/03_EVENT_CONTRACT.md (e.g. 'task.started')."
        ),
    )
    return server


mcp = create_server()


if __name__ == "__main__":
    # Local/dev default: stdio. Docker/Caddy deployment (mcp.example.com,
    # TECH/01_ARCHITECTURE.md) overrides via STUDIO_MCP_TRANSPORT=streamable-http.
    _raw_transport = os.environ.get("STUDIO_MCP_TRANSPORT", "stdio")
    if _raw_transport not in get_args(_Transport):
        raise ValueError(f"invalid STUDIO_MCP_TRANSPORT: {_raw_transport!r}")

    if _raw_transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # 0.0.0.0: must be reachable from Caddy in another container, not just
        # loopback. Port 8100 kept distinct from the api service's 8000 —
        # matches docker/docker-compose.yml and docker/Caddyfile.
        host = os.environ.get("STUDIO_MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("STUDIO_MCP_PORT", "8100"))
        mcp.run(transport=_raw_transport, host=host, port=port)  # type: ignore[call-overload]
