"""Tests for the Phase 6 deterministic decision -> code graph bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.adr_common import adr_filename, content_hash, render_adr_markdown
from scripts.decision_graph import build_decision_subgraph, compose_graphs, decision_node_id


def _write_adr(
    decisions_dir: Path, dec_id: str, title: str, body: str = "Corps.", **extra: Any
) -> Path:
    decisions_dir.mkdir(parents=True, exist_ok=True)
    fields = {
        "id": dec_id,
        "title": title,
        "source": "docs/DECISIONS.md",
        "sync_hash": content_hash(body),
        **extra,
    }
    path = decisions_dir / adr_filename(dec_id, title)
    path.write_text(render_adr_markdown(fields, body), encoding="utf-8")
    return path


def test_every_decision_becomes_a_node(tmp_path: Path) -> None:
    _write_adr(tmp_path / "decisions", "DEC-0001", "Titre un")
    _write_adr(tmp_path / "decisions", "DEC-0002", "Titre deux")
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids=None)
    assert {n["id"] for n in sub.nodes} == {
        decision_node_id("DEC-0001"),
        decision_node_id("DEC-0002"),
    }


def test_resolved_entity_becomes_an_edge(tmp_path: Path) -> None:
    _write_adr(
        tmp_path / "decisions",
        "DEC-0001",
        "Titre",
        graphify_entities=[{"node_id": "some_symbol", "symbol": "Some", "relation": "concerns"}],
    )
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids={"some_symbol"})
    assert len(sub.edges) == 1
    edge = sub.edges[0]
    assert edge["source"] == decision_node_id("DEC-0001")
    assert edge["target"] == "some_symbol"
    assert edge["relation"] == "documents"  # "concerns" mapped, not invented
    assert sub.refused == []


def test_entity_missing_from_graph_is_refused_not_silently_dropped(tmp_path: Path) -> None:
    _write_adr(
        tmp_path / "decisions",
        "DEC-0001",
        "Titre",
        graphify_entities=[{"node_id": "ghost_symbol", "symbol": "Ghost", "relation": "concerns"}],
    )
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids={"other_symbol"})
    assert sub.edges == []
    assert len(sub.refused) == 1
    assert sub.refused[0].node_id == "ghost_symbol"


def test_null_node_id_is_refused(tmp_path: Path) -> None:
    _write_adr(
        tmp_path / "decisions",
        "DEC-0001",
        "Titre",
        graphify_entities=[{"node_id": None, "symbol": "Unresolved", "relation": "concerns"}],
    )
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids=set())
    assert sub.edges == []
    assert sub.refused[0].symbol == "Unresolved"


def test_no_graph_available_resolves_everything_optimistically(tmp_path: Path) -> None:
    """When graph.json isn't available (graph_node_ids=None), a non-null
    node_id is still wired -- there's nothing to refuse it against."""
    _write_adr(
        tmp_path / "decisions",
        "DEC-0001",
        "Titre",
        graphify_entities=[{"node_id": "x", "symbol": "X", "relation": "concerns"}],
    )
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids=None)
    assert len(sub.edges) == 1
    assert sub.refused == []


def test_known_relation_vocabulary_passes_through_unchanged(tmp_path: Path) -> None:
    _write_adr(
        tmp_path / "decisions",
        "DEC-0001",
        "Titre",
        graphify_entities=[{"node_id": "x", "symbol": "X", "relation": "implements"}],
    )
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids={"x"})
    assert sub.edges[0]["relation"] == "implements"


def test_superseded_by_creates_a_supersedes_edge_between_decisions(tmp_path: Path) -> None:
    _write_adr(tmp_path / "decisions", "DEC-0001", "Ancien")
    _write_adr(tmp_path / "decisions", "DEC-0002", "Nouveau", superseded_by="DEC-0001")
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids=None)
    supersede_edges = [e for e in sub.edges if e["relation"] == "supersedes"]
    assert len(supersede_edges) == 1
    assert supersede_edges[0]["source"] == decision_node_id("DEC-0001")
    assert supersede_edges[0]["target"] == decision_node_id("DEC-0002")


def test_dangling_supersedes_reference_is_refused(tmp_path: Path) -> None:
    _write_adr(tmp_path / "decisions", "DEC-0001", "Titre", supersedes="DEC-9999")
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids=None)
    assert sub.edges == []
    assert any(r.node_id == "DEC-9999" for r in sub.refused)


def test_build_decision_subgraph_is_idempotent(tmp_path: Path) -> None:
    _write_adr(
        tmp_path / "decisions",
        "DEC-0001",
        "Titre",
        graphify_entities=[{"node_id": "x", "symbol": "X", "relation": "concerns"}],
    )
    first = build_decision_subgraph(tmp_path / "decisions", graph_node_ids={"x"})
    second = build_decision_subgraph(tmp_path / "decisions", graph_node_ids={"x"})
    assert first.to_dict() == second.to_dict()


def test_compose_graphs_is_a_pure_union_and_never_mutates_inputs(tmp_path: Path) -> None:
    _write_adr(
        tmp_path / "decisions",
        "DEC-0001",
        "Titre",
        graphify_entities=[{"node_id": "x", "symbol": "X", "relation": "concerns"}],
    )
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids={"x"})
    base = {"nodes": [{"id": "x"}], "edges": [{"source": "x", "target": "y", "relation": "calls"}]}
    base_copy = {"nodes": list(base["nodes"]), "edges": list(base["edges"])}

    composite = compose_graphs(base, sub)
    assert base == base_copy  # base_graph untouched
    assert len(composite["nodes"]) == len(base["nodes"]) + len(sub.nodes)
    assert len(composite["edges"]) == len(base["edges"]) + len(sub.edges)


def test_compose_graphs_reads_edges_from_networkx_links_key(tmp_path: Path) -> None:
    """Graphify's real graph.json is a networkx node-link export: its edges
    live under "links", not "edges". A base graph with "edges": [] but real
    data under "links" must not be composed as if it had zero base edges."""
    _write_adr(
        tmp_path / "decisions",
        "DEC-0001",
        "Titre",
        graphify_entities=[{"node_id": "x", "symbol": "X", "relation": "concerns"}],
    )
    sub = build_decision_subgraph(tmp_path / "decisions", graph_node_ids={"x"})
    base = {
        "nodes": [{"id": "x"}],
        "links": [{"source": "x", "target": "y", "relation": "calls"}],
        "edges": [],  # present but empty, as in the real Graphify export
    }
    composite = compose_graphs(base, sub)
    assert len(composite["edges"]) == 1 + len(sub.edges)
