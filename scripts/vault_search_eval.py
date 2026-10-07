"""P04 evaluation — relevance of `studio_api.services.vault.search_notes`.

Loads `tests/eval/dec_corpus.json` as decision notes of a throwaway project on a
real PostgreSQL (`STUDIO_TEST_DATABASE_URL`), replays every query of
`tests/eval/dec_queries.json` through the *real* ranked search service
(`services/api/src/studio_api/services/vault.py`, read-only) and compares the
micro/macro recall and token budget against the P00 baseline of
`docs/DEC_RELEVANCE_BASELINE_P00.md`. Everything it created is removed at the
end; the ranking code is never modified.

Published to `docs/VAULT_SEARCH_EVAL_P04.md` (human report + a machine JSON
block used by `--check`).

Usage:
    uv run python -m scripts.vault_search_eval --root . --check   # exit 1 if stale
    uv run python -m scripts.vault_search_eval --root . --apply   # (re)write it
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.user import UserModel
from studio_api.db.models.vault import VaultNoteModel
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services import vault as vault_service
from studio_api.services.authz import load_principal
from studio_contracts.vault import VaultNoteStatus, VaultNoteType, content_hash

QUERIES_FORMAT = "studio.eval.dec-queries/v1"
CORPUS_FORMAT = "studio.eval.dec-corpus/v1"
METRICS_FORMAT = "studio.eval.vault-search/v1"

QUERIES_RELATIVE_PATH = "tests/eval/dec_queries.json"
CORPUS_RELATIVE_PATH = "tests/eval/dec_corpus.json"
REPORT_RELATIVE_PATH = "docs/VAULT_SEARCH_EVAL_P04.md"
BASELINE_RELATIVE_PATH = "docs/DEC_RELEVANCE_BASELINE_P00.md"

METRICS_BEGIN = "<!-- VAULT_SEARCH_METRICS_BEGIN -->"
METRICS_END = "<!-- VAULT_SEARCH_METRICS_END -->"
BASELINE_BEGIN = "<!-- DEC_RELEVANCE_METRICS_BEGIN -->"
BASELINE_END = "<!-- DEC_RELEVANCE_METRICS_END -->"

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test"

DECIMALS = 4

_STATUS_MAP = {
    "accepted": VaultNoteStatus.VALIDATED.value,
    "validated": VaultNoteStatus.VALIDATED.value,
    "proposed": VaultNoteStatus.PROPOSED.value,
    "draft": VaultNoteStatus.DRAFT.value,
    "superseded": VaultNoteStatus.SUPERSEDED.value,
    "archived": VaultNoteStatus.ARCHIVED.value,
}


@dataclass(frozen=True)
class CorpusNote:
    """The subset of a decision the vault note needs."""

    id: uuid.UUID
    readable_id: str
    title: str
    body: str
    status: str
    task_id: uuid.UUID | None


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def load_corpus(path: Path) -> list[CorpusNote]:
    payload = _load_json(path)
    if payload.get("format") != CORPUS_FORMAT:
        raise ValueError(f"{path}: unexpected format {payload.get('format')!r}")
    rows: list[CorpusNote] = []
    for entry in payload["decisions"]:
        rows.append(
            CorpusNote(
                id=uuid.UUID(entry["id"]),
                readable_id=entry["readable_id"],
                title=entry["title"],
                body=entry["body"],
                status=entry["status"],
                task_id=uuid.UUID(entry["task_id"]) if entry["task_id"] else None,
            )
        )
    return rows


def load_queries(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if payload.get("format") != QUERIES_FORMAT:
        raise ValueError(f"{path}: unexpected format {payload.get('format')!r}")
    return payload


def load_baseline(path: Path) -> dict[str, Any] | None:
    """The P00 machine block, embedded in the report for the comparison table."""
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


def _validate_labels(queries: dict[str, Any], corpus: list[CorpusNote]) -> None:
    by_id = {row.readable_id: row for row in corpus}
    for query in queries["queries"]:
        for readable_id in query["expected"]:
            row = by_id.get(readable_id)
            if row is None:
                raise ValueError(f"{query['id']}: expected {readable_id} is absent from the corpus")
            if _STATUS_MAP.get(row.status) == VaultNoteStatus.SUPERSEDED.value:
                raise ValueError(
                    f"{query['id']}: expected {readable_id} is superseded and can never be selected"
                )


def _tokens(chars: int) -> int:
    """Approximate token count from characters (chars / 4, rounded up)."""
    return (chars + 3) // 4


def _note_status(status: str) -> VaultNoteStatus:
    return VaultNoteStatus(_STATUS_MAP.get(status, status))


def _note_anchors(note: CorpusNote) -> list[str]:
    return [f"task:{note.task_id}"] if note.task_id is not None else []


def _note_fields(note: CorpusNote) -> dict[str, Any]:
    status = _note_status(note.status)
    anchors = _note_anchors(note)
    return {
        "id": note.id,
        "scope": "project",
        "slug": note.readable_id.lower(),
        "readable_id": note.readable_id,
        "note_type": "decision",
        "title": note.title,
        "summary": "",
        "body": note.body,
        "status": status.value,
        "tags": [],
        "anchors": anchors,
        "content_hash": content_hash(
            title=note.title,
            summary="",
            body=note.body,
            status=status,
            tags=[],
            links=[],
            anchors=anchors,
        ),
        "author_type": "system",
    }


async def _purge_corpus_notes(session: AsyncSession, corpus: list[CorpusNote]) -> None:
    """Remove notes a previous interrupted run left behind: `readable_id` is
    unique across the whole database, so a stale row would make the insert fail."""
    await session.execute(
        delete(VaultNoteModel).where(
            VaultNoteModel.readable_id.in_([note.readable_id for note in corpus])
        )
    )
    await session.commit()


async def _insert_notes(
    session: AsyncSession, corpus: list[CorpusNote], project_id: uuid.UUID, author_id: uuid.UUID
) -> None:
    for note in corpus:
        fields = _note_fields(note)
        session.add(
            VaultNoteModel(
                **fields,
                project_id=project_id,
                author_id=author_id,
            )
        )
    await session.commit()


async def _cleanup(
    session: AsyncSession,
    project_id: uuid.UUID,
    machine_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    await session.rollback()
    await session.execute(delete(VaultNoteModel).where(VaultNoteModel.project_id == project_id))
    await session.execute(
        delete(ProjectMembershipModel).where(ProjectMembershipModel.project_id == project_id)
    )
    await session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
    await session.execute(delete(MachineModel).where(MachineModel.id == machine_id))
    await session.execute(delete(UserModel).where(UserModel.id == user_id))
    await session.commit()


async def _search_query(
    session: AsyncSession,
    principal: Any,
    project_id: uuid.UUID,
    query: dict[str, Any],
    *,
    limit: int,
    max_chars: int,
) -> dict[str, Any]:
    task_raw = query.get("task_id")
    task_id = uuid.UUID(task_raw) if task_raw else None
    result = await vault_service.search_notes(
        session,
        principal,
        q=query["objective"],
        scope=None,
        project_id=project_id,
        note_types=[VaultNoteType.DECISION],
        statuses=[],
        include_superseded=False,
        paths=[],
        task_id=task_id,
        limit=limit,
        max_chars=max_chars,
    )
    hits = result.items
    retrieved = [hit.note.readable_id for hit in hits if hit.note.readable_id is not None]
    expected = list(query["expected"])
    hits_found = len(set(retrieved) & set(expected))
    chars = sum(len(hit.note.title) + len(hit.note.summary) + len(hit.snippet) for hit in hits)
    return {
        "id": query["id"],
        "objective": query["objective"],
        "task_id": str(task_id) if task_id else None,
        "retrieved": retrieved,
        "expected": expected,
        "true_positives": hits_found,
        "precision": round(hits_found / len(retrieved), DECIMALS) if retrieved else 0.0,
        "recall": round(hits_found / len(expected), DECIMALS) if expected else 0.0,
        "chars": chars,
        "tokens": _tokens(chars),
        "empty": not retrieved,
    }


async def _run_db_eval(
    queries: dict[str, Any],
    corpus: list[CorpusNote],
    baseline: dict[str, Any] | None,
    *,
    limit: int,
    max_chars: int,
    database_url: str,
) -> dict[str, Any]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    machine_id = uuid.uuid4()
    user_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            await _purge_corpus_notes(session, corpus)
            user = await provisioning_service.create_user(
                session,
                "Vault Search Eval",
                f"vault-search-eval-{uuid.uuid4().hex}@example.test",
                "admin",
            )
            machine, _token = await provisioning_service.create_machine(
                session, user.id, "vault-search-eval"
            )
            project = await projects_service.create_project(
                session,
                f"vault-search-eval-{uuid.uuid4().hex[:8]}",
                "Vault Search Eval",
                None,
                creator=user,
            )
            user_id = user.id
            machine_id = machine.id
            project_id = project.id
            principal = await load_principal(session, machine)
            await _insert_notes(session, corpus, project_id, user_id)
            try:
                per_query = [
                    await _search_query(
                        session,
                        principal,
                        project_id,
                        query,
                        limit=limit,
                        max_chars=max_chars,
                    )
                    for query in queries["queries"]
                ]
            finally:
                await _cleanup(session, project_id, machine_id, user_id)
    finally:
        await engine.dispose()

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
        baseline_by_id = {row["id"]: row for row in baseline["per_query"]}
        for row in per_query:
            p00 = baseline_by_id.get(row["id"])
            row["baseline_recall"] = p00["recall"] if p00 else None
        baseline_p00 = {
            "source": BASELINE_RELATIVE_PATH,
            "format": baseline.get("format"),
            "limit": baseline.get("queries", {}).get("limit"),
            "max_chars": baseline.get("queries", {}).get("max_chars"),
            "aggregate": baseline.get("aggregate"),
        }

    return {
        "format": METRICS_FORMAT,
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
            "tokens_per_result_mean": round(tokens_total / retrieved_total, 2)
            if retrieved_total
            else 0.0,
        },
        "baseline_p00": baseline_p00,
        "per_query": per_query,
    }


def run_eval(
    queries: dict[str, Any],
    corpus: list[CorpusNote],
    baseline: dict[str, Any] | None,
    *,
    limit: int,
    max_chars: int,
    database_url: str,
) -> dict[str, Any]:
    _validate_labels(queries, corpus)
    return asyncio.run(
        _run_db_eval(
            queries,
            corpus,
            baseline,
            limit=limit,
            max_chars=max_chars,
            database_url=database_url,
        )
    )


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


def render_markdown(metrics: dict[str, Any]) -> str:
    agg = metrics["aggregate"]
    baseline = metrics.get("baseline_p00")
    base_agg = baseline["aggregate"] if baseline else None

    lines = [
        "# Évaluation de la recherche du vault — P04 (roadmap vault serveur)",
        "",
        "- Projet temporaire : évaluation sur PostgreSQL "
        f"(`{CORPUS_RELATIVE_PATH}` chargé en notes)",
        f"- Corpus : `{metrics['corpus']['path']}` ({metrics['corpus']['decisions']} décisions)",
        f"- Requêtes : `{metrics['queries']['path']}` ({metrics['queries']['count']} objectifs)",
        "- Recherche : `studio_api.services.vault.search_notes` "
        f"(limit={metrics['queries']['limit']}, max_chars={metrics['queries']['max_chars']})",
        "- Tokens : approximation `ceil(caractères / 4)` sur `titre + résumé + extrait` "
        "effectivement retournés (la recherche ne renvoie jamais le corps)",
        "",
        "## Méthodologie",
        "",
        "Le corpus versionné est inséré comme notes `decision` d'un projet jetable sur un",
        "vrai PostgreSQL, puis chaque objectif est rejoué via le service de recherche réel",
        "(classement par ancre, lien puis lexical — couverture des termes, titre ×3, "
        "`ts_rank_cd` en départage). Le service et le",
        "classement ne sont pas modifiés en lecture ; le projet et ses notes sont supprimés",
        "en fin d'exécution. Les requêtes n'ont pas de `task_id` : elles mesurent le",
        "recouvrement lexical, seule relation disponible pour un objectif libre.",
        "",
        "## Agrégat P00 vs P04",
        "",
        "| Métrique | P00 | P04 |",
        "|---|---|---|",
        f"| Requêtes | {base_agg['queries'] if base_agg else '—'} | {agg['queries']} |",
        "| Réponses vides | "
        f"{_pct(base_agg['empty_rate']) if base_agg else '—'} | {_pct(agg['empty_rate'])} |",
        f"| Précision micro | {_pct(base_agg['micro_precision']) if base_agg else '—'} "
        f"| {_pct(agg['micro_precision'])} |",
        f"| Rappel micro | {_pct(base_agg['micro_recall']) if base_agg else '—'} "
        f"| {_pct(agg['micro_recall'])} |",
        f"| Précision macro | {_pct(base_agg['macro_precision']) if base_agg else '—'} "
        f"| {_pct(agg['macro_precision'])} |",
        f"| Rappel macro | {_pct(base_agg['macro_recall']) if base_agg else '—'} "
        f"| {_pct(agg['macro_recall'])} |",
        "| Notes retournées | "
        f"{base_agg['retrieved_total'] if base_agg else '—'} | {agg['retrieved_total']} |",
        f"| Vrais positifs | {base_agg['true_positives'] if base_agg else '—'} "
        f"| {agg['true_positives']} |",
        "| Tokens par appel (moyenne) | "
        f"{_num(base_agg['tokens_per_call_mean']) if base_agg else '—'} "
        f"| {_num(agg['tokens_per_call_mean'])} |",
        f"| Tokens par résultat (moyenne) | — | {_num(agg['tokens_per_result_mean'])} |",
        "",
        f"Le rappel micro P04 est de {_pct(agg['micro_recall'])} "
        f"pour un budget de {_num(agg['tokens_per_call_mean'])} tokens par appel, "
        "contre "
        f"{_pct(base_agg['micro_recall']) if base_agg else '—'} / "
        f"{_num(base_agg['tokens_per_call_mean']) if base_agg else '—'} en P00.",
        "",
        "## Détail par requête",
        "",
        "| id | objectif | attendues | rappel P00 | retournées P04 | rappel P04 | tokens P04 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in metrics["per_query"]:
        expected = ", ".join(row["expected"])
        retrieved = ", ".join(row["retrieved"]) or "—"
        lines.append(
            f"| {row['id']} | {row['objective']} | {expected} | "
            f"{_pct(row.get('baseline_recall'))} | {retrieved} | "
            f"{_pct(row['recall'])} | {row['tokens']} |"
        )

    missed = [row for row in metrics["per_query"] if set(row["expected"]) - set(row["retrieved"])]
    lines += [
        "",
        "## Requêtes manquées en P04",
        "",
    ]
    if not missed:
        lines.append("Aucune : chaque décision attendue figure dans les 5 premiers résultats.")
    else:
        lines.append("| id | objectif | attendues absentes | retournées |")
        lines.append("|---|---|---|---|")
        for row in missed:
            missing = ", ".join(sorted(set(row["expected"]) - set(row["retrieved"])))
            lines.append(
                f"| {row['id']} | {row['objective']} | {missing} "
                f"| {', '.join(row['retrieved']) or '—'} |"
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
    baseline = load_baseline(args.root / BASELINE_RELATIVE_PATH)
    selection = queries.get("selection", {})
    database_url = os.environ.get("STUDIO_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
    metrics = run_eval(
        queries,
        corpus,
        baseline,
        limit=int(selection.get("limit", 5)),
        max_chars=int(selection.get("max_chars", 12000)),
        database_url=database_url,
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
