"""P16 evaluation — final before/after report of the vault roadmap.

Reads back the machine blocks of P00 (`docs/DEC_RELEVANCE_BASELINE_P00.md`),
P04 (`docs/VAULT_SEARCH_EVAL_P04.md`) and P07 (`docs/DEC_RELEVANCE_P07.md`),
replays the current decision selection through `scripts.dec_relevance_eval`
on the same 45 queries, and reads the `prepare_context` latency measured in
`docs/CONTEXT_LATENCY_P16.md` when it exists. No database, no server.

The report is published to `docs/VAULT_EVAL_P16.md` (human report + a machine
JSON block used by `--check`).

Usage:
    uv run python -m scripts.vault_eval_p16 --root . --check   # exit 1 if stale
    uv run python -m scripts.vault_eval_p16 --root . --apply   # (re)write it
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, cast

from scripts import dec_relevance_eval as dr
from scripts import vault_search_eval as vs

METRICS_FORMAT = "studio.eval.vault-p16/v1"
LATENCY_FORMAT = "studio.eval.context-latency/v1"
LATENCY_VERDICTS = ("acceptable", "too_slow")

REPORT_RELATIVE_PATH = "docs/VAULT_EVAL_P16.md"
LATENCY_RELATIVE_PATH = "docs/CONTEXT_LATENCY_P16.md"
P00_RELATIVE_PATH = dr.BASELINE_RELATIVE_PATH
P04_RELATIVE_PATH = vs.REPORT_RELATIVE_PATH
P07_RELATIVE_PATH = dr.REPORT_RELATIVE_PATH

METRICS_BEGIN = "<!-- VAULT_EVAL_P16_METRICS_BEGIN -->"
METRICS_END = "<!-- VAULT_EVAL_P16_METRICS_END -->"

PHASES = ("P00", "P04", "P07", "P16")
AGGREGATE_KEYS = (
    "queries",
    "empty_rate",
    "micro_recall",
    "macro_recall",
    "micro_precision",
    "true_positives",
    "expected_total",
    "retrieved_total",
    "tokens_total",
    "tokens_per_call_mean",
)

MET = "met"
MET_EXPLAINED = "met_with_explained_gap"
NOT_MET = "not_met"


def _read(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"{path}: missing report")
    return path.read_text(encoding="utf-8")


def load_phases(root: Path) -> dict[str, dict[str, Any]]:
    """The machine blocks of the frozen P00, P04 and P07 reports."""
    p00 = dr.load_baseline(root / P00_RELATIVE_PATH)
    if p00 is None:
        raise ValueError(f"{P00_RELATIVE_PATH}: machine block missing")
    p04 = json.loads(vs._extract_metrics(_read(root / P04_RELATIVE_PATH)))
    p07 = json.loads(dr._extract_metrics(_read(root / P07_RELATIVE_PATH)))
    return {"P00": p00, "P04": p04, "P07": p07}


def _json_fence(report: str) -> str | None:
    marker = "```json"
    if marker not in report:
        return None
    block = report.split(marker, 1)[1]
    if "```" not in block:
        raise ValueError("unterminated ```json block")
    return block.split("```", 1)[0].strip()


def load_latency(path: Path) -> dict[str, Any] | None:
    """The `studio.eval.context-latency/v1` block, or None when not measured."""
    if not path.is_file():
        return None
    block = _json_fence(path.read_text(encoding="utf-8"))
    if block is None:
        return None
    payload = cast(dict[str, Any], json.loads(block))
    if payload.get("format") != LATENCY_FORMAT:
        raise ValueError(f"{path}: unexpected format {payload.get('format')!r}")
    if payload.get("verdict") not in LATENCY_VERDICTS:
        raise ValueError(f"{path}: unexpected verdict {payload.get('verdict')!r}")
    measured = payload["global"]
    return {
        "source": LATENCY_RELATIVE_PATH,
        "p50_ms": measured["p50_ms"],
        "p95_ms": measured["p95_ms"],
        "max_ms": measured["max_ms"],
        "threshold_p95_ms": payload["threshold_p95_ms"],
        "verdict": payload["verdict"],
    }


async def replay_p16(root: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    queries = dr.load_queries(root / dr.QUERIES_RELATIVE_PATH)
    corpus = dr.load_corpus(root / dr.CORPUS_RELATIVE_PATH)
    selection = queries.get("selection", {})
    return await dr.run_eval(
        queries,
        corpus,
        limit=int(selection.get("limit", 5)),
        max_chars=int(selection.get("max_chars", 12000)),
        baseline=baseline,
    )


def _ids(metrics: dict[str, Any]) -> list[str]:
    return [row["id"] for row in metrics["per_query"]]


def _hits(row: dict[str, Any]) -> set[str]:
    return set(row["retrieved"]) & set(row["expected"])


def recall_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """True positives lost and gained per query, `before` → `after`."""
    before_by_id = {row["id"]: row for row in before["per_query"]}
    changes: list[dict[str, Any]] = []
    for row in after["per_query"]:
        previous = before_by_id.get(row["id"])
        if previous is None:
            continue
        lost = sorted(_hits(previous) - _hits(row))
        gained = sorted(_hits(row) - _hits(previous))
        if lost or gained:
            changes.append(
                {"id": row["id"], "objective": row["objective"], "lost": lost, "gained": gained}
            )
    return changes


def lexical_ceiling(p07: dict[str, Any]) -> dict[str, Any]:
    rows = [
        {"id": row["id"], "unreachable": list(row["lexically_unreachable"])}
        for row in p07["per_query"]
        if row["lexically_unreachable"]
    ]
    unreachable = sum(len(row["unreachable"]) for row in rows)
    expected = p07["aggregate"]["expected_total"]
    return {
        "source": P07_RELATIVE_PATH,
        "per_query": rows,
        "unreachable_total": unreachable,
        "expected_total": expected,
        "attainable_recall": round((expected - unreachable) / expected, dr.DECIMALS)
        if expected
        else 0.0,
    }


def _criteria(
    query_ids: dict[str, list[str]],
    phases: dict[str, dict[str, Any]],
    changes: list[dict[str, Any]],
    latency: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    reference = query_ids["P00"]
    same_queries = all(ids == reference for ids in query_ids.values())

    p00, p16 = phases["P00"], phases["P16"]
    empty_ok = p16["empty_rate"] <= p00["empty_rate"]
    recall_ok = (
        p16["micro_recall"] >= p00["micro_recall"] and p16["macro_recall"] >= p00["macro_recall"]
    )
    net_lost = sum(len(row["lost"]) - len(row["gained"]) for row in changes)
    gap_accounted = net_lost == p00["true_positives"] - p16["true_positives"]
    precision_bought = p16["micro_precision"] > p00["micro_precision"]
    if empty_ok and recall_ok:
        quality = MET
    elif empty_ok and gap_accounted and precision_bought:
        quality = MET_EXPLAINED
    else:
        quality = NOT_MET

    if latency is None:
        speed = NOT_MET
    else:
        speed = MET if latency["verdict"] == "acceptable" else NOT_MET

    return [
        {
            "id": 1,
            "label": "mêmes requêtes que P00 (égalité des ids)",
            "verdict": MET if same_queries else NOT_MET,
            "evidence": {"count": len(reference), "equal": same_queries},
        },
        {
            "id": 2,
            "label": "taux de decisions: [] et rappel meilleurs que P00, ou écart expliqué",
            "verdict": quality,
            "evidence": {
                "empty_rate_not_worse": empty_ok,
                "recall_not_worse": recall_ok,
                "gap_accounted_by_listed_true_positives": gap_accounted,
                "micro_precision_improved": precision_bought,
            },
        },
        {
            "id": 3,
            "label": "latence de prepare_context mesurée et acceptable",
            "verdict": speed,
            "evidence": {
                "measured": latency is not None,
                "latency_verdict": latency["verdict"] if latency else None,
            },
        },
    ]


def build_metrics(
    phases: dict[str, dict[str, Any]],
    p16: dict[str, Any],
    query_ids: list[str],
    latency: dict[str, Any] | None,
) -> dict[str, Any]:
    reports = {**phases, "P16": p16}
    aggregates = {
        phase: {key: reports[phase]["aggregate"].get(key) for key in AGGREGATE_KEYS}
        for phase in PHASES
    }
    ids = {"queries_file": query_ids, **{phase: _ids(reports[phase]) for phase in PHASES}}
    changes = recall_changes(phases["P00"], p16)
    return {
        "format": METRICS_FORMAT,
        "sources": {
            "P00": P00_RELATIVE_PATH,
            "P04": P04_RELATIVE_PATH,
            "P07": P07_RELATIVE_PATH,
            "P16": f"replay of {dr.REPORT_RELATIVE_PATH} selection",
            "queries": dr.QUERIES_RELATIVE_PATH,
            "corpus": dr.CORPUS_RELATIVE_PATH,
        },
        "phases": aggregates,
        "query_ids": {"count": len(query_ids), "ids": query_ids},
        "recall_gap_vs_p00": {
            "true_positives_p00": aggregates["P00"]["true_positives"],
            "true_positives_p16": aggregates["P16"]["true_positives"],
            "lost_total": sum(len(row["lost"]) for row in changes),
            "gained_total": sum(len(row["gained"]) for row in changes),
            "per_query": changes,
        },
        "lexical_ceiling": lexical_ceiling(phases["P07"]),
        "latency": latency,
        "criteria": _criteria(ids, aggregates, changes, latency),
    }


def _cell(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if key in ("empty_rate", "micro_recall", "macro_recall", "micro_precision"):
        return dr._pct(value)
    if key == "tokens_per_call_mean":
        return dr._num(value)
    return str(value)


_ROW_LABELS = (
    ("empty_rate", "Réponses `decisions: []`"),
    ("micro_recall", "Rappel micro"),
    ("macro_recall", "Rappel macro"),
    ("micro_precision", "Précision micro"),
    ("true_positives", "Vrais positifs"),
    ("retrieved_total", "Éléments retournés"),
    ("tokens_total", "Tokens injectés (total)"),
    ("tokens_per_call_mean", "Tokens par appel (moyenne)"),
)

_VERDICT_LABELS = {
    MET: "atteint",
    MET_EXPLAINED: "atteint, écart expliqué",
    NOT_MET: "non atteint",
}


def render_markdown(metrics: dict[str, Any]) -> str:
    phases = metrics["phases"]
    gap = metrics["recall_gap_vs_p00"]
    ceiling = metrics["lexical_ceiling"]
    latency = metrics["latency"]
    lines = [
        "# Évaluation finale de la roadmap vault — P16 (avant / après)",
        "",
        f"- P00 : `{P00_RELATIVE_PATH}` (baseline figée, bloc machine relu)",
        f"- P04 : `{P04_RELATIVE_PATH}` (recherche vault, bloc machine relu)",
        f"- P07 : `{P07_RELATIVE_PATH}` (sélection des décisions, bloc machine relu)",
        "- P16 : sélection actuelle rejouée par `scripts.dec_relevance_eval` sur "
        f"`{dr.QUERIES_RELATIVE_PATH}` et `{dr.CORPUS_RELATIVE_PATH}`",
        f"- Latence : `{LATENCY_RELATIVE_PATH}` (`{LATENCY_FORMAT}`)",
        "- Tokens : approximation `ceil(caractères / 4)` sur les corps retournés",
        "",
        "## Commande",
        "",
        "```",
        "uv run python -m scripts.vault_eval_p16 --root . --check   # exit 1 si périmé",
        "uv run python -m scripts.vault_eval_p16 --root . --apply   # (ré)écrit ce rapport",
        "```",
        "",
        "## Agrégat P00 / P04 / P07 / P16",
        "",
        "| Métrique | " + " | ".join(PHASES) + " |",
        "|---|" + "---|" * len(PHASES),
        f"| Requêtes | {' | '.join(_cell('queries', phases[p]['queries']) for p in PHASES)} |",
    ]
    for key, label in _ROW_LABELS:
        cells = " | ".join(_cell(key, phases[phase][key]) for phase in PHASES)
        lines.append(f"| {label} | {cells} |")
    lines += [
        "",
        "P04 mesure la recherche vault (`studio_vault_search`), P00, P07 et P16 la sélection",
        "des décisions de `studio_prepare_context` ; « — » signale une métrique absente.",
        "",
        "## Critères de P16",
        "",
        "| # | Critère | Verdict |",
        "|---|---|---|",
    ]
    for criterion in metrics["criteria"]:
        lines.append(
            f"| {criterion['id']} | {criterion['label']} "
            f"| {_VERDICT_LABELS[criterion['verdict']]} |"
        )
    p00, p16 = phases["P00"], phases["P16"]
    lines += [
        "",
        f"1. Les {metrics['query_ids']['count']} ids de requête de "
        f"`{dr.QUERIES_RELATIVE_PATH}` sont comparés, dans l'ordre, à ceux des blocs",
        "   P00, P04, P07 et du rejeu P16.",
        f"2. Réponses vides : {_cell('empty_rate', p00['empty_rate'])} en P00, "
        f"{_cell('empty_rate', p16['empty_rate'])} en P16 ; rappel micro "
        f"{_cell('micro_recall', p00['micro_recall'])} → "
        f"{_cell('micro_recall', p16['micro_recall'])}, précision micro "
        f"{_cell('micro_precision', p00['micro_precision'])} → "
        f"{_cell('micro_precision', p16['micro_precision'])}. Un rappel inférieur n'est",
        "   accepté que si les vrais positifs perdus et gagnés ci-dessous expliquent tout",
        "   l'écart et que la précision micro progresse.",
        "3. Voir la section latence.",
        "",
        "## Écart de rappel expliqué",
        "",
        f"Vrais positifs : {gap['true_positives_p00']} en P00, {gap['true_positives_p16']} "
        f"en P16 (perdus : {gap['lost_total']}, gagnés : {gap['gained_total']}).",
        "",
    ]
    if gap["per_query"]:
        lines += [
            "| id | objectif | perdus vs P00 | gagnés vs P00 |",
            "|---|---|---|---|",
        ]
        for row in gap["per_query"]:
            lines.append(
                f"| {row['id']} | {row['objective']} | {', '.join(row['lost']) or '—'} "
                f"| {', '.join(row['gained']) or '—'} |"
            )
    else:
        lines.append("Aucun vrai positif perdu ni gagné.")
    lines += [
        "",
        "### Plafond lexical (données P07)",
        "",
    ]
    if ceiling["per_query"]:
        lines += [
            "| id | attendues sans terme commun avec l'objectif |",
            "|---|---|",
        ]
        for row in ceiling["per_query"]:
            lines.append(f"| {row['id']} | {', '.join(row['unreachable'])} |")
        lines.append("")
    lines += [
        f"{ceiling['unreachable_total']} décisions attendues sur {ceiling['expected_total']} "
        "ne partagent aucun terme avec leur objectif : aucune règle lexicale ne peut les",
        f"atteindre, le rappel micro maximal est donc {dr._pct(ceiling['attainable_recall'])}.",
        "",
        "## Latence de `prepare_context`",
        "",
    ]
    if latency is None:
        lines += [
            "Latence non mesurée : `" + LATENCY_RELATIVE_PATH + "` est absent ou sans bloc",
            "machine. Le critère 3 n'est pas atteint.",
        ]
    else:
        lines += [
            "| p50 | p95 | max | seuil p95 | verdict |",
            "|---|---|---|---|---|",
            f"| {latency['p50_ms']} ms | {latency['p95_ms']} ms | {latency['max_ms']} ms "
            f"| {latency['threshold_p95_ms']} ms | {latency['verdict']} |",
        ]
    lines += [
        "",
        "## Métriques machine (vérifiées par `--check`)",
        "",
        METRICS_BEGIN,
        "```json",
        dr.canonical_json(metrics),
        "```",
        METRICS_END,
        "",
    ]
    return "\n".join(lines)


def _extract_metrics(report: str) -> str:
    if METRICS_BEGIN not in report or METRICS_END not in report:
        raise ValueError("metrics markers missing from the report")
    block = report.split(METRICS_BEGIN, 1)[1].split(METRICS_END, 1)[0].strip()
    if block.startswith("```json"):
        block = block[len("```json") :]
    if block.endswith("```"):
        block = block[: -len("```")]
    return block.strip()


def compute_metrics(root: Path) -> dict[str, Any]:
    phases = load_phases(root)
    p16 = asyncio.run(replay_p16(root, phases["P00"]))
    queries = dr.load_queries(root / dr.QUERIES_RELATIVE_PATH)
    query_ids = [query["id"] for query in queries["queries"]]
    latency = load_latency(root / LATENCY_RELATIVE_PATH)
    return build_metrics(phases, p16, query_ids, latency)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if the report is stale")
    mode.add_argument("--apply", action="store_true", help="(re)write the report")
    args = parser.parse_args(argv)

    metrics = compute_metrics(args.root)
    target = args.root / REPORT_RELATIVE_PATH
    if args.apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_markdown(metrics), encoding="utf-8", newline="\n")
        print(f"Wrote {REPORT_RELATIVE_PATH}.")
        return 0
    current = target.read_text(encoding="utf-8") if target.is_file() else ""
    try:
        published = _extract_metrics(current)
    except ValueError:
        print(f"{REPORT_RELATIVE_PATH} is missing or has no metrics block -- rerun with --apply.")
        return 1
    if published != dr.canonical_json(metrics):
        print(f"{REPORT_RELATIVE_PATH} is stale -- rerun with --apply.")
        return 1
    print(f"{REPORT_RELATIVE_PATH} is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
