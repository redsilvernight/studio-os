from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, Tool
from studio_client.config import ClientConfig
from studio_client.knowledge import GraphifyGraphProvider
from studio_mcp.local_server import (
    GRAPH_QUERY_DESCRIPTION,
    MEMORY_READ_DESCRIPTION,
    MEMORY_SEARCH_DESCRIPTION,
    create_local_server,
    create_local_server_from_config,
    create_local_server_from_env,
)
from studio_mcp.local_tools import make_graph_query, make_memory_search


async def _call(server: MCPServer, name: str, arguments: dict[str, Any]) -> CallToolResult:
    """`MCPServer.call_tool` returns `CallToolResult | InputRequiredResult`; none
    of these tools ever prompt for more input, so every call site here expects
    the former — narrow it once instead of asserting it at each of the 25
    call sites below."""
    result = await server.call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    return result


# UC-3 / 8.3a conformance for the local knowledge MCP server (DEC-0047).
# Synthetic vaults/graphs on `tmp_path` only — never the developer's real
# vault. No database, no token, no VPS: these tests must pass with no
# Postgres, no env credentials and no network.

SCOPE = ("projects/demo/", "conventions/")

FORBIDDEN_FRAGMENTS = (
    "obsidian",
    "graphify",
    "claude",
    "qwen",
    "codex",
    "opencode",
    "TECH/",
    "DEC-",
    ".py",
    "vault_sync",
    "contract-guardian",
    "studio-tester",
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    _write(
        root / "projects/demo/alpha.md",
        "---\ntitle: Alpha Note\n---\n# Alpha\nKeyword searchable content here.\n",
    )
    _write(root / "projects/demo/plain.md", "# Plain Title\nJust some body text.\n")
    _write(root / "projects/demo/broken.md", "---\ntitle: [unclosed\n---\nBody.\n")
    _write(root / "conventions/style.md", "# Style\nShared convention text.\n")
    _write(root / "private/secret.md", "# Secret\nPrivate content here.\n")
    _write(root / "projects/demo/big.md", "# Big\n" + ("lorem ipsum dolor " * 2000))
    for i in range(25):
        _write(root / f"projects/demo/bulk-{i:02d}.md", f"# Bulk {i}\nBulk filler {i}.\n")
    return root


@pytest.fixture
def graph_dir(tmp_path: Path) -> Path:
    out = tmp_path / "graph-out"
    out.mkdir()
    (out / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "label": "alpha_func",
                        "source_file": "a.py",
                        "source_location": "a.py:10",
                    },
                    {
                        "id": "n2",
                        "label": "beta_func",
                        "source_file": "b.py",
                        "source_location": "b.py:3",
                    },
                ],
                "links": [{"source": "n1", "target": "n2"}],
            }
        ),
        encoding="utf-8",
    )
    (out / "manifest.json").write_text(
        json.dumps({"a.py": {"mtime": 0}, "b.py": {"mtime": 0}}), encoding="utf-8"
    )
    return out


# Discovery


async def _names(vault_path: Path | None, graph_path: Path | None) -> list[str]:
    server = create_local_server(
        vault_path=vault_path,
        scope_allow=SCOPE if vault_path else (),
        graph_dir=graph_path,
    )
    return sorted(tool.name for tool in await server.list_tools())


async def _tools(vault_path: Path | None, graph_path: Path | None) -> list[Tool]:
    server = create_local_server(
        vault_path=vault_path,
        scope_allow=SCOPE if vault_path else (),
        graph_dir=graph_path,
    )
    return await server.list_tools()


async def test_no_config_registers_nothing() -> None:
    assert await _names(None, None) == []


async def test_vault_only_registers_memory_tools(vault: Path, graph_dir: Path) -> None:
    assert await _names(vault, None) == ["studio_memory_read", "studio_memory_search"]


async def test_graph_only_registers_graph_tool(vault: Path, graph_dir: Path) -> None:
    assert await _names(None, graph_dir) == ["studio_graph_query"]


async def test_vault_and_graph_register_all_three(vault: Path, graph_dir: Path) -> None:
    assert await _names(vault, graph_dir) == [
        "studio_graph_query",
        "studio_memory_read",
        "studio_memory_search",
    ]


async def test_configured_but_missing_backend_stays_announced(tmp_path: Path) -> None:
    # Configured != reachable: the tool stays in tools/list, the provider's
    # degraded shape answers at call time.
    server = create_local_server(vault_path=tmp_path / "no-such-vault", scope_allow=SCOPE)
    assert sorted(tool.name for tool in await server.list_tools()) == [
        "studio_memory_read",
        "studio_memory_search",
    ]
    result = await _call(server, "studio_memory_search", {"query": "x"})
    assert result.structured_content == {"matches": [], "reason": "vault_missing"}


async def test_from_config_and_from_env(vault: Path, tmp_path: Path) -> None:
    config = ClientConfig(
        api_base_url="http://localhost:1",
        knowledge_vault_path=vault,
        knowledge_scope_allow=SCOPE,
    )
    server = create_local_server_from_config(config)
    assert sorted(tool.name for tool in await server.list_tools()) == [
        "studio_memory_read",
        "studio_memory_search",
    ]


async def test_from_env_parses_scope_and_ignores_bad_json(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_KNOWLEDGE_VAULT_PATH", str(vault))
    monkeypatch.setenv("STUDIO_CLIENT_KNOWLEDGE_SCOPE_ALLOW", json.dumps(list(SCOPE)))
    server = create_local_server_from_env()
    assert "studio_memory_search" in [t.name for t in await server.list_tools()]
    monkeypatch.setenv("STUDIO_CLIENT_KNOWLEDGE_SCOPE_ALLOW", "not-json{{{")
    server = create_local_server_from_env()
    assert "studio_memory_search" in [t.name for t in await server.list_tools()]


# Metadata


async def test_tools_are_read_only_with_generic_descriptions(vault: Path, graph_dir: Path) -> None:
    by_name = {tool.name: tool for tool in await _tools(vault, graph_dir)}
    assert set(by_name) == {
        "studio_memory_search",
        "studio_memory_read",
        "studio_graph_query",
    }
    for tool in by_name.values():
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        assert tool.description and len(tool.description) >= 40
        lowered = tool.description.lower()
        for fragment in FORBIDDEN_FRAGMENTS:
            assert fragment.lower() not in lowered, f"{tool.name} leaks {fragment}"


async def test_input_schemas_match_contract(vault: Path, graph_dir: Path) -> None:
    by_name = {tool.name: tool for tool in await _tools(vault, graph_dir)}
    search_schema = by_name["studio_memory_search"].input_schema
    assert set(search_schema["required"]) == {"query"}
    assert search_schema["properties"]["max_results"].get("default", 20) == 20
    read_schema = by_name["studio_memory_read"].input_schema
    assert set(read_schema["required"]) == {"path"}
    assert read_schema["properties"]["max_chars"].get("default", 4000) == 4000
    graph_schema = by_name["studio_graph_query"].input_schema
    assert set(graph_schema["required"]) == {"text"}
    assert graph_schema["properties"]["mode"].get("default", "query") == "query"
    assert set(graph_schema["properties"]["mode"]["enum"]) == {
        "query",
        "relevant_files",
        "dependencies",
        "related_symbols",
    }
    assert graph_schema["properties"]["limit"].get("default", 20) == 20


def test_description_constants_are_generic() -> None:
    for description in (
        MEMORY_SEARCH_DESCRIPTION,
        MEMORY_READ_DESCRIPTION,
        GRAPH_QUERY_DESCRIPTION,
    ):
        lowered = description.lower()
        for fragment in FORBIDDEN_FRAGMENTS:
            assert fragment.lower() not in lowered


# Memory


async def test_search_nominal_and_case_insensitive(vault: Path) -> None:
    server = create_local_server(vault_path=vault, scope_allow=SCOPE)
    result = await _call(server, "studio_memory_search", {"query": "searchable"})
    assert result.structured_content is not None
    assert result.structured_content["matches"] == [
        {
            "path": "projects/demo/alpha.md",
            "title": "Alpha Note",
            "excerpt": "# Alpha Keyword searchable content here.",
            "truncated": False,
        }
    ]
    upper = await _call(server, "studio_memory_search", {"query": "SEARCHABLE"})
    assert upper.structured_content == result.structured_content


async def test_search_bounded_and_scoped(vault: Path) -> None:
    server = create_local_server(vault_path=vault, scope_allow=SCOPE)
    result = await _call(server, "studio_memory_search", {"query": "bulk", "max_results": 5})
    assert result.structured_content is not None
    assert len(result.structured_content["matches"]) == 5
    private = await _call(server, "studio_memory_search", {"query": "secret"})
    assert private.structured_content == {"matches": []}


async def test_search_invalid_limit_is_machine_readable(vault: Path) -> None:
    server = create_local_server(vault_path=vault, scope_allow=SCOPE)
    result = await _call(server, "studio_memory_search", {"query": "x", "max_results": 0})
    assert result.structured_content is not None
    assert result.structured_content["error_code"] == "invalid_argument"


async def test_read_nominal_truncation_and_frontmatter(vault: Path) -> None:
    server = create_local_server(vault_path=vault, scope_allow=SCOPE)
    result = await _call(server, "studio_memory_read", {"path": "projects/demo/alpha.md"})
    assert result.structured_content is not None
    assert result.structured_content["title"] == "Alpha Note"
    assert result.structured_content["truncated"] is False
    plain = await _call(server, "studio_memory_read", {"path": "projects/demo/plain.md"})
    assert plain.structured_content is not None
    assert plain.structured_content["title"] == "Plain Title"
    big = await _call(server, 
        "studio_memory_read", {"path": "projects/demo/big.md", "max_chars": 100}
    )
    assert big.structured_content is not None
    assert big.structured_content["truncated"] is True
    assert len(big.structured_content["content"]) <= 102


async def test_read_errors_are_machine_readable(vault: Path) -> None:
    server = create_local_server(vault_path=vault, scope_allow=SCOPE)
    for path, code in (
        ("projects/demo/missing.md", "not_found"),
        ("private/secret.md", "out_of_scope"),
        ("../outside.md", "out_of_scope"),
        ("projects/demo/broken.md", "invalid_frontmatter"),
    ):
        result = await _call(server, "studio_memory_read", {"path": path})
        assert result.structured_content is not None
        assert result.structured_content["error_code"] == code, path
    absolute = str(vault / "projects/demo/alpha.md")
    result = await _call(server, "studio_memory_read", {"path": absolute})
    assert result.structured_content is not None
    assert result.structured_content["error_code"] == "out_of_scope"


async def test_read_does_not_follow_scope_escaping_symlink(vault: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    link = vault / "projects/demo/evil.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not permitted on this platform")
    server = create_local_server(vault_path=vault, scope_allow=SCOPE)
    result = await _call(server, "studio_memory_read", {"path": "projects/demo/evil.md"})
    assert result.structured_content is not None
    assert result.structured_content["error_code"] == "out_of_scope"


async def test_no_stack_trace_leaks_on_unexpected_failure() -> None:
    class _Boom:
        def search(self, query: str, *, max_results: int = 20) -> object:
            raise RuntimeError("synthetic boom")

    handler = make_memory_search(_Boom())  # type: ignore[arg-type]
    result = await handler("x", 20)
    assert result["error_code"] == "error"
    assert "Traceback" not in result["message"]


# Graph


async def test_graph_modes_and_freshness(graph_dir: Path) -> None:
    server = create_local_server(graph_dir=graph_dir)
    query = await _call(server, "studio_graph_query", {"text": "alpha"})
    assert query.structured_content is not None
    assert query.structured_content["nodes"][0]["label"] == "alpha_func"
    assert query.structured_content["stale"] is False
    assert "stale_reason" not in query.structured_content
    files = await _call(server, 
        "studio_graph_query", {"text": "alpha", "mode": "relevant_files"}
    )
    assert files.structured_content is not None
    assert files.structured_content["files"] == ["a.py"]
    deps = await _call(server, "studio_graph_query", {"text": "a.py", "mode": "dependencies"})
    assert deps.structured_content is not None
    assert deps.structured_content["files"] == ["b.py"]
    assert deps.structured_content["stale"] is False
    related = await _call(server, 
        "studio_graph_query", {"text": "b.py", "mode": "related_symbols"}
    )
    assert related.structured_content is not None
    assert [node["label"] for node in related.structured_content["nodes"]] == ["beta_func"]


async def test_graph_bounded(graph_dir: Path) -> None:
    server = create_local_server(graph_dir=graph_dir)
    result = await _call(server, "studio_graph_query", {"text": "func", "limit": 1})
    assert result.structured_content is not None
    assert len(result.structured_content["nodes"]) == 1


async def test_graph_invalid_mode_rejected(graph_dir: Path) -> None:
    handler = make_graph_query(GraphifyGraphProvider(graph_dir))
    assert (await handler("x", "nope", 20))["error_code"] == "invalid_argument"  # type: ignore[arg-type]


async def test_graph_degraded_states(tmp_path: Path, graph_dir: Path) -> None:
    server = create_local_server(graph_dir=tmp_path / "no-graph")
    missing = await _call(server, "studio_graph_query", {"text": "x"})
    assert missing.structured_content is not None
    assert missing.structured_content["stale"] is True
    assert missing.structured_content["stale_reason"] == "graph_missing"
    no_manifest = tmp_path / "no-manifest"
    no_manifest.mkdir()
    (no_manifest / "graph.json").write_text(
        json.dumps({"nodes": [], "links": []}), encoding="utf-8"
    )
    server = create_local_server(graph_dir=no_manifest)
    result = await _call(server, "studio_graph_query", {"text": "x"})
    assert result.structured_content is not None
    assert result.structured_content["stale_reason"] == "manifest_missing"
    bad = tmp_path / "bad-graph"
    bad.mkdir()
    (bad / "graph.json").write_text("{not json", encoding="utf-8")
    server = create_local_server(graph_dir=bad)
    result = await _call(server, "studio_graph_query", {"text": "x"})
    assert result.structured_content is not None
    assert result.structured_content["stale_reason"] == "graph_invalid"


async def test_graph_not_covered_and_source_states(graph_dir: Path, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    a_file = src / "a.py"
    a_file.write_text("x = 1\n", encoding="utf-8")
    (src / "b.py").write_text("y = 2\n", encoding="utf-8")
    manifest = {"a.py": {"mtime": a_file.stat().st_mtime}, "b.py": {"mtime": 0}}
    (graph_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    server = create_local_server(graph_dir=graph_dir, source_root=src)
    fresh = await _call(server, "studio_graph_query", {"text": "a.py", "mode": "dependencies"})
    assert fresh.structured_content is not None
    assert fresh.structured_content["stale"] is False
    changed = await _call(server, "studio_graph_query", {"text": "b.py", "mode": "dependencies"})
    assert changed.structured_content is not None
    assert changed.structured_content["stale_reason"] == "changed_since_indexed"
    (src / "gone.py").write_text("z = 3\n", encoding="utf-8")
    manifest["gone.py"] = {"mtime": 0}
    (graph_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (src / "gone.py").unlink()
    # New server: the provider snapshots the manifest on first load.
    server = create_local_server(graph_dir=graph_dir, source_root=src)
    gone = await _call(server, "studio_graph_query", {"text": "gone.py", "mode": "dependencies"})
    assert gone.structured_content is not None
    assert gone.structured_content["stale_reason"] == "source_missing"
    server = create_local_server(graph_dir=graph_dir)
    uncovered = await _call(server, 
        "studio_graph_query", {"text": "zzz.py", "mode": "dependencies"}
    )
    assert uncovered.structured_content is not None
    assert uncovered.structured_content["stale_reason"] == "not_covered"


# Isolation


def test_local_server_imports_without_server_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The local path must not need Postgres, tokens or the VPS: fresh
    interpreter, scrubbed env; neither the server stack (`studio_api`,
    `sqlalchemy`, `fastapi`) nor the credential/network client machinery
    (`studio_client.api_client`, `studio_client.tokens`,
    `studio_client.transfers`, `keyring`) may be imported."""
    for var in (
        "DATABASE_URL",
        "STUDIO_DATABASE_URL",
        "STUDIO_MCP_MACHINE_TOKEN",
        "STUDIO_API_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    script = (
        "import sys;"
        "from studio_mcp.local_server import create_local_server;"
        "from studio_mcp.local_tools import make_memory_search;"
        "s = create_local_server();"
        "forbidden = ('studio_api', 'sqlalchemy', 'fastapi', 'keyring',"
        " 'studio_client.api_client', 'studio_client.tokens',"
        " 'studio_client.transfers');"
        "bad = [m for m in sys.modules if any("
        "m == p or m.startswith(p + '.') for p in forbidden)];"
        "assert not bad, bad;"
        "print('local-ok')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "local-ok" in completed.stdout


async def test_local_server_created_with_scrubbed_env(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in (
        "DATABASE_URL",
        "STUDIO_DATABASE_URL",
        "STUDIO_MCP_MACHINE_TOKEN",
        "STUDIO_API_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    server = create_local_server(vault_path=vault, scope_allow=SCOPE)
    assert len(await server.list_tools()) == 2


async def test_call_tool_without_context(vault: Path) -> None:
    """Unknown harnesses connect without any Studi'OS identity: tool calls
    carry no auth context at all."""
    server = create_local_server(vault_path=vault, scope_allow=SCOPE)
    result = await _call(server, "studio_memory_search", {"query": "alpha"})
    assert result.structured_content is not None
    assert result.structured_content["matches"]
