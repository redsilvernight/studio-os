"""Deterministic, LLM-free bridge from decisions to the code graph (Phase 6).

Reads the unit ADRs (docs/decisions/DEC-*.md -- the canonical source; the
vault notes Phase 5 syncs from them carry the identical `graphify_entities`
after a sync, so reading ADRs directly is equivalent and avoids a second
dependency on the vault path) and produces a *separate* decision sub-graph:
one node per decision, one node per entity/decision it references, and
typed edges between them. This is written to its own artifact
(`decisions_subgraph.json`) -- the AST code graph (`graph.json`) is never
opened for writing here, so there is no risk of tripping Graphify's
anti-shrink protection or losing nodes. `compose_graphs` builds the
queryable union of the two in memory (or to a third `graph.composite.json`
artifact) without ever mutating either input.

Edge relations: an ADR's `graphify_entities` carry a `relation` field
inherited from the vault schema (observed value so far: "concerns"). Rather
than inventing a mapping not evidenced anywhere, only the mandate's own
vocabulary (affects/implements/constrains/supersedes/documents) is used
verbatim when an entity already specifies one of those; anything else
(currently just "concerns") maps to the closest match, "documents" -- a
decision documenting a concern about a symbol -- and nothing here invents a
relation a human hasn't stated in some form.

An entity reference is only ever turned into an edge when its `node_id` is
non-null AND present in the current AST graph's node set. Anything else
(null node_id, or a node_id the graph no longer has) is refused and
reported, never silently dropped or guessed into an edge.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adr_common import parse_adr_markdown

DECISIONS_DIR_RELPATH = "docs/decisions"
DEFAULT_GRAPH_PATH = Path(r"E:\Graphify\Studio-OS\graphify-out\graph.json")
DEFAULT_SUBGRAPH_PATH = Path(r"E:\Graphify\Studio-OS\graphify-out\decisions_subgraph.json")

KNOWN_RELATIONS = {"affects", "implements", "constrains", "supersedes", "documents"}
RELATION_FALLBACK = {"concerns": "documents"}


def decision_node_id(dec_id: str) -> str:
    return f"decision_{dec_id.lower().replace('-', '_')}"


@dataclass
class RefusedReference:
    dec_id: str
    node_id: str | None
    symbol: str | None
    reason: str


@dataclass
class DecisionSubgraph:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    refused: list[RefusedReference] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "refused_references": [r.__dict__ for r in self.refused],
        }


def _map_relation(raw: str | None) -> str:
    if raw in KNOWN_RELATIONS:
        return raw
    return RELATION_FALLBACK.get(raw or "", "documents")


def load_graph_node_ids(graph_path: Path) -> set[str] | None:
    if not graph_path.exists():
        return None
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return {n["id"] for n in data.get("nodes", []) if isinstance(n, dict) and "id" in n}


def build_decision_subgraph(
    decisions_dir: Path, graph_node_ids: set[str] | None
) -> DecisionSubgraph:
    sub = DecisionSubgraph()
    adrs: dict[str, dict[str, Any]] = {}
    for path in sorted(decisions_dir.glob("DEC-*.md")):
        fields, _body = parse_adr_markdown(path.read_text(encoding="utf-8"))
        adrs[fields["id"]] = fields

    for dec_id, fields in adrs.items():
        node_id = decision_node_id(dec_id)
        sub.nodes.append(
            {
                "id": node_id,
                "label": f"{dec_id} — {fields['title']}",
                "file_type": "rationale",
                "decision_id": dec_id,
                "status": fields.get("status"),
            }
        )

        for entity in fields.get("graphify_entities") or []:
            symbol = entity.get("symbol")
            raw_node_id = entity.get("node_id")
            if raw_node_id is None:
                sub.refused.append(
                    RefusedReference(
                        dec_id=dec_id,
                        node_id=None,
                        symbol=symbol,
                        reason="entity has no node_id (unresolved reference)",
                    )
                )
                continue
            if graph_node_ids is not None and raw_node_id not in graph_node_ids:
                sub.refused.append(
                    RefusedReference(
                        dec_id=dec_id,
                        node_id=raw_node_id,
                        symbol=symbol,
                        reason="node_id not present in the current AST graph",
                    )
                )
                continue
            sub.edges.append(
                {
                    "source": node_id,
                    "target": raw_node_id,
                    "relation": _map_relation(entity.get("relation")),
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                }
            )

        for field_name, relation in (("supersedes", "supersedes"), ("superseded_by", "supersedes")):
            target_dec = fields.get(field_name)
            if not target_dec:
                continue
            if target_dec not in adrs:
                sub.refused.append(
                    RefusedReference(
                        dec_id=dec_id,
                        node_id=target_dec,
                        symbol=None,
                        reason=f"{field_name} references a DEC id with no ADR",
                    )
                )
                continue
            source, target = (
                (node_id, decision_node_id(target_dec))
                if field_name == "supersedes"
                else (decision_node_id(target_dec), node_id)
            )
            sub.edges.append(
                {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                }
            )

    return sub


def write_subgraph(path: Path, sub: DecisionSubgraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sub.to_dict(), indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )


def _base_edges(base_graph: dict[str, Any]) -> list[Any]:
    """graph.json is Graphify's networkx node-link export: edges live under
    "links", not "edges" (confirmed against the real Studio OS graph.json,
    which has 0 top-level "edges" and thousands of "links"). Accept a plain
    "edges" key too, for a base graph built by something else."""
    if "links" in base_graph:
        return list(base_graph["links"])
    return list(base_graph.get("edges", []))


def compose_graphs(base_graph: dict[str, Any], sub: DecisionSubgraph) -> dict[str, Any]:
    """Pure union for querying -- never mutates `base_graph`. Node/edge ids
    are unique by construction (decision_* vs AST node ids never collide),
    so this is a plain concatenation, not a merge with conflict rules."""
    return {
        "nodes": list(base_graph.get("nodes", [])) + list(sub.nodes),
        "edges": _base_edges(base_graph) + list(sub.edges),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--graph-path", type=Path, default=DEFAULT_GRAPH_PATH)
    ap.add_argument("--out", type=Path, default=DEFAULT_SUBGRAPH_PATH)
    ap.add_argument("--composite-out", type=Path, default=None)
    args = ap.parse_args()

    decisions_dir = args.root / DECISIONS_DIR_RELPATH
    graph_node_ids = load_graph_node_ids(args.graph_path)
    sub = build_decision_subgraph(decisions_dir, graph_node_ids)
    write_subgraph(args.out, sub)

    print(
        f"decision subgraph: {len(sub.nodes)} node(s), {len(sub.edges)} edge(s), "
        f"{len(sub.refused)} refused reference(s) -> {args.out}"
    )
    for r in sub.refused:
        print(f"  REFUSED {r.dec_id}: {r.symbol or r.node_id} -- {r.reason}")

    if args.composite_out is not None:
        base_graph = (
            json.loads(args.graph_path.read_text(encoding="utf-8"))
            if args.graph_path.exists()
            else {"nodes": [], "edges": []}
        )
        composite = compose_graphs(base_graph, sub)
        args.composite_out.parent.mkdir(parents=True, exist_ok=True)
        args.composite_out.write_text(
            json.dumps(composite, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(
            f"composite graph: {len(composite['nodes'])} node(s), "
            f"{len(composite['edges'])} edge(s) -> {args.composite_out}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
