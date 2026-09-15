from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from studio_client.config import ClientConfig
from studio_client.knowledge import GraphifyGraphProvider, ScopePolicy, VaultMemoryProvider

from studio_mcp.local_tools import make_graph_query, make_memory_read, make_memory_search

_READ_ONLY = ToolAnnotations(read_only_hint=True)

MEMORY_SEARCH_DESCRIPTION = (
    "Search the local shared knowledge memory (Markdown notes) by keyword — "
    "read-only. Returns bounded matches (path, title, excerpt) within the "
    "operator-configured scope; private notes are never indexed or listed. "
    "A temporarily unavailable store returns an empty match list with a "
    "machine-readable reason instead of failing."
)

MEMORY_READ_DESCRIPTION = (
    "Read one shared knowledge note by its store-relative path — read-only, "
    "length-bounded, truncated with a flag when longer than the limit. Paths "
    "outside the configured scope (absolute paths, parent-directory escapes, "
    "links leaving the scope) fail with out_of_scope; unknown notes fail "
    "with not_found."
)

GRAPH_QUERY_DESCRIPTION = (
    "Query the local knowledge graph of indexed files and symbols — "
    "read-only. Modes: query (symbol search), relevant_files, dependencies, "
    "related_symbols. Every response carries a freshness flag (stale plus "
    "stale_reason when relevant); a missing or uncovered index is reported "
    "stale, never served as fresh."
)


def create_local_server(
    *,
    vault_path: Path | None = None,
    scope_allow: tuple[str, ...] = (),
    graph_dir: Path | None = None,
    source_root: Path | None = None,
) -> MCPServer:
    """Build the UC-3 local MCP server (DEC-0047): tools are registered
    exactly when their backend is *configured*, never on physical
    reachability — a configured-but-unavailable backend stays announced
    and answers with the provider's machine-readable degraded shape.
    This process touches no database, no token, no remote API: the stdio
    child process launched by the MCP client is the trust boundary."""
    server = MCPServer(name="studio-os-local")
    if vault_path is not None:
        memory = VaultMemoryProvider(vault_path, ScopePolicy(allowed_prefixes=scope_allow))
        server.add_tool(
            make_memory_search(memory),
            name="studio_memory_search",
            description=MEMORY_SEARCH_DESCRIPTION,
            annotations=_READ_ONLY,
        )
        server.add_tool(
            make_memory_read(memory),
            name="studio_memory_read",
            description=MEMORY_READ_DESCRIPTION,
            annotations=_READ_ONLY,
        )
    if graph_dir is not None:
        graph = GraphifyGraphProvider(graph_dir, source_root=source_root)
        server.add_tool(
            make_graph_query(graph),
            name="studio_graph_query",
            description=GRAPH_QUERY_DESCRIPTION,
            annotations=_READ_ONLY,
        )
    return server


def create_local_server_from_config(config: ClientConfig) -> MCPServer:
    """Convenience over `create_local_server` reusing the Bloc B knowledge
    settings (`STUDIO_CLIENT_KNOWLEDGE_*`, DEC-0042) — still no API use."""
    return create_local_server(
        vault_path=config.knowledge_vault_path,
        scope_allow=config.knowledge_scope_allow,
        graph_dir=config.knowledge_graph_dir,
        source_root=config.knowledge_source_root,
    )


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw) if raw else None


def _env_scope(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return ()
    return tuple(parsed)


def create_local_server_from_env() -> MCPServer:
    """Stdio entrypoint configuration: `STUDIO_CLIENT_KNOWLEDGE_VAULT_PATH`,
    `STUDIO_CLIENT_KNOWLEDGE_SCOPE_ALLOW` (JSON list),
    `STUDIO_CLIENT_KNOWLEDGE_GRAPH_DIR`, `STUDIO_CLIENT_KNOWLEDGE_SOURCE_ROOT`.
    """
    return create_local_server(
        vault_path=_env_path("STUDIO_CLIENT_KNOWLEDGE_VAULT_PATH"),
        scope_allow=_env_scope("STUDIO_CLIENT_KNOWLEDGE_SCOPE_ALLOW"),
        graph_dir=_env_path("STUDIO_CLIENT_KNOWLEDGE_GRAPH_DIR"),
        source_root=_env_path("STUDIO_CLIENT_KNOWLEDGE_SOURCE_ROOT"),
    )


if __name__ == "__main__":
    create_local_server_from_env().run(transport="stdio")
