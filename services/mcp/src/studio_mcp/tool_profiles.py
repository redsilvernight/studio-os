"""Server-side tool profiles for the `studio-os` MCP server.

A profile is the set of tools the server advertises on `tools/list` and accepts
on `tools/call` for one connection. `session` (the default) exposes the tools a
regular agent session needs (DEC-0183); `admin` exposes the full registered
surface for project initialization, roadmaps, transfers, runtime and
definition management. The profile is selected per connection, never per tool:
an HTTP caller sends `X-Studio-Tool-Profile: admin`, a stdio harness sets
`STUDIO_MCP_TOOL_PROFILE=admin`. Any other value falls back to the default.

This is a noise/token control, not an authorization boundary: role and project
checks still live in the shared services (DEC-0046 §4).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.types import CallToolResult, ListToolsResult, TextContent

from studio_mcp.access_registry import MCP_ACCESS

SESSION_PROFILE = "session"
ADMIN_PROFILE = "admin"
DEFAULT_TOOL_PROFILE = SESSION_PROFILE

TOOL_PROFILE_HEADER = "x-studio-tool-profile"
TOOL_PROFILE_ENV = "STUDIO_MCP_TOOL_PROFILE"

SESSION_TOOL_PROFILE: frozenset[str] = frozenset(
    {
        "studio_get_projects",
        "studio_get_project_state",
        "studio_prepare_context",
        "studio_start_work",
        "studio_sync",
        "studio_coordinate",
        "studio_log_ai_work",
        "studio_handoff",
        "studio_create_task",
        "studio_update_task",
        "studio_claim_resources",
        "studio_release_resource",
        "studio_add_decision",
        "studio_accept_decision",
        "studio_supersede_decision",
        "studio_discover_definitions",
        "studio_resolve_agent",
        "studio_get_task",
        "studio_get_active_tasks",
        "studio_get_decisions",
        "studio_get_resource_claims",
        "studio_get_recent_changes",
        "studio_get_ai_work",
        "studio_get_teammate_activity",
    }
)

TOOL_PROFILES: Mapping[str, frozenset[str]] = {
    SESSION_PROFILE: SESSION_TOOL_PROFILE,
    ADMIN_PROFILE: frozenset(MCP_ACCESS),
}


def normalise_tool_profile(value: str | None) -> str:
    """Return a known profile name, defaulting when unset or unrecognised."""
    if value is None:
        return DEFAULT_TOOL_PROFILE
    normalised = value.strip().casefold()
    return normalised if normalised in TOOL_PROFILES else DEFAULT_TOOL_PROFILE


def resolve_tool_profile(headers: Mapping[str, str] | None) -> str:
    """The profile for one connection. HTTP connections (headers present) read
    the request header only — a server-wide env var must not leak into them;
    stdio connections fall back to `STUDIO_MCP_TOOL_PROFILE`."""
    if headers is None:
        return normalise_tool_profile(os.environ.get(TOOL_PROFILE_ENV))
    for name, value in headers.items():
        if name.casefold() == TOOL_PROFILE_HEADER:
            return normalise_tool_profile(value)
    return DEFAULT_TOOL_PROFILE


def tools_for_profile(profile: str) -> frozenset[str]:
    return TOOL_PROFILES.get(profile, TOOL_PROFILES[DEFAULT_TOOL_PROFILE])


def _request_headers(ctx: ServerRequestContext[Any, Any]) -> Mapping[str, str] | None:
    return getattr(ctx.request, "headers", None)


class ToolProfileMiddleware:
    """Filter `tools/list` and reject out-of-profile `tools/call` per connection.

    Registered on `MCPServer(middleware=...)`, so it runs for both stdio and
    HTTP transports (mcp.server.context.ServerMiddleware). `session` is the
    default; `admin` is opt-in per connection.
    """

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if ctx.method not in ("tools/list", "tools/call"):
            return await call_next(ctx)
        profile = resolve_tool_profile(_request_headers(ctx))
        allowed = tools_for_profile(profile)
        if ctx.method == "tools/list":
            result = await call_next(ctx)
            if isinstance(result, ListToolsResult):
                result.tools = [tool for tool in result.tools if tool.name in allowed]
            return result
        params = ctx.params if isinstance(ctx.params, Mapping) else {}
        name = params.get("name")
        if name not in allowed:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error_code": "tool_not_in_profile",
                                "message": (
                                    f"tool {name!r} is not part of the {profile!r} "
                                    "tool profile; connect with the admin profile to use it"
                                ),
                                "tool_profile": profile,
                            }
                        ),
                    )
                ],
                is_error=True,
            )
        return await call_next(ctx)
