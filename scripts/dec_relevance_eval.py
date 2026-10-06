"""P00 baseline — relevance of the decisions injected by `studio_prepare_context`.

Replays the *real* decision-selection logic
(`studio_api.services.project_context._select_decisions`) over a versioned
corpus, with no database and no server: the service boundary
`decisions.list_decisions` is replaced by the corpus, so the ranking, the
`superseded` filter, the `linked_to_task` shortcut, the `limit` and the text
budget are exactly the shipped ones. Reading only — the API code is not
modified.

Published to `docs/DEC_RELEVANCE_BASELINE_P00.md` (human report + a machine
JSON block used by `--check`).

Usage:
    uv run python -m scripts.dec_relevance_eval --root . --check   # exit 1 if stale
    uv run python -m scripts.dec_relevance_eval --root . --apply   # (re)write it
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import studio_api.services.decisions as decisions_service
from studio_api.services.project_context import _Budget, _select_decisions, query_terms

QUERIES_FORMAT = "studio.eval.dec-queries/v1"
CORPUS_FORMAT = "studio.eval.dec-corpus/v1"
METRICS_FORMAT = "studio.eval.dec-relevance/v1"

QUERIES_RELATIVE_PATH = "tests/eval/dec_queries.json"
CORPUS_RELATIVE_PATH = "tests/eval/dec_corpus.json"
REPORT_RELATIVE_PATH = "docs/DEC_RELEVANCE_BASELINE_P00.md"

METRICS_BEGIN = "<!-- DEC_RELEVANCE_METRICS_BEGIN -->"
METRICS_END = "<!-- DEC_RELEVANCE_METRICS_END -->"

DECIMALS = 4


@dataclass(frozen=True)
class DecisionRow:
    """The subset of `DecisionModel` the selection reads."""

    id: uuid.UUID
    readable_id: str
    title: str
    body: str
    status: str
    task_id: uuid.UUID | None
    created_at: datetime


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(path: Path) -> list[DecisionRow]:
    payload = _load_json(path)
    if payload.get("format") != CORPUS_FORMAT:
        raise ValueError(f"{path}: unexpected format {payload.get('format')!r}")
    rows: list[DecisionRow] = []
    for entry in payload["decisions"]:
        rows.append(
            DecisionRow(
                id=uuid.UUID(entry["id"]),
                readable_id=entry["readable_id"],
                title=entry["title"],
                body=entry["body"],
                status=entry["status"],
                task_id=uuid.UUID(entry["task_id"]) if entry["task_id"] else None,
                created_at=datetime.fromisoformat(entry["created_at"]),
            )
        )
    return rows


def load_queries(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if payload.get("format") != QUERIES_FORMAT:
        raise ValueError(f"{path}: unexpected format {payload.get('format')!r}")
    return payload


def _validate_labels(queries: dict[str, Any], corpus: list[DecisionRow]) -> None:
    by_id = {row.readable_id: row for row in corpus}
    for query in queries["queries"]:
        for readable_id in query["expected"]:
            row = by_id.get(readable_id)
            if row is None:
                raise ValueError(f"{query['id']}: expected {readable_id} is absent from the corpus")
            if row.status == "superseded":
                raise ValueError(
                    f"{query['id']}: expected {readable_id} is superseded and can never be selected"
                )


def _tokens(chars: int) -> int:
    """Approximate token count from characters (chars / 4, rounded up)."""
    return (chars + 3) // 4


async def _select_for_query(
    objective: str,
    corpus: list[DecisionRow],
    project_id: uuid.UUID,
    limit: int,
    max_chars: int,
) -> list[Any]:
    terms = query_terms(objective)
    budget = _Budget(max_chars)
    picked, _total = await _select_decisions(
        None,  # type: ignore[arg-type]  # list_decisions is replaced below
        None,  # type: ignore[arg-type]
        project_id,
        None,
        terms,
        limit,
        budget,
        {},
        {},
    )
    return picked


async def run_eval(
    queries: dict[str, Any],
    corpus: list[DecisionRow],
    *,
    limit: int,
    max_chars: int,
) -> dict[str, Any]:
    _validate_labels(queries, corpus)
    project_id = uuid.UUID(queries["project_id"])

    original = decisions_service.list_decisions

    async def _corpus_decisions(
        session: Any, principal: Any, project_id: Any = None
    ) -> list[DecisionRow]:
        return corpus

    decisions_service.list_decisions = _corpus_decisions  # type: ignore[assignment]
    try:
        per_query: list[dict[str, Any]] = []
        for query in queries["queries"]:
            picked = await _select_for_query(
                query["objective"], corpus, project_id, limit, max_chars
            )
            retrieved = [item.readable_id for item in picked]
            expected = list(query["expected"])
            hits = len(set(retrieved) & set(expected))
            chars = sum(len(item.body) for item in picked)
            per_query.append(
                {
                    "id": query["id"],
                    "objective": query["objective"],
                    "retrieved": retrieved,
                    "expected": expected,
                    "true_positives": hits,
                    "precision": round(hits / len(retrieved), DECIMALS) if retrieved else 0.0,
                    "recall": round(hits / len(expected), DECIMALS) if expected else 0.0,
                    "chars": chars,
                    "tokens": _tokens(chars),
                    "empty": not retrieved,
                }
            )
    finally:
        decisions_service.list_decisions = original  # type: ignore[assignment]

    retrieved_total = sum(len(row["retrieved"]) for row in per_query)
    expected_total = sum(len(row["expected"]) for row in per_query)
    true_positives = sum(row["true_positives"] for row in per_query)
    chars_total = sum(row["chars"] for row in per_query)
    tokens_total = sum(row["tokens"] for row in per_query)
    count = len(per_query)
    empty = sum(1 for row in per_query if row["empty"])
    macro_precision = sum(row["precision"] for row in per_query) / count if count else 0.0
    macro_recall = sum(row["recall"] for row in per_query) / count if count else 0.0

    return {
        "format": METRICS_FORMAT,
        "project_id": str(project_id),
        "corpus": {
            "path": CORPUS_RELATIVE_PATH,
            "format": CORPUS_FORMAT,
            "decisions": len(corpus),
        },
        "queries": {
            "path": QUERIES_RELATIVE_PATH,
            "format": QUERIES_FORMAT,
            "count": count,
            "limit": limit,
            "max_chars": max_chars,
        },
        "aggregate": {
            "queries": count,
            "empty_answers": empty,
            "empty_rate": round(empty / count, DECIMALS) if count else 0.0,
            "retrieved_total": retrieved_total,
            "expected_total": expected_total,
            "true_positives": true_positives,
            "micro_precision": round(true_positives / retrieved_total, DECIMALS)
            if retrieved_total
            else 0.0,
            "micro_recall": round(true_positives / expected_total, DECIMALS)
            if expected_total
            else 0.0,
            "macro_precision": round(macro_precision, DECIMALS),
            "macro_recall": round(macro_recall, DECIMALS),
            "chars_total": chars_total,
            "tokens_total": tokens_total,
            "tokens_per_call_mean": round(tokens_total / count, 2) if count else 0.0,
        },
        "per_query": per_query,
    }


def canonical_json(metrics: dict[str, Any]) -> str:
    return json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True)


def _extract_metrics(report: str) -> str:
    if METRICS_BEGIN not in report or METRICS_END not in report:
        raise ValueError("metrics markers missing from the report")
    block = report.split(METRICS_BEGIN, 1)[1].split(METRICS_END, 1)[0].strip()
    if block.startswith("```json"):
        block = block[len("```json") :]
    if block.endswith("```"):
        block = block[: -len("```")]
    return block.strip()


def _pct(value: float) -> str:
    return f"{value * 100:.1f} %"


def render_markdown(metrics: dict[str, Any]) -> str:
    agg = metrics["aggregate"]
    lines = [
        "# Baseline de pertinence des décisions — P00 (roadmap vault serveur)",
        "",
        f"- Projet : Studio OS (`{metrics['project_id']}`)",
        f"- Corpus : `{metrics['corpus']['path']}` "
        f"({metrics['corpus']['decisions']} décisions serveur, snapshot lecture seule)",
        f"- Requêtes : `{metrics['queries']['path']}` ({metrics['queries']['count']} objectifs)",
        "- Sélection : `studio_api.services.project_context._select_decisions` "
        f"(limit={metrics['queries']['limit']}, max_chars={metrics['queries']['max_chars']})",
        "- Tokens : approximation `ceil(caractères / 4)` sur les corps effectivement retournés",
        "",
        "## Méthodologie",
        "",
        "La logique de sélection réelle est importée depuis `services/api` et rejouée sans",
        "base de données : la frontière de service `decisions.list_decisions` est remplacée",
        "par le corpus versionné, si bien que le filtre `superseded`, l'ordre",
        "(`linked_to_task`, score, `accepted`, récence, `readable_id`), `limit` et le budget",
        "de texte sont ceux du serveur. Les requêtes n'ont pas de `task_id` : elles mesurent",
        "le recouvrement lexical pur, seule relation disponible pour un objectif libre.",
        "",
        "## Agrégat",
        "",
        "| Métrique | Valeur |",
        "|---|---|",
        f"| Requêtes | {agg['queries']} |",
        f"| Réponses `decisions: []` | {agg['empty_answers']} ({_pct(agg['empty_rate'])}) |",
        f"| Précision micro | {_pct(agg['micro_precision'])} |",
        f"| Rappel micro | {_pct(agg['micro_recall'])} |",
        f"| Précision macro | {_pct(agg['macro_precision'])} |",
        f"| Rappel macro | {_pct(agg['macro_recall'])} |",
        f"| Décisions retournées | {agg['retrieved_total']} "
        f"(attendues : {agg['expected_total']}, vrais positifs : {agg['true_positives']}) |",
        f"| Caractères injectés (total) | {agg['chars_total']} |",
        f"| Tokens injectés (total) | {agg['tokens_total']} |",
        f"| Tokens par appel (moyenne) | {agg['tokens_per_call_mean']} |",
        "",
        "## Détail par requête",
        "",
        "| id | objectif | retournées | attendues | précision | rappel | tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in metrics["per_query"]:
        retrieved = ", ".join(row["retrieved"]) or "—"
        expected = ", ".join(row["expected"])
        lines.append(
            f"| {row['id']} | {row['objective']} | {retrieved} | {expected} | "
            f"{_pct(row['precision'])} | {_pct(row['recall'])} | {row['tokens']} |"
        )
    lines += [
        "",
        "## Métriques machine (vérifiées par `--check`)",
        "",
        METRICS_BEGIN,
        "```json",
        canonical_json(metrics),
        "```",
        METRICS_END,
        "",
    ]
    return "\n".join(lines)


def render_report(metrics: dict[str, Any]) -> str:
    return render_markdown(metrics)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if the report is stale")
    mode.add_argument("--apply", action="store_true", help="(re)write the report")
    parser.add_argument("--stdout", action="store_true", help="also print the report")
    args = parser.parse_args(argv)

    queries = load_queries(args.root / QUERIES_RELATIVE_PATH)
    corpus = load_corpus(args.root / CORPUS_RELATIVE_PATH)
    selection = queries.get("selection", {})
    metrics = asyncio.run(
        run_eval(
            queries,
            corpus,
            limit=int(selection.get("limit", 5)),
            max_chars=int(selection.get("max_chars", 12000)),
        )
    )
    rendered = render_report(metrics)
    target = args.root / REPORT_RELATIVE_PATH
    if args.stdout:
        sys.stdout.write(rendered)
    if args.apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"Wrote {REPORT_RELATIVE_PATH}.")
        return 0
    current = target.read_text(encoding="utf-8") if target.is_file() else ""
    try:
        published = _extract_metrics(current)
    except ValueError:
        print(f"{REPORT_RELATIVE_PATH} is missing or has no metrics block -- rerun with --apply.")
        return 1
    if published != canonical_json(metrics):
        print(f"{REPORT_RELATIVE_PATH} is stale -- rerun with --apply.")
        return 1
    print(f"{REPORT_RELATIVE_PATH} is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
