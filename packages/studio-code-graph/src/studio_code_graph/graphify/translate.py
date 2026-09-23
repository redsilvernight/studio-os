from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from studio_contracts.local.common import LocalResourceKind, build_local_uri
from studio_contracts.local.graph import (
    Confidence,
    GraphEdge,
    GraphNode,
    GraphNodeRef,
    GraphProvenance,
    NodeKind,
    RelationKind,
)

from studio_code_graph.paths import is_selected, normalize_repo_relative
from studio_code_graph.provider import BuildFailure, CodeGraphBuildError

LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".gd": "gdscript",
}

RELATION_MAP: dict[str, RelationKind] = {
    "contains": RelationKind.CONTAINS,
    "method": RelationKind.CONTAINS,
    "imports": RelationKind.IMPORTS,
    "imports_from": RelationKind.IMPORTS,
    "calls": RelationKind.CALLS,
    "inherits": RelationKind.INHERITS,
}

_LINE_RE = re.compile(r"L(\d{1,7})")
_IDENTIFIER_RE = re.compile(r"[^a-z0-9_.-]+")
_MAX_LINE = 9_999_999
_MAX_LABEL = 200


@dataclass(frozen=True)
class TranslationContext:
    workspace_id: UUID
    repo_name: str
    repo_root: Path
    source_id: str
    provider_id: str
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class Translation:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    languages: tuple[str, ...]
    dropped: dict[str, int]


@dataclass
class _RawNode:
    native_id: str
    kind: NodeKind
    label: str
    path: str
    line: int | None
    extractor: str


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:24]


def language_of(path: str) -> str | None:
    return LANGUAGE_BY_EXTENSION.get(PurePosixPath(path).suffix.lower())


def _line_of(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = _LINE_RE.search(value)
    if match is None:
        return None
    line = int(match.group(1))
    return line if 1 <= line <= _MAX_LINE else None


def _extractor(origin: object, provider_id: str) -> str:
    text = _IDENTIFIER_RE.sub("_", str(origin or "ast").lower()).strip("_")
    return f"{provider_id}.{text or 'ast'}"[:64]


def _clean_label(label: str) -> str:
    text = label.strip()
    if text.endswith("()"):
        text = text[:-2]
    return text.lstrip(".") or label.strip()


def _links(graph: dict[str, Any]) -> list[object]:
    raw = graph.get("links", graph.get("edges"))
    if not isinstance(raw, list):
        raise CodeGraphBuildError(BuildFailure.OUTPUT_CORRUPT, "graph output has no edge list")
    return raw


def _classify(raw: dict[str, Any], path: str) -> NodeKind | None:
    if raw.get("_callable_class"):
        return NodeKind.CLASS
    if raw.get("_callable"):
        return NodeKind.FUNCTION
    if str(raw.get("label", "")) == PurePosixPath(path).name:
        return NodeKind.FILE
    return None


def _collect_nodes(
    graph: dict[str, Any], context: TranslationContext, dropped: Counter[str]
) -> dict[str, _RawNode]:
    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list):
        raise CodeGraphBuildError(BuildFailure.OUTPUT_CORRUPT, "graph output has no node list")
    collected: dict[str, _RawNode] = {}
    for raw in raw_nodes:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            dropped["malformed_node"] += 1
            continue
        if raw.get("file_type", "code") != "code":
            dropped["non_code_node"] += 1
            continue
        source_file = str(raw.get("source_file") or "")
        if not source_file.strip():
            dropped["unresolved_external_node"] += 1
            continue
        path = normalize_repo_relative(source_file, context.repo_root)
        if path is None:
            dropped["unsafe_path"] += 1
            continue
        if not is_selected(path, context.include_globs, context.exclude_globs) or (
            context.languages and language_of(path) not in context.languages
        ):
            dropped["excluded_by_config"] += 1
            continue
        kind = _classify(raw, path)
        if kind is None:
            dropped["unsupported_node_kind"] += 1
            continue
        label = str(raw.get("label", ""))
        collected[raw["id"]] = _RawNode(
            native_id=raw["id"],
            kind=kind,
            label=path if kind is NodeKind.FILE else _clean_label(label),
            path=path,
            line=_line_of(raw.get("source_location")),
            extractor=_extractor(raw.get("_origin"), context.provider_id),
        )
    return collected


def _qualify_methods(raw_links: list[object], nodes: dict[str, _RawNode]) -> None:
    for link in raw_links:
        if not isinstance(link, dict) or link.get("relation") != "method":
            continue
        owner = nodes.get(str(link.get("source")))
        member = nodes.get(str(link.get("target")))
        if owner is not None and member is not None and owner.kind is NodeKind.CLASS:
            member.label = f"{owner.label}.{member.label}"


def _assign_ids(nodes: dict[str, _RawNode], context: TranslationContext) -> dict[str, str]:
    seen: Counter[tuple[str, str, str]] = Counter()
    ids: dict[str, str] = {}
    ordered = sorted(
        nodes.values(), key=lambda item: (item.path, item.line or 0, item.label, item.native_id)
    )
    for item in ordered:
        key = (item.kind.value, item.path, item.label)
        occurrence = seen[key]
        seen[key] += 1
        ids[item.native_id] = "n-" + _digest(
            context.repo_name, item.kind.value, item.path, item.label, str(occurrence)
        )
    return ids


def _uri(context: TranslationContext, path: str, line: int | None) -> str | None:
    try:
        return build_local_uri(
            LocalResourceKind.CODE,
            context.workspace_id,
            f"{context.repo_name}/{path}",
            fragment=f"L{line}" if line else None,
        )
    except ValueError:
        return None


def _build_nodes(
    nodes: dict[str, _RawNode],
    ids: dict[str, str],
    context: TranslationContext,
    dropped: Counter[str],
) -> tuple[dict[str, GraphNode], set[str]]:
    built: dict[str, GraphNode] = {}
    languages: set[str] = set()
    for native_id, item in nodes.items():
        metadata: dict[str, str | int | float | bool | None] = {
            "repo": context.repo_name,
            "path": item.path,
        }
        if item.line is not None:
            metadata["line"] = item.line
        language = language_of(item.path)
        if language is not None:
            metadata["language"] = language
        try:
            built[native_id] = GraphNode(
                node_id=ids[native_id],
                kind=item.kind,
                label=item.label[:_MAX_LABEL],
                uri=_uri(context, item.path, item.line),
                provenance=GraphProvenance(
                    source_id=context.source_id,
                    extractor=item.extractor,
                    confidence=Confidence.EXTRACTED,
                ),
                metadata=metadata,
            )
        except ValidationError:
            dropped["invalid_node"] += 1
            continue
        if language is not None:
            languages.add(language)
    return built, languages


def _edge_confidence(raw: object) -> Confidence | None:
    value = str(raw or "").upper()
    if value == "EXTRACTED":
        return Confidence.EXTRACTED
    if value == "INFERRED":
        return Confidence.INFERRED
    return None


def _build_edges(
    raw_links: list[object],
    nodes: dict[str, _RawNode],
    built: dict[str, GraphNode],
    context: TranslationContext,
    dropped: Counter[str],
) -> list[GraphEdge]:
    edges: dict[str, GraphEdge] = {}
    for link in raw_links:
        if not isinstance(link, dict):
            dropped["malformed_edge"] += 1
            continue
        native_relation = str(link.get("relation", ""))
        kind = RELATION_MAP.get(native_relation)
        if kind is None:
            dropped["unsupported_relation"] += 1
            continue
        source_key, target_key = str(link.get("source")), str(link.get("target"))
        if source_key not in built or target_key not in built:
            dropped["unresolved_external_edge"] += 1
            continue
        confidence = _edge_confidence(link.get("confidence"))
        if confidence is None:
            dropped["unreliable_edge"] += 1
            continue
        source_node, target_node = built[source_key], built[target_key]
        if kind is RelationKind.CONTAINS and source_node.node_id == target_node.node_id:
            dropped["self_containment"] += 1
            continue
        edge_id = "e-" + _digest(kind.value, source_node.node_id, target_node.node_id)
        if edge_id in edges:
            dropped["duplicate_edge"] += 1
            continue
        evidence = None
        if confidence is Confidence.INFERRED:
            origin = nodes[source_key]
            evidence_line = _line_of(link.get("source_location")) or origin.line
            evidence = _uri(context, origin.path, evidence_line)
            if evidence is None:
                dropped["unreliable_edge"] += 1
                continue
        metadata: dict[str, str | int | float | bool | None] = {}
        if native_relation != kind.value:
            metadata["native_relation"] = native_relation
        line = _line_of(link.get("source_location"))
        if line is not None:
            metadata["line"] = line
        edges[edge_id] = GraphEdge(
            edge_id=edge_id,
            kind=kind,
            source=GraphNodeRef(source_id=context.source_id, node_id=source_node.node_id),
            target=GraphNodeRef(source_id=context.source_id, node_id=target_node.node_id),
            provenance=GraphProvenance(
                source_id=context.source_id,
                extractor=nodes[source_key].extractor,
                confidence=confidence,
                evidence=evidence,
            ),
            metadata=metadata,
        )
    return [edges[key] for key in sorted(edges)]


def translate_graph(graph: object, context: TranslationContext) -> Translation:
    """Graphify `graph.json` -> common graph schema. Only what Graphify states
    is kept: facts it cannot ground in a repo file, relations outside the P1
    vocabulary and low-confidence edges are counted in `dropped`, never
    reinterpreted."""
    if not isinstance(graph, dict):
        raise CodeGraphBuildError(BuildFailure.OUTPUT_CORRUPT, "graph output is not an object")
    dropped: Counter[str] = Counter()
    raw_links = _links(graph)
    raw_nodes = _collect_nodes(graph, context, dropped)
    _qualify_methods(raw_links, raw_nodes)
    ids = _assign_ids(raw_nodes, context)
    built, languages = _build_nodes(raw_nodes, ids, context, dropped)
    edges = _build_edges(raw_links, raw_nodes, built, context, dropped)
    nodes = sorted(built.values(), key=lambda node: node.node_id)
    return Translation(nodes, edges, tuple(sorted(languages)), dict(sorted(dropped.items())))
