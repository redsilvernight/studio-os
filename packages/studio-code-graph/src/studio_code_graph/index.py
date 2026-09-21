from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from studio_contracts.local.code_graph import CodeSymbolRef
from studio_contracts.local.common import MAX_PAGE_LIMIT
from studio_contracts.local.graph import (
    GraphCounts,
    GraphDirection,
    GraphEdge,
    GraphNode,
    GraphNodeRef,
    GraphPage,
    GraphSource,
    NodeKind,
    RelationKind,
)

MAX_PAGE_EDGES = MAX_PAGE_LIMIT * 2
_EXPAND_NODE_CAP = MAX_PAGE_LIMIT - 1


class InvalidCursorError(ValueError):
    pass


class UnknownNodeError(LookupError):
    pass


@dataclass(frozen=True)
class SearchHit:
    rank: int
    label: str
    node: GraphNode


def _stamp(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:8]


def _encode(stamp: str, offset: int) -> str:
    return f"{stamp}.{offset}"


def _decode(cursor: str | None, stamp: str) -> int:
    if cursor is None:
        return 0
    head, _, tail = cursor.partition(".")
    if head != stamp or not tail.isdigit():
        raise InvalidCursorError("cursor does not belong to this index or query")
    return int(tail)


def _other_end(edge: GraphEdge, node_id: str) -> str:
    return edge.target.node_id if edge.source.node_id == node_id else edge.source.node_id


class CodeGraphIndex:
    """In-memory, read-only view over the snapshots of one workspace, built once
    per index change so UI queries never re-read files or re-run a provider."""

    def __init__(
        self,
        source_id: str,
        fingerprint: str,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
    ) -> None:
        self.source_id = source_id
        self.fingerprint = fingerprint
        self._nodes: list[GraphNode] = sorted(nodes, key=lambda node: node.node_id)
        self._by_id = {node.node_id: node for node in self._nodes}
        self._edges: list[GraphEdge] = sorted(
            (
                edge
                for edge in edges
                if edge.source.node_id in self._by_id and edge.target.node_id in self._by_id
            ),
            key=lambda edge: edge.edge_id,
        )
        self._incident: dict[str, list[GraphEdge]] = {}
        for edge in self._edges:
            self._incident.setdefault(edge.source.node_id, []).append(edge)
            if edge.target.node_id != edge.source.node_id:
                self._incident.setdefault(edge.target.node_id, []).append(edge)
        self._search_keys = [
            (node.label.lower(), node.label.lower().rsplit(".", 1)[-1], node)
            for node in self._nodes
            if node.uri is not None
        ]

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._by_id

    def page(
        self, source: GraphSource, limit: int, cursor: str | None, kinds: Sequence[NodeKind]
    ) -> GraphPage:
        wanted = frozenset(kinds)
        stamp = _stamp(self.fingerprint, *sorted(kind.value for kind in wanted))
        offset = _decode(cursor, stamp)
        pool = [node for node in self._nodes if not wanted or node.kind in wanted]
        if offset > len(pool):
            raise InvalidCursorError("cursor is past the end of the index")
        taken: list[GraphNode] = []
        page_ids: set[str] = set()
        edge_ids: set[str] = set()
        frontier: set[str] = set()
        edges: list[GraphEdge] = []
        truncated = False
        position = offset
        while position < len(pool) and len(taken) < limit:
            node = pool[position]
            fresh = [
                edge
                for edge in self._incident.get(node.node_id, ())
                if edge.edge_id not in edge_ids
            ]
            outside = {_other_end(edge, node.node_id) for edge in fresh} - page_ids - {node.node_id}
            next_frontier = (frontier - {node.node_id}) | outside
            fits = (
                len(edges) + len(fresh) <= MAX_PAGE_EDGES and len(next_frontier) <= MAX_PAGE_LIMIT
            )
            if not fits and taken:
                break
            if not fits:
                fresh, next_frontier, truncated = self._clip(node.node_id, fresh, page_ids)
            taken.append(node)
            page_ids.add(node.node_id)
            edges.extend(fresh)
            edge_ids.update(edge.edge_id for edge in fresh)
            frontier = next_frontier
            position += 1
        has_more = position < len(pool)
        return GraphPage(
            source=source,
            nodes=taken,
            edges=edges,
            frontier=[
                GraphNodeRef(source_id=self.source_id, node_id=item) for item in sorted(frontier)
            ],
            next_cursor=_encode(stamp, position) if has_more else None,
            truncated=has_more or truncated,
            counts=GraphCounts(
                nodes=len(taken),
                edges=len(edges),
                total_nodes=len(pool),
                total_edges=self.edge_count,
            ),
        )

    def _clip(
        self, node_id: str, fresh: list[GraphEdge], page_ids: set[str]
    ) -> tuple[list[GraphEdge], set[str], bool]:
        kept: list[GraphEdge] = []
        frontier: set[str] = set()
        for edge in fresh:
            other = _other_end(edge, node_id)
            adds = other not in page_ids and other != node_id and other not in frontier
            if len(kept) >= MAX_PAGE_EDGES or (adds and len(frontier) >= MAX_PAGE_LIMIT):
                continue
            kept.append(edge)
            if other != node_id:
                frontier.add(other)
        return kept, frontier, True

    def expand(
        self,
        source: GraphSource,
        node_id: str,
        direction: GraphDirection,
        relations: Sequence[RelationKind],
        limit: int,
        cursor: str | None,
    ) -> GraphPage:
        center = self._by_id.get(node_id)
        if center is None:
            raise UnknownNodeError("node is not part of this index")
        wanted = frozenset(relations)
        stamp = _stamp(
            self.fingerprint, node_id, direction.value, *sorted(kind.value for kind in wanted)
        )
        offset = _decode(cursor, stamp)
        incident = [
            edge
            for edge in self._incident.get(node_id, ())
            if (not wanted or edge.kind in wanted)
            and (
                direction is GraphDirection.BOTH
                or (direction is GraphDirection.OUT and edge.source.node_id == node_id)
                or (direction is GraphDirection.IN and edge.target.node_id == node_id)
            )
        ]
        if offset > len(incident):
            raise InvalidCursorError("cursor is past the end of the expansion")
        window = incident[offset : offset + min(limit, _EXPAND_NODE_CAP)]
        neighbours = {center.node_id: center}
        for edge in window:
            other = self._by_id[_other_end(edge, node_id)]
            neighbours[other.node_id] = other
        end = offset + len(window)
        has_more = end < len(incident)
        return GraphPage(
            source=source,
            nodes=sorted(neighbours.values(), key=lambda node: node.node_id),
            edges=window,
            next_cursor=_encode(stamp, end) if has_more else None,
            truncated=has_more,
            counts=GraphCounts(
                nodes=len(neighbours),
                edges=len(window),
                total_nodes=None,
                total_edges=len(incident),
            ),
        )

    def search(
        self, name: str, kinds: Sequence[NodeKind], limit: int, cursor: str | None
    ) -> tuple[list[CodeSymbolRef], str | None]:
        needle = name.strip().lower()
        wanted = frozenset(kinds)
        stamp = _stamp(self.fingerprint, needle, *sorted(kind.value for kind in wanted))
        offset = _decode(cursor, stamp)
        hits: list[SearchHit] = []
        for label, tail, node in self._search_keys:
            if wanted and node.kind not in wanted:
                continue
            if needle in (label, tail):
                rank = 0
            elif label.startswith(needle) or tail.startswith(needle):
                rank = 1
            elif needle in label:
                rank = 2
            else:
                continue
            hits.append(SearchHit(rank, label, node))
        hits.sort(key=lambda hit: (hit.rank, hit.label, hit.node.node_id))
        if offset > len(hits):
            raise InvalidCursorError("cursor is past the end of the results")
        window = hits[offset : offset + limit]
        refs = [
            CodeSymbolRef(
                node_id=hit.node.node_id,
                kind=hit.node.kind,
                name=hit.node.label,
                uri=hit.node.uri or "",
            )
            for hit in window
        ]
        end = offset + len(window)
        return refs, _encode(stamp, end) if end < len(hits) else None
