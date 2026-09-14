"""Global control sequence for the decisions/vault/Graphify pipeline
(Phase 8). Runs, in order:

  1. ADR validation (parseable front matter, unique ids, filename<->id match)
  2. docs/DECISIONS.md index freshness (adr_index --check equivalent)
  3. vault sync status (adr_common/vault_sync --check equivalent)
  4. Graphify reference integrity (vault_lint)
  5. decision sub-graph build (decision_graph, no LLM)
  6. composite graph node/edge count sanity (before/after AST graph)
  7. cost ledger report (graphify_ledger, if a ledger is present)

Exits 0 only when every hard check (1-4) passes with zero errors; sub-graph
build/composite/cost are always attempted and reported, never silently
skipped, but a resolution gap there is a warning, not a failure (matching
the mandate: "plus de 98% des references... apres correction des
identifiants legitimes" is a target to work towards, not a hard gate on
every run).

Usage:
    uv run python -m scripts.graphify_control --root .
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path

from .adr_common import parse_adr_markdown
from .adr_index import DECISIONS_DIR_RELPATH as _ADR_DIR
from .adr_index import INDEX_RELPATH, render_index
from .decision_graph import (
    DEFAULT_GRAPH_PATH,
    build_decision_subgraph,
    compose_graphs,
    load_graph_node_ids,
)
from .vault_lint import run_lint
from .vault_sync import DEFAULT_VAULT_DIR as _SYNC_VAULT_DIR
from .vault_sync import plan_sync


def _load_ledger_module(root: Path) -> types.ModuleType | None:
    """The ledger engine (graphify_ledger.py) is canonically global, shipped
    next to `~/.claude/scripts/graphify_incremental_update.py` -- this
    project has no local copy of its own. Prefer a project-local
    `scripts/graphify_ledger.py` override if one shows up later."""
    project_local = root / "scripts" / "graphify_ledger.py"
    global_copy = Path.home() / ".claude" / "scripts" / "graphify_ledger.py"
    path = project_local if project_local.exists() else global_copy
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("graphify_ledger", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_adrs(decisions_dir: Path) -> list[str]:
    errors = []
    seen_ids: set[str] = set()
    for path in sorted(decisions_dir.glob("DEC-*.md")):
        try:
            fields, _body = parse_adr_markdown(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            errors.append(f"{path.name}: unparseable front matter ({exc})")
            continue
        dec_id = fields.get("id")
        if not dec_id:
            errors.append(f"{path.name}: missing id field")
            continue
        if dec_id in seen_ids:
            errors.append(f"{path.name}: duplicate id {dec_id}")
        seen_ids.add(dec_id)
        if not path.name.startswith(f"{dec_id}-"):
            errors.append(f"{path.name}: filename does not start with its own id {dec_id}")
        for required in ("title", "source", "sync_hash"):
            if not fields.get(required):
                errors.append(f"{path.name}: missing required field {required}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--vault-dir", type=Path, default=_SYNC_VAULT_DIR)
    ap.add_argument("--graph-path", type=Path, default=DEFAULT_GRAPH_PATH)
    ap.add_argument("--cost-json", type=Path, default=DEFAULT_GRAPH_PATH.parent / "cost.json")
    args = ap.parse_args()

    ok = True
    decisions_dir = args.root / _ADR_DIR

    print("== 1. validation ADR ==")
    adr_errors = validate_adrs(decisions_dir)
    if adr_errors:
        ok = False
        for e in adr_errors:
            print(f"  ERROR {e}")
    else:
        print(f"  OK ({len(list(decisions_dir.glob('DEC-*.md')))} ADR)")

    print("== 2. fraicheur de docs/DECISIONS.md ==")
    new_index = render_index(decisions_dir)
    current_index_path = args.root / INDEX_RELPATH
    current_index = (
        current_index_path.read_text(encoding="utf-8") if current_index_path.exists() else ""
    )
    if new_index != current_index:
        ok = False
        print("  ERROR docs/DECISIONS.md est perime (relancer scripts.adr_index --apply)")
    else:
        print("  OK")

    print("== 3. synchronisation vault ==")
    sync_plan = plan_sync(args.root, args.vault_dir)
    pending = [a for a in sync_plan.actions if a.kind in ("update", "create")]
    if pending or sync_plan.conflicts:
        ok = False
        print(
            f"  ERROR {len(pending)} action(s) en attente, {len(sync_plan.conflicts)} conflit(s) "
            f"(relancer scripts.vault_sync --apply / resoudre les conflits)"
        )
    else:
        print(f"  OK ({len(sync_plan.actions)} decision(s) synchronisee(s))")

    print("== 4. integrite des references Graphify (vault) ==")
    lint_report = run_lint(args.root, args.vault_dir, args.graph_path)
    if lint_report.errors:
        ok = False
        for issue in lint_report.errors:
            print(f"  ERROR {issue.check} ({issue.dec_id}): {issue.message}")
    else:
        print(f"  OK ({len(lint_report.issues)} avertissement(s))")
    if lint_report.entities_total:
        print(
            f"  entites resolues: {lint_report.entities_resolved}/{lint_report.entities_total} "
            f"({lint_report.resolution_rate:.1%})"
        )

    print("== 5. construction du sous-graphe de decisions ==")
    graph_node_ids = load_graph_node_ids(args.graph_path)
    sub = build_decision_subgraph(decisions_dir, graph_node_ids)
    print(
        f"  {len(sub.nodes)} noeud(s), {len(sub.edges)} arete(s), "
        f"{len(sub.refused)} reference(s) refusee(s) (0 token LLM)"
    )

    print("== 6. graphe composite (avant/apres) ==")
    if args.graph_path.exists():
        base_graph = json.loads(args.graph_path.read_text(encoding="utf-8"))
        base_nodes, base_edges = (
            len(base_graph.get("nodes", [])),
            len(base_graph.get("links", base_graph.get("edges", []))),
        )
        composite = compose_graphs(base_graph, sub)
        print(f"  avant: {base_nodes} noeud(s), {base_edges} arete(s)")
        print(f"  apres: {len(composite['nodes'])} noeud(s), {len(composite['edges'])} arete(s)")
    else:
        print("  graph.json absent -- sous-graphe seul disponible")

    print("== 7. rapport de cout ==")
    ledger_module = _load_ledger_module(args.root)
    if ledger_module is None:
        print("  moteur de ledger introuvable (ni local, ni global)")
    elif args.cost_json.exists():
        ledger = ledger_module.load_ledger(args.cost_json)
        print(f"  {json.dumps(ledger_module.cost_by_backend(ledger), ensure_ascii=False)}")
        print(f"  {json.dumps(ledger_module.ast_semantic_ratio(ledger), ensure_ascii=False)}")
    else:
        print("  cost.json absent")

    print(f"\n{'OK' if ok else 'ECHEC'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
