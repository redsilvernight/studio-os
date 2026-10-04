from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp.server import ServerRequestContext
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from studio_mcp.access_registry import MCP_ACCESS
from studio_mcp.server import mcp
from studio_mcp.tool_profiles import (
    ADMIN_PROFILE,
    DEFAULT_TOOL_PROFILE,
    SESSION_PROFILE,
    SESSION_TOOL_PROFILE,
    TOOL_PROFILE_ENV,
    TOOL_PROFILES,
    ToolProfileMiddleware,
    normalise_tool_profile,
    resolve_tool_profile,
    tools_for_profile,
)

_HEADER = "x-studio-tool-profile"


def _context(
    method: str, *, headers: dict[str, str] | None, params: dict[str, Any] | None = None
) -> ServerRequestContext[Any, Any]:
    request = None if headers is None else SimpleNamespace(headers=headers)
    return ServerRequestContext(
        session=cast(Any, None),
        lifespan_context={},
        protocol_version="2026-07-28",
        method=method,
        params=params,
        request=request,
    )


def _all_tools() -> list[Tool]:
    return [Tool(name=name, input_schema={"type": "object"}) for name in MCP_ACCESS]


async def _list_all(ctx: ServerRequestContext[Any, Any]) -> ListToolsResult:
    return ListToolsResult(tools=_all_tools())


def test_session_profile_is_a_subset_of_the_registered_surface() -> None:
    assert SESSION_TOOL_PROFILE <= set(MCP_ACCESS)
    assert len(SESSION_TOOL_PROFILE) < len(MCP_ACCESS)


def test_admin_profile_is_every_registered_tool() -> None:
    assert set(TOOL_PROFILES[ADMIN_PROFILE]) == set(MCP_ACCESS)


def test_default_profile_is_session() -> None:
    assert DEFAULT_TOOL_PROFILE == SESSION_PROFILE
    assert normalise_tool_profile(None) == SESSION_PROFILE
    assert normalise_tool_profile("nonsense") == SESSION_PROFILE


def test_resolve_reads_profile_header_case_insensitively() -> None:
    assert resolve_tool_profile({_HEADER: "admin"}) == ADMIN_PROFILE
    assert resolve_tool_profile({"X-Studio-Tool-Profile": "  Admin "}) == ADMIN_PROFILE
    assert resolve_tool_profile({_HEADER: "session"}) == SESSION_PROFILE
    assert resolve_tool_profile({}) == SESSION_PROFILE


def test_stdio_resolution_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOOL_PROFILE_ENV, "admin")
    assert resolve_tool_profile(None) == ADMIN_PROFILE
    monkeypatch.setenv(TOOL_PROFILE_ENV, "session")
    assert resolve_tool_profile(None) == SESSION_PROFILE


def test_http_connection_ignores_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOOL_PROFILE_ENV, "admin")
    assert resolve_tool_profile({}) == SESSION_PROFILE
    assert resolve_tool_profile({_HEADER: "admin"}) == ADMIN_PROFILE


def test_tools_for_profile_unknown_falls_back() -> None:
    assert tools_for_profile("unknown") == SESSION_TOOL_PROFILE
    assert tools_for_profile(ADMIN_PROFILE) == frozenset(MCP_ACCESS)


@pytest.mark.asyncio
async def test_tools_list_is_filtered_to_the_session_profile() -> None:
    middleware = ToolProfileMiddleware()
    result = await middleware(_context("tools/list", headers={}), _list_all)
    assert isinstance(result, ListToolsResult)
    assert {tool.name for tool in result.tools} == set(SESSION_TOOL_PROFILE)


@pytest.mark.asyncio
async def test_tools_list_serves_everything_for_the_admin_profile() -> None:
    middleware = ToolProfileMiddleware()
    result = await middleware(_context("tools/list", headers={_HEADER: "admin"}), _list_all)
    assert isinstance(result, ListToolsResult)
    assert {tool.name for tool in result.tools} == set(MCP_ACCESS)


@pytest.mark.asyncio
async def test_call_outside_the_profile_is_rejected_without_dispatch() -> None:
    middleware = ToolProfileMiddleware()
    called = False

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> str:
        nonlocal called
        called = True
        return "dispatched"

    ctx = _context(
        "tools/call",
        headers={},
        params={"name": "studio_apply_roadmap_hydration", "arguments": {}},
    )
    result = await middleware(ctx, call_next)
    assert isinstance(result, CallToolResult)
    assert result.is_error is True
    assert not called
    content = result.content[0]
    assert isinstance(content, TextContent)
    assert "tool_not_in_profile" in content.text


@pytest.mark.asyncio
async def test_call_inside_the_profile_is_dispatched() -> None:
    middleware = ToolProfileMiddleware()
    called = False

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> str:
        nonlocal called
        called = True
        return "dispatched"

    ctx = _context(
        "tools/call",
        headers={},
        params={"name": "studio_prepare_context", "arguments": {}},
    )
    assert await middleware(ctx, call_next) == "dispatched"
    assert called


@pytest.mark.asyncio
async def test_admin_connection_may_call_an_admin_tool() -> None:
    middleware = ToolProfileMiddleware()
    called = False

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> str:
        nonlocal called
        called = True
        return "dispatched"

    ctx = _context(
        "tools/call",
        headers={_HEADER: "admin"},
        params={"name": "studio_apply_roadmap_hydration", "arguments": {}},
    )
    assert await middleware(ctx, call_next) == "dispatched"
    assert called


def test_server_registers_the_profile_middleware() -> None:
    lowlevel = cast(Any, mcp)._lowlevel_server
    assert any(isinstance(middleware, ToolProfileMiddleware) for middleware in lowlevel.middleware)
