from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from studio_client.knowledge.errors import KnowledgeError

DEFAULT_LIMIT = 20

GRAPH_FILENAME = "graph.json"
MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class GraphNode:
    id: str
    label: str
    source_file: str = ""
    source_location: str = ""


@dataclass(frozen=True)
class GraphQueryResult:
    nodes: list[GraphNode] = field(default_factory=list)
    stale: bool = False
    stale_reason: str | None = None


@dataclass(frozen=True)
class RelevantFilesResult:
    files: list[str] = field(default_factory=list)
    stale: bool = False
    stale_reason: str | None = None


@dataclass(frozen=True)
class DependenciesResult:
    files: list[str] = field(default_factory=list)
    stale: bool = False
    stale_reason: str | None = None


@dataclass(frozen=True)
class RelatedSymbolsResult:
    nodes: list[GraphNode] = field(default_factory=list)
    stale: bool = False
    stale_reason: str | None = None


class GraphProvider(Protocol):
    """`TECH/09` graph surface, read-only for 8.2 (DEC-0042)."""

    def query(self, text: str, *, limit: int = DEFAULT_LIMIT) -> GraphQueryResult: ...
    def relevant_files(
        self, topic_or_path: str, *, limit: int = DEFAULT_LIMIT
    ) -> RelevantFilesResult: ...
    def dependencies(self, file_path: str, *, limit: int = DEFAULT_LIMIT) -> DependenciesResult: ...
    def related_symbols(
        self, symbol_or_file: str, *, limit: int = DEFAULT_LIMIT
    ) -> RelatedSymbolsResult: ...
    def refresh_graph(self) -> None: ...


@dataclass
class _LoadedGraph:
    nodes: list[dict[str, Any]]
    links: list[dict[str, Any]]
    manifest: dict[str, Any]


class GraphifyGraphProvider:
    """Read-only Graphify adapter over the centralized `graphify-out` dir.

    Reads `graph.json` (node-link format) and `manifest.json` (coverage
    ledger) directly — no PowerShell, no subprocess, no network. Freshness
    comes from manifest *coverage*, never from bare mtimes: a requested
    file absent from the manifest is reported `stale`, never served as
    fresh. When `source_root` is set, a drift between the on-disk mtime and
    the manifest-recorded mtime is also reported stale. Missing or corrupt
    artefacts degrade to stale empty results with a machine-readable
    reason, never an untyped exception.
    """

    GRAPH_MISSING = "graph_missing"
    MANIFEST_MISSING = "manifest_missing"
    GRAPH_INVALID = "graph_invalid"
    NOT_COVERED = "not_covered"
    CHANGED_SINCE_INDEXED = "changed_since_indexed"
    SOURCE_MISSING = "source_missing"

    def __init__(self, graph_dir: Path | None, *, source_root: Path | None = None) -> None:
        self._graph_dir = graph_dir
        self._source_root = source_root
        self._cache: _LoadedGraph | None = None
        self._load_error: str | None = None

    def _load(self) -> _LoadedGraph | None:
        if self._cache is not None or self._load_error is not None:
            return self._cache
        if self._graph_dir is None or not self._graph_dir.is_dir():
            self._load_error = self.GRAPH_MISSING
            return None
        graph_path = self._graph_dir / GRAPH_FILENAME
        if not graph_path.is_file():
            self._load_error = self.GRAPH_MISSING
            return None
        try:
            raw = json.loads(graph_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._load_error = self.GRAPH_INVALID
            return None
        nodes = raw.get("nodes")
        links = raw.get("links", raw.get("edges", []))
        if not isinstance(nodes, list) or not isinstance(links, list):
            self._load_error = self.GRAPH_INVALID
            return None
        manifest: dict[str, Any] = {}
        manifest_path = self._graph_dir / MANIFEST_FILENAME
        if manifest_path.is_file():
            try:
                parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict):
                manifest = parsed
        self._cache = _LoadedGraph(nodes=nodes, links=links, manifest=manifest)
        return self._cache

    def _stale_state(self) -> tuple[bool, str | None]:
        if self._load() is None:
            reason = self._load_error or self.GRAPH_MISSING
            return True, reason
        if not self._manifest_present():
            return True, self.MANIFEST_MISSING
        return False, None

    def _manifest_present(self) -> bool:
        loaded = self._load()
        return loaded is not None and bool(loaded.manifest)

    def _freshness(self, file_path: str) -> tuple[bool, str | None]:
        """Coverage first, mtime-against-manifest second (DEC-0042)."""
        loaded = self._load()
        if loaded is None:
            return True, self._load_error or self.GRAPH_MISSING
        if not loaded.manifest:
            return True, self.MANIFEST_MISSING
        entry = loaded.manifest.get(file_path)
        if entry is None:
            return True, self.NOT_COVERED
        if self._source_root is not None:
            disk = self._source_root / file_path
            if not disk.exists():
                return True, self.SOURCE_MISSING
            recorded = entry.get("mtime") if isinstance(entry, dict) else None
            if isinstance(recorded, int | float):
                try:
                    if disk.stat().st_mtime != float(recorded):
                        return True, self.CHANGED_SINCE_INDEXED
                except OSError:
                    return True, self.SOURCE_MISSING
        return False, None

    @staticmethod
    def _node_of(raw: dict[str, Any]) -> GraphNode:
        label = raw.get("label")
        node_id = raw.get("id")
        source_file = raw.get("source_file") or ""
        location = raw.get("source_location") or ""
        return GraphNode(
            id=str(node_id) if node_id is not None else "",
            label=str(label) if label is not None else "",
            source_file=str(source_file),
            source_location=str(location),
        )

    def query(self, text: str, *, limit: int = DEFAULT_LIMIT) -> GraphQueryResult:
        """Substring match over node labels, bounded and compact."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        stale, reason = self._stale_state()
        loaded = self._load()
        if loaded is None:
            return GraphQueryResult(nodes=[], stale=True, stale_reason=reason)
        needle = text.strip().lower()
        if not needle:
            return GraphQueryResult(nodes=[], stale=stale, stale_reason=reason)
        matched = [
            self._node_of(raw)
            for raw in loaded.nodes
            if isinstance(raw, dict) and needle in str(raw.get("label") or "").lower()
        ]
        matched.sort(key=lambda node: (node.label.lower(), node.id))
        return GraphQueryResult(nodes=matched[:limit], stale=stale, stale_reason=reason)

    def relevant_files(
        self, topic_or_path: str, *, limit: int = DEFAULT_LIMIT
    ) -> RelevantFilesResult:
        """Distinct source files behind a topic match or an explicit path."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        loaded = self._load()
        topic = topic_or_path.strip().lstrip("./")
        if loaded is None:
            return RelevantFilesResult(files=[], stale=True, stale_reason=self._load_error)
        needle = topic.lower()
        files = {
            str(raw.get("source_file"))
            for raw in loaded.nodes
            if isinstance(raw, dict)
            and str(raw.get("source_file") or "")
            and (
                needle in str(raw.get("label") or "").lower()
                or needle in str(raw.get("source_file") or "").lower()
            )
        }
        ordered = sorted(files)[:limit]
        if self._looks_like_path(topic):
            stale, reason = self._freshness(topic)
            return RelevantFilesResult(files=ordered, stale=stale, stale_reason=reason)
        stale, reason = self._stale_state()
        return RelevantFilesResult(files=ordered, stale=stale, stale_reason=reason)

    def dependencies(self, file_path: str, *, limit: int = DEFAULT_LIMIT) -> DependenciesResult:
        """Distinct files linked to symbols of the requested file (1 hop)."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        stale, reason = self._freshness(file_path)
        loaded = self._load()
        if loaded is None:
            return DependenciesResult(files=[], stale=True, stale_reason=reason)
        ids_in_file = {
            str(raw.get("id"))
            for raw in loaded.nodes
            if isinstance(raw, dict) and str(raw.get("source_file") or "") == file_path
        }
        by_id = {
            str(raw.get("id")): raw
            for raw in loaded.nodes
            if isinstance(raw, dict) and raw.get("id") is not None
        }
        neighbours: set[str] = set()
        for raw in loaded.links:
            if not isinstance(raw, dict):
                continue
            source, target = str(raw.get("source")), str(raw.get("target"))
            other: str | None = None
            if source in ids_in_file:
                other = target
            elif target in ids_in_file:
                other = source
            if other is not None and other in by_id:
                other_file = str(by_id[other].get("source_file") or "")
                if other_file and other_file != file_path:
                    neighbours.add(other_file)
        return DependenciesResult(
            files=sorted(neighbours)[:limit], stale=stale, stale_reason=reason
        )

    def related_symbols(
        self, symbol_or_file: str, *, limit: int = DEFAULT_LIMIT
    ) -> RelatedSymbolsResult:
        """Symbols in a file, or label matches plus their 1-hop neighbours."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        loaded = self._load()
        if loaded is None:
            return RelatedSymbolsResult(nodes=[], stale=True, stale_reason=self._load_error)
        needle = symbol_or_file.strip()
        in_file = [
            self._node_of(raw)
            for raw in loaded.nodes
            if isinstance(raw, dict) and str(raw.get("source_file") or "") == needle
        ]
        if in_file:
            stale, reason = self._freshness(needle)
            in_file.sort(key=lambda node: (node.label.lower(), node.id))
            return RelatedSymbolsResult(nodes=in_file[:limit], stale=stale, stale_reason=reason)
        lowered = needle.lower()
        direct = [
            self._node_of(raw)
            for raw in loaded.nodes
            if isinstance(raw, dict) and lowered in str(raw.get("label") or "").lower()
        ]
        direct_ids = {node.id for node in direct}
        by_id = {
            str(raw.get("id")): self._node_of(raw)
            for raw in loaded.nodes
            if isinstance(raw, dict) and raw.get("id") is not None
        }
        neighbours: dict[str, GraphNode] = {}
        for raw in loaded.links:
            if not isinstance(raw, dict):
                continue
            source, target = str(raw.get("source")), str(raw.get("target"))
            other: str | None = None
            if source in direct_ids:
                other = target
            elif target in direct_ids:
                other = source
            if other is not None and other not in direct_ids and other in by_id:
                neighbours.setdefault(other, by_id[other])
        combined = sorted(
            direct + sorted(neighbours.values(), key=lambda n: (n.label.lower(), n.id)),
            key=lambda node: (node.label.lower(), node.id),
        )
        if self._looks_like_path(needle):
            stale, reason = self._freshness(needle)
            return RelatedSymbolsResult(nodes=combined[:limit], stale=stale, stale_reason=reason)
        stale, reason = self._stale_state()
        return RelatedSymbolsResult(nodes=combined[:limit], stale=stale, stale_reason=reason)

    @staticmethod
    def _looks_like_path(topic: str) -> bool:
        return "/" in topic or topic.endswith((".py", ".md", ".toml", ".json", ".yml", ".yaml"))

    def refresh_graph(self) -> None:
        """Explicitly unsupported (DEC-0042): graph rebuilds are end-of-task
        operations driven by the main conversation, never by an agent call.
        Raises before any I/O — and this module imports no subprocess
        machinery at all, so nothing can be launched from here."""
        raise KnowledgeError(
            KnowledgeError.REFRESH_UNSUPPORTED,
            "graph refresh is an end-of-task operation, not an agent call",
        )
