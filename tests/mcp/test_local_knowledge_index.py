from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, Tool
from studio_contracts.local.common import ComponentState
from studio_mcp.local_server import (
    create_local_server_from_knowledge,
    create_local_server_from_workspace,
)

from tests.knowledge.factories import WORKSPACE_ID, make_config, make_vault

SCOPE = ("projects/demo/",)

FORBIDDEN_FRAGMENTS = ("obsidian", "graphify", "keyring", "token")


async def _call(server: MCPServer, name: str, arguments: dict[str, Any]) -> CallToolResult:
    result = await server.call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    return result


def _server(vault: Path, cache: Path, *, scope: tuple[str, ...] = SCOPE) -> MCPServer:
    return create_local_server_from_knowledge(
        workspace_id=WORKSPACE_ID,
        vault_root=vault,
        cache_dir=cache,
        scope_allow=scope,
        index_now=True,
    )


async def test_index_backed_memory_tools_are_registered(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    server = _server(vault, tmp_path / "cache")
    tools: list[Tool] = await server.list_tools()
    assert sorted(tool.name for tool in tools) == [
        "studio_memory_read",
        "studio_memory_search",
    ]
    assert all(tool.annotations is not None and tool.annotations.read_only_hint for tool in tools)
    for tool in tools:
        for fragment in FORBIDDEN_FRAGMENTS:
            assert fragment not in (tool.description or "").lower()


async def test_search_reads_the_derived_index(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    server = _server(vault, tmp_path / "cache")
    result = await _call(server, "studio_memory_search", {"query": "combat rules"})
    payload = result.structured_content
    assert payload is not None
    assert payload["matches"][0]["path"] == "projects/demo/combat.md"
    assert "reason" not in payload


async def test_the_scope_stays_closed_by_default(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    server = _server(vault, tmp_path / "cache", scope=())
    result = await _call(server, "studio_memory_search", {"query": "combat rules"})
    assert result.structured_content == {"matches": []}


async def test_read_refuses_a_path_outside_the_scope(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    server = _server(vault, tmp_path / "cache")
    result = await _call(server, "studio_memory_read", {"path": "conventions/style.md"})
    payload = result.structured_content
    assert payload is not None
    assert payload["error_code"] == "out_of_scope"


async def test_read_returns_the_canonical_markdown(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    server = _server(vault, tmp_path / "cache")
    result = await _call(server, "studio_memory_read", {"path": "projects/demo/intro.md"})
    payload = result.structured_content
    assert payload is not None
    assert payload["title"] == "Introduction"
    assert "Introduction" in str(payload["content"])


async def test_a_workspace_with_knowledge_off_registers_no_memory_tool(tmp_path: Path) -> None:
    make_vault(tmp_path)
    config = make_config(tmp_path, knowledge=False)
    server = create_local_server_from_workspace(config, cache_dir=tmp_path / "cache")
    assert await server.list_tools() == []


async def test_a_workspace_with_knowledge_on_builds_the_same_tools(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    config = make_config(tmp_path)
    server = create_local_server_from_workspace(
        config, cache_dir=tmp_path / "cache", index_now=True
    )
    assert sorted(tool.name for tool in await server.list_tools()) == [
        "studio_memory_read",
        "studio_memory_search",
    ]
    assert vault.is_dir()
    assert ComponentState.READY.value == "ready"
