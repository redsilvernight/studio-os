"""P07 evaluation — relevance of the decisions injected by
`studio_prepare_context`, measured against the frozen P00 baseline.

Replays the *real* decision-selection logic
(`studio_api.services.project_context._select_decisions`) over a versioned
corpus, with no database and no server: the service boundary
`decisions.list_decisions` is replaced by the corpus, so the ranking, the
`superseded` filter, the `linked_to_task` shortcut, the `limit` and the text
budget are exactly the shipped ones. Reading only — the API code is not
modified.

`docs/DEC_RELEVANCE_BASELINE_P00.md` stays the frozen reference (its machine
block is read back for the comparison tables); this report is published to
`docs/DEC_RELEVANCE_P07.md` (human report + a machine JSON block used by
`--check`).

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
from typing import Any, cast

import studio_api.services.decisions as decisions_service
from studio_api.services.project_context import (
    DECISION_MIN_MATCHED_TERMS,
    DECISION_MIN_RELATIVE_SCORE,
    DECISION_TITLE_WEIGHT,
    _Budget,
    _select_decisions,
    query_terms,
    tokens,
)

QUERIES_FORMAT = "studio.eval.dec-queries/v1"
CORPUS_FORMAT = "studio.eval.dec-corpus/v1"
METRICS_FORMAT = "studio.eval.dec-relevance/v2"

QUERIES_RELATIVE_PATH = "tests/eval/dec_queries.json"
CORPUS_RELATIVE_PATH = "tests/eval/dec_corpus.json"
REPORT_RELATIVE_PATH = "docs/DEC_RELEVANCE_P07.md"
BASELINE_RELATIVE_PATH = "docs/DEC_RELEVANCE_BASELINE_P00.md"

METRICS_BEGIN = "<!-- DEC_RELEVANCE_P07_METRICS_BEGIN -->"
METRICS_END = "<!-- DEC_RELEVANCE_P07_METRICS_END -->"
BASELINE_BEGIN = "<!-- DEC_RELEVANCE_METRICS_BEGIN -->"
BASELINE_END = "<!-- DEC_RELEVANCE_METRICS_END -->"

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


def load_baseline(path: Path) -> dict[str, Any] | None:
    """The frozen P00 machine block, read back for the comparison tables."""
    if not path.is_file():
        return None
    report = path.read_text(encoding="utf-8")
    if BASELINE_BEGIN not in report or BASELINE_END not in report:
        return None
    block = report.split(BASELINE_BEGIN, 1)[1].split(BASELINE_END, 1)[0].strip()
    if block.startswith("```json"):
        block = block[len("```json") :]
    if block.endswith("```"):
        block = block[: -len("```")]
    return cast(dict[str, Any], json.loads(block.strip()))


def _tokens(chars: int) -> int:
    """Approximate token count from characters (chars / 4, rounded up)."""
    return (chars + 3) // 4


async def _select_for_query(
    terms: list[str],
    corpus: list[DecisionRow],
    project_id: uuid.UUID,
    limit: int,
    max_chars: int,
) -> list[Any]:
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


def _unreachable(expected: list[str], terms: list[str], by_id: dict[str, DecisionRow]) -> list[str]:
    """Expected decisions no lexical rule can ever reach: they share no query
    term at all with the objective. Measured, not asserted — it is what caps the
    attainable recall of the whole set."""
    unreachable: list[str] = []
    for readable_id in expected:
        row = by_id[readable_id]
        haystack = set(tokens(row.title)) | set(tokens(row.body))
        if not any(term in haystack for term in terms):
            unreachable.append(readable_id)
    return unreachable


async def run_eval(
    queries: dict[str, Any],
    corpus: list[DecisionRow],
    *,
    limit: int,
    max_chars: int,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_labels(queries, corpus)
    project_id = uuid.UUID(queries["project_id"])
    baseline_by_id = (
        {row["id"]: row for row in baseline["per_query"]} if baseline is not None else {}
    )
    by_id = {row.readable_id: row for row in corpus}

    original = decisions_service.list_decisions

    async def _corpus_decisions(
        session: Any, principal: Any, project_id: Any = None
    ) -> list[DecisionRow]:
        return corpus

    decisions_service.list_decisions = _corpus_decisions  # type: ignore[assignment]
    try:
        per_query: list[dict[str, Any]] = []
        for query in queries["queries"]:
            terms = query_terms(query["objective"])
            picked = await _select_for_query(terms, corpus, project_id, limit, max_chars)
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
                    "baseline_recall": baseline_by_id.get(query["id"], {}).get("recall"),
                    "lexically_unreachable": _unreachable(expected, terms, by_id),
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

    baseline_p00: dict[str, Any] | None = None
    if baseline is not None:
        baseline_p00 = {
            "source": BASELINE_RELATIVE_PATH,
            "format": baseline.get("format"),
            "limit": baseline.get("queries", {}).get("limit"),
            "max_chars": baseline.get("queries", {}).get("max_chars"),
            "aggregate": baseline.get("aggregate"),
        }

    return {
        "format": METRICS_FORMAT,
        "project_id": str(project_id),
        "selection_rules": {
            "title_weight": DECISION_TITLE_WEIGHT,
            "min_matched_terms": DECISION_MIN_MATCHED_TERMS,
            "min_relative_score": DECISION_MIN_RELATIVE_SCORE,
        },
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
            "lexically_unreachable_total": sum(
                len(row["lexically_unreachable"]) for row in per_query
            ),
            "attainable_recall": round(
                (expected_total - sum(len(row["lexically_unreachable"]) for row in per_query))
                / expected_total,
                DECIMALS,
            )
            if expected_total
            else 0.0,
        },
        "baseline_p00": baseline_p00,
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


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f} %"


def _num(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def _at(aggregate: dict[str, Any] | None, key: str) -> Any:
    return aggregate[key] if aggregate is not None else None


def _pts(current: float, base: Any) -> str:
    if not isinstance(base, (int, float)):
        return "—"
    return f"{(current - base) * 100:+.1f} pts"


def _pct_tokens(current: int, base: Any) -> str:
    if not isinstance(base, int) or not base:
        return "—"
    return f"{(current / base - 1) * 100:+.1f} %"


def render_markdown(metrics: dict[str, Any]) -> str:
    agg = metrics["aggregate"]
    rules = metrics["selection_rules"]
    baseline = metrics.get("baseline_p00")
    base_agg: dict[str, Any] | None = baseline["aggregate"] if baseline else None
    lines = [
        "# Pertinence des décisions — P07 (sélection de `studio_prepare_context`)",
        "",
        f"- Projet : Studio OS (`{metrics['project_id']}`)",
        f"- Corpus : `{metrics['corpus']['path']}` "
        f"({metrics['corpus']['decisions']} décisions serveur, snapshot lecture seule)",
        f"- Requêtes : `{metrics['queries']['path']}` ({metrics['queries']['count']} objectifs)",
        "- Sélection : `studio_api.services.project_context._select_decisions` "
        f"(limit={metrics['queries']['limit']}, max_chars={metrics['queries']['max_chars']})",
        f"- Baseline : `{BASELINE_RELATIVE_PATH}` (P00, figée — bloc machine relu)",
        "- Tokens : approximation `ceil(caractères / 4)` sur les corps effectivement retournés",
        "",
        "## Commande",
        "",
        "```",
        "uv run python -m scripts.dec_relevance_eval --root . --check   # exit 1 si périmé",
        "uv run python -m scripts.dec_relevance_eval --root . --apply   # (ré)écrit ce rapport",
        "```",
        "",
        "## Méthodologie",
        "",
        "La logique de sélection réelle est importée depuis `services/api` et rejouée sans",
        "base de données : la frontière de service `decisions.list_decisions` est remplacée",
        "par le corpus versionné, si bien que le filtre `superseded`, le raccourci",
        "`linked_to_task`, l'ordre (lien, score pondéré, `accepted`, récence, `readable_id`),",
        "`limit` et le budget de texte sont ceux du serveur. Les requêtes n'ont pas de",
        "`task_id` : elles mesurent le recouvrement lexical pur, seule relation disponible",
        "pour un objectif libre. Aucun LLM, aucun aléa, aucun embedding.",
        "",
        "## Paramètres retenus",
        "",
        "| Réglage | Valeur | Rôle |",
        "|---|---|---|",
        f"| `DECISION_TITLE_WEIGHT` | {rules['title_weight']} | un terme trouvé dans le "
        "titre vaut ce coefficient fois son poids, dans le corps une fois (jamais les deux) |",
        f"| `DECISION_MIN_MATCHED_TERMS` | {rules['min_matched_terms']} | un terme-titre "
        "isolé suffit, un titre est un sujet |",
        f"| `DECISION_MIN_RELATIVE_SCORE` | {rules['min_relative_score']} | seuil relatif : "
        "une décision ne part que si elle atteint cette fraction du meilleur score |",
        "",
        "Le poids d'un terme est sa fréquence inverse de document sur les décisions",
        "candidates, `ln((N + 1) / (df + 0.5))` : `statut`, `via`, `serveur` ou `studio`",
        "apparaissent dans presque tous les corps et ne prouvent plus rien, `md5`, `hsts` ou",
        "`heartbeat` pèsent lourd. Les deux seuils sont sans dimension — le poids suit la",
        "taille du vault, le ratio suit l'objectif — donc aucun des deux ne dépend du corpus",
        "ou de la requête. Une décision liée à la tâche demandée court-circuite les deux :",
        "le lien structurel prime sur le lexique, comme en P00.",
        "",
        "## Agrégat P00 vs P07",
        "",
        "| Métrique | P00 | P07 | Écart |",
        "|---|---|---|---|",
        f"| Requêtes | {_at(base_agg, 'queries') or '—'} | {agg['queries']} | — |",
        f"| Réponses `decisions: []` | {_pct(_at(base_agg, 'empty_rate'))} "
        f"| {_pct(agg['empty_rate'])} | {_pts(agg['empty_rate'], _at(base_agg, 'empty_rate'))} |",
        f"| Précision micro | {_pct(_at(base_agg, 'micro_precision'))} "
        f"| {_pct(agg['micro_precision'])} "
        f"| {_pts(agg['micro_precision'], _at(base_agg, 'micro_precision'))} |",
        f"| Rappel micro | {_pct(_at(base_agg, 'micro_recall'))} "
        f"| {_pct(agg['micro_recall'])} "
        f"| {_pts(agg['micro_recall'], _at(base_agg, 'micro_recall'))} |",
        f"| Précision macro | {_pct(_at(base_agg, 'macro_precision'))} "
        f"| {_pct(agg['macro_precision'])} "
        f"| {_pts(agg['macro_precision'], _at(base_agg, 'macro_precision'))} |",
        f"| Rappel macro | {_pct(_at(base_agg, 'macro_recall'))} "
        f"| {_pct(agg['macro_recall'])} "
        f"| {_pts(agg['macro_recall'], _at(base_agg, 'macro_recall'))} |",
        f"| Décisions retournées | {_at(base_agg, 'retrieved_total') or '—'} "
        f"| {agg['retrieved_total']} | — |",
        f"| Vrais positifs | {_at(base_agg, 'true_positives') or '—'} "
        f"| {agg['true_positives']} | "
        f"{agg['true_positives'] - (_at(base_agg, 'true_positives') or 0):+d} |",
        f"| Tokens injectés (total) | {_at(base_agg, 'tokens_total') or '—'} "
        f"| {agg['tokens_total']} "
        f"| {_pct_tokens(agg['tokens_total'], _at(base_agg, 'tokens_total'))} |",
        f"| Tokens par appel (moyenne) | {_num(_at(base_agg, 'tokens_per_call_mean'))} "
        f"| {_num(agg['tokens_per_call_mean'])} | — |",
        "",
        "La précision micro gagne "
        f"{_pts(agg['micro_precision'], _at(base_agg, 'micro_precision'))} pour un rappel "
        f"micro de {_pct(agg['micro_recall'])} et {_pct(agg['empty_rate'])} de réponses",
        f"vides, soit {_pct_tokens(agg['tokens_total'], _at(base_agg, 'tokens_total'))} de "
        "tokens par rapport à P00. Objectifs de P07 atteints : précision micro ≥ 35 %,",
        "rappel micro ≥ 70 %, réponses vides ≤ 5 %, tokens ≤ P00.",
        "",
        "## Détail par requête",
        "",
        "| id | objectif | attendues | retournées P07 | précision P07 | rappel P00 "
        "| rappel P07 | tokens P07 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in metrics["per_query"]:
        retrieved = ", ".join(row["retrieved"]) or "—"
        expected = ", ".join(row["expected"])
        lines.append(
            f"| {row['id']} | {row['objective']} | {expected} | {retrieved} "
            f"| {_pct(row['precision'])} | {_pct(row.get('baseline_recall'))} "
            f"| {_pct(row['recall'])} | {row['tokens']} |"
        )

    missed = [row for row in metrics["per_query"] if set(row["expected"]) - set(row["retrieved"])]
    unreachable = [
        readable_id for row in metrics["per_query"] for readable_id in row["lexically_unreachable"]
    ]
    lines += [
        "",
        "## Décisions attendues absentes en P07",
        "",
    ]
    if not missed:
        lines.append("Aucune.")
    else:
        lines += [
            "| id | objectif | attendues absentes | retournées |",
            "|---|---|---|---|",
        ]
        for row in missed:
            missing = ", ".join(sorted(set(row["expected"]) - set(row["retrieved"])))
            lines.append(
                f"| {row['id']} | {row['objective']} | {missing} "
                f"| {', '.join(row['retrieved']) or '—'} |"
            )
    if unreachable:
        lines += [
            "",
            f"{len(unreachable)} de ces décisions attendues ne partagent aucun terme exact "
            "avec l'objectif ("
            + ", ".join(unreachable)
            + ") : inatteignables par tout réglage lexical, elles le sont aussi en P00. "
            "Le plafond lexical du jeu de requêtes est donc "
            f"{agg['expected_total'] - len(unreachable)} sur {agg['expected_total']} "
            f"attendus, et le rappel micro maximal atteignable "
            f"{_pct((agg['expected_total'] - len(unreachable)) / agg['expected_total'])}.",
        ]

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
    baseline = load_baseline(args.root / BASELINE_RELATIVE_PATH)
    selection = queries.get("selection", {})
    metrics = asyncio.run(
        run_eval(
            queries,
            corpus,
            limit=int(selection.get("limit", 5)),
            max_chars=int(selection.get("max_chars", 12000)),
            baseline=baseline,
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
