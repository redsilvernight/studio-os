from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from studio_client.knowledge import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_READ_CHARS,
    GraphProvider,
    KnowledgeError,
    MemoryProvider,
)
from studio_client.knowledge.graph import DEFAULT_LIMIT as GRAPH_DEFAULT_LIMIT

GraphMode = Literal["query", "relevant_files", "dependencies", "related_symbols"]

_TOOL_ERROR = "error"
_INVALID_ARGUMENT = "invalid_argument"


def _failure(error_code: str, message: str) -> dict[str, Any]:
    return {"error_code": error_code, "message": message}


def _unexpected(exc: Exception) -> dict[str, Any]:
    return _failure(_TOOL_ERROR, f"{type(exc).__name__}: {exc}")


def make_memory_search(
    provider: MemoryProvider,
) -> Callable[[str, int], Awaitable[dict[str, Any]]]:
    """Thin MCP handler over `MemoryProvider.search` (TECH/07 UC-3, DEC-0047).

    Success keeps the provider's degraded shape (`reason` on a valid
    business response); only real failures become `{error_code, ...}`.
    """

    async def studio_memory_search(
        query: str, max_results: int = DEFAULT_MAX_RESULTS
    ) -> dict[str, Any]:
        try:
            result = provider.search(query, max_results=max_results)
        except KnowledgeError as exc:
            return _failure(exc.reason, exc.message)
        except ValueError as exc:
            return _failure(_INVALID_ARGUMENT, str(exc))
        except Exception as exc:
            return _unexpected(exc)
        payload: dict[str, Any] = {
            "matches": [
                {
                    "path": hit.path,
                    "title": hit.title,
                    "excerpt": hit.excerpt,
                    "truncated": hit.truncated,
                }
                for hit in result.matches
            ]
        }
        if result.reason is not None:
            payload["reason"] = result.reason
        return payload

    return studio_memory_search


def make_memory_read(
    provider: MemoryProvider,
) -> Callable[[str, int], Awaitable[dict[str, Any]]]:
    """Thin MCP handler over `MemoryProvider.read` (TECH/07 UC-3, DEC-0047)."""

    async def studio_memory_read(path: str, max_chars: int = DEFAULT_READ_CHARS) -> dict[str, Any]:
        try:
            result = provider.read(path, max_chars=max_chars)
        except KnowledgeError as exc:
            return _failure(exc.reason, exc.message)
        except ValueError as exc:
            return _failure(_INVALID_ARGUMENT, str(exc))
        except Exception as exc:
            return _unexpected(exc)
        return {
            "path": result.path,
            "title": result.title,
            "content": result.content,
            "truncated": result.truncated,
        }

    return studio_memory_read


def make_graph_query(
    provider: GraphProvider,
) -> Callable[[str, GraphMode, int], Awaitable[dict[str, Any]]]:
    """Thin MCP handler over the four `GraphProvider` reads behind one tool
    with a `mode` parameter (TECH/07 UC-3, DEC-0047). `stale` is always
    present; freshness comes from the provider, never invented here."""

    async def studio_graph_query(
        text: str, mode: GraphMode = "query", limit: int = GRAPH_DEFAULT_LIMIT
    ) -> dict[str, Any]:
        try:
            if mode == "query":
                result = provider.query(text, limit=limit)
                return {
                    "nodes": [
                        {
                            "id": node.id,
                            "label": node.label,
                            "source_file": node.source_file,
                            "source_location": node.source_location,
                        }
                        for node in result.nodes
                    ],
                    "stale": result.stale,
                    **({"stale_reason": result.stale_reason} if result.stale_reason else {}),
                }
            if mode == "relevant_files":
                files_result = provider.relevant_files(text, limit=limit)
                return {
                    "files": list(files_result.files),
                    "stale": files_result.stale,
                    **(
                        {"stale_reason": files_result.stale_reason}
                        if files_result.stale_reason
                        else {}
                    ),
                }
            if mode == "dependencies":
                deps_result = provider.dependencies(text, limit=limit)
                return {
                    "files": list(deps_result.files),
                    "stale": deps_result.stale,
                    **(
                        {"stale_reason": deps_result.stale_reason}
                        if deps_result.stale_reason
                        else {}
                    ),
                }
            if mode == "related_symbols":
                symbols_result = provider.related_symbols(text, limit=limit)
                return {
                    "nodes": [
                        {
                            "id": node.id,
                            "label": node.label,
                            "source_file": node.source_file,
                            "source_location": node.source_location,
                        }
                        for node in symbols_result.nodes
                    ],
                    "stale": symbols_result.stale,
                    **(
                        {"stale_reason": symbols_result.stale_reason}
                        if symbols_result.stale_reason
                        else {}
                    ),
                }
            return _failure(_INVALID_ARGUMENT, f"unknown mode: {mode!r}")
        except ValueError as exc:
            return _failure(_INVALID_ARGUMENT, str(exc))
        except Exception as exc:
            return _unexpected(exc)

    return studio_graph_query
