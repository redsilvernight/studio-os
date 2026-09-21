from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from studio_code_graph.index import (
    MAX_PAGE_EDGES,
    CodeGraphIndex,
    InvalidCursorError,
    UnknownNodeError,
)
from studio_contracts.local.common import LocalResourceKind, build_local_uri
from studio_contracts.local.graph import (
    Confidence,
    GraphDirection,
    GraphEdge,
    GraphNode,
    GraphNodeRef,
    GraphProvenance,
    GraphSource,
    GraphSourceKind,
    NodeKind,
    RelationKind,
)

from .support import WORKSPACE_ID

SOURCE_ID = "code.fake"
SOURCE = GraphSource(
    source_id=SOURCE_ID,
    kind=GraphSourceKind.CODE,
    provider_id="fake",
    workspace_id=WORKSPACE_ID,
    generated_at=datetime(2026, 1, 1, tzinfo=UTC),
)


def make_node(kind: NodeKind, label: str, path: str = "a.py") -> GraphNode:
    digest = hashlib.sha256(f"{kind}{label}{path}".encode()).hexdigest()[:16]
    return GraphNode(
        node_id=f"n-{digest}",
        kind=kind,
        label=label,
        uri=build_local_uri(LocalResourceKind.CODE, WORKSPACE_ID, f"app/{path}"),
        provenance=GraphProvenance(
            source_id=SOURCE_ID, extractor="fake.ast", confidence=Confidence.EXTRACTED
        ),
    )


def make_edge(kind: RelationKind, source: GraphNode, target: GraphNode) -> GraphEdge:
    digest = hashlib.sha256(f"{kind}{source.node_id}{target.node_id}".encode()).hexdigest()[:16]
    return GraphEdge(
        edge_id=f"e-{digest}",
        kind=kind,
        source=GraphNodeRef(source_id=SOURCE_ID, node_id=source.node_id),
        target=GraphNodeRef(source_id=SOURCE_ID, node_id=target.node_id),
        provenance=GraphProvenance(
            source_id=SOURCE_ID, extractor="fake.ast", confidence=Confidence.EXTRACTED
        ),
    )


def small_graph() -> tuple[list[GraphNode], list[GraphEdge]]:
    file_a = make_node(NodeKind.FILE, "a.py", "a.py")
    file_b = make_node(NodeKind.FILE, "b.py", "b.py")
    klass = make_node(NodeKind.CLASS, "Greeter")
    method = make_node(NodeKind.FUNCTION, "Greeter.greet")
    func = make_node(NodeKind.FUNCTION, "helper", "b.py")
    edges = [
        make_edge(RelationKind.CONTAINS, file_a, klass),
        make_edge(RelationKind.CONTAINS, klass, method),
        make_edge(RelationKind.CONTAINS, file_b, func),
        make_edge(RelationKind.IMPORTS, file_a, file_b),
        make_edge(RelationKind.CALLS, method, func),
    ]
    return [file_a, file_b, klass, method, func], edges


def small_index() -> CodeGraphIndex:
    nodes, edges = small_graph()
    return CodeGraphIndex(SOURCE_ID, "f" * 64, nodes, edges)


def star_index(size: int) -> CodeGraphIndex:
    hub = make_node(NodeKind.FILE, "hub.py", "hub.py")
    leaves = [make_node(NodeKind.FUNCTION, f"fn{i}", "hub.py") for i in range(size)]
    edges = [make_edge(RelationKind.CONTAINS, hub, leaf) for leaf in leaves]
    return CodeGraphIndex(SOURCE_ID, "a" * 64, [hub, *leaves], edges)


def test_counts_and_membership() -> None:
    index = small_index()
    assert index.node_count == 5 and index.edge_count == 5
    nodes, _ = small_graph()
    assert index.has_node(nodes[0].node_id) and not index.has_node("n-missing")


def test_edges_to_unknown_nodes_are_ignored() -> None:
    nodes, edges = small_graph()
    ghost = make_node(NodeKind.FUNCTION, "ghost")
    extra = make_edge(RelationKind.CALLS, nodes[3], ghost)
    index = CodeGraphIndex(SOURCE_ID, "f" * 64, nodes, [*edges, extra])
    assert index.edge_count == 5


def test_page_is_a_valid_contract_page_and_filters_by_kind() -> None:
    index = small_index()
    page = index.page(SOURCE, 100, None, [])
    assert page.counts.total_nodes == 5 and page.next_cursor is None and not page.truncated
    files = index.page(SOURCE, 100, None, [NodeKind.FILE])
    assert {node.kind for node in files.nodes} == {NodeKind.FILE}
    assert files.counts.total_nodes == 2
    ids = {node.node_id for node in files.nodes}
    assert all(ref.node_id not in ids for ref in files.frontier), (
        "frontier holds only nodes outside the page"
    )


def test_paging_covers_every_node_exactly_once() -> None:
    index = small_index()
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        page = index.page(SOURCE, 2, cursor, [])
        seen.extend(node.node_id for node in page.nodes)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == 5 and len(set(seen)) == 5


def test_page_bounds_hold_for_a_hub_node() -> None:
    index = star_index(1500)
    page = index.page(SOURCE, 500, None, [])
    assert len(page.nodes) <= 500 and len(page.edges) <= MAX_PAGE_EDGES
    assert len(page.frontier) <= 500
    seen = {node.node_id for node in page.nodes}
    frontier = {ref.node_id for ref in page.frontier}
    assert all(
        edge.source.node_id in seen | frontier and edge.target.node_id in seen | frontier
        for edge in page.edges
    )


def test_every_edge_is_reachable_through_paging() -> None:
    index = star_index(300)
    edges: set[str] = set()
    cursor = None
    while True:
        page = index.page(SOURCE, 100, cursor, [])
        edges.update(edge.edge_id for edge in page.edges)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(edges) == 300


def test_cursor_bound_to_its_index_and_query() -> None:
    index = small_index()
    cursor = index.page(SOURCE, 2, None, []).next_cursor
    assert cursor is not None
    with pytest.raises(InvalidCursorError):
        index.page(SOURCE, 2, cursor, [NodeKind.FILE])
    with pytest.raises(InvalidCursorError):
        star_index(5).page(SOURCE, 2, cursor, [])
    with pytest.raises(InvalidCursorError):
        index.page(SOURCE, 2, "garbage", [])
    with pytest.raises(InvalidCursorError):
        index.page(SOURCE, 2, f"{cursor.split('.')[0]}.9999", [])


def test_expand_by_direction_and_relation() -> None:
    index = small_index()
    nodes, _ = small_graph()
    file_a = nodes[0]
    both = index.expand(SOURCE, file_a.node_id, GraphDirection.BOTH, [], 50, None)
    assert {edge.kind for edge in both.edges} == {RelationKind.CONTAINS, RelationKind.IMPORTS}
    only_imports = index.expand(
        SOURCE, file_a.node_id, GraphDirection.OUT, [RelationKind.IMPORTS], 50, None
    )
    assert [edge.kind for edge in only_imports.edges] == [RelationKind.IMPORTS]
    incoming = index.expand(
        SOURCE, nodes[1].node_id, GraphDirection.IN, [RelationKind.IMPORTS], 50, None
    )
    assert [edge.source.node_id for edge in incoming.edges] == [file_a.node_id]
    assert file_a.node_id in {node.node_id for node in incoming.nodes}


def test_expand_pages_a_hub() -> None:
    index = star_index(1200)
    hub_id = next(node.node_id for node in index.page(SOURCE, 1, None, [NodeKind.FILE]).nodes)
    total = 0
    cursor = None
    while True:
        page = index.expand(SOURCE, hub_id, GraphDirection.OUT, [], 500, cursor)
        assert len(page.nodes) <= 500
        total += len(page.edges)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert total == 1200


def test_expand_unknown_node_and_bad_cursor() -> None:
    index = small_index()
    with pytest.raises(UnknownNodeError):
        index.expand(SOURCE, "n-nope", GraphDirection.BOTH, [], 10, None)
    nodes, _ = small_graph()
    with pytest.raises(InvalidCursorError):
        index.expand(SOURCE, nodes[0].node_id, GraphDirection.BOTH, [], 10, "x.1")


def test_search_ranking_kinds_and_paging() -> None:
    index = small_index()
    refs, cursor = index.search("greet", [], 10, None)
    assert [ref.name for ref in refs][0] == "Greeter.greet" and cursor is None
    exact, _ = index.search("helper", [], 10, None)
    assert exact[0].name == "helper"
    classes, _ = index.search("gree", [NodeKind.CLASS], 10, None)
    assert [ref.name for ref in classes] == ["Greeter"]
    first, cursor = index.search("e", [], 2, None)
    assert len(first) == 2 and cursor is not None
    second, _ = index.search("e", [], 2, cursor)
    assert not {r.node_id for r in first} & {r.node_id for r in second}
    assert index.search("zzz", [], 10, None) == ([], None)


def test_search_cursor_is_bound_to_the_query() -> None:
    index = small_index()
    _, cursor = index.search("e", [], 1, None)
    assert cursor is not None
    with pytest.raises(InvalidCursorError):
        index.search("r", [], 1, cursor)
