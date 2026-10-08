"""P16 evaluation — in-process latency of `prepare_project_context`.

Loads `tests/eval/dec_corpus.json` both as server decisions and as vault
decision notes of a throwaway project on a real PostgreSQL
(`STUDIO_TEST_DATABASE_URL`), then times every query of
`tests/eval/dec_queries.json` through the *real* service
(`studio_api.services.project_context.prepare_project_context`): warm-up passes
first, then several `time.perf_counter` samples per query. Everything it
created is removed at the end.

Published to `docs/CONTEXT_LATENCY_P16.md` (human report + a machine JSON block).
Timings are not deterministic, so `--check` validates only the structure of the
published block and its set of query ids; it never touches the database.

Usage:
    uv run python -m scripts.context_latency_eval --root . --check   # exit 1 if invalid
    uv run python -m scripts.context_latency_eval --root . --apply   # measure and (re)write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import sys
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.user import UserModel
from studio_api.db.models.vault import VaultNoteModel
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import Principal, load_principal
from studio_api.services.project_context import prepare_project_context

from scripts.vault_search_eval import (
    CORPUS_RELATIVE_PATH,
    QUERIES_RELATIVE_PATH,
    CorpusNote,
    _note_fields,
    load_corpus,
    load_queries,
)

METRICS_FORMAT = "studio.eval.context-latency/v1"
REPORT_RELATIVE_PATH = "docs/CONTEXT_LATENCY_P16.md"
COMMAND = "uv run python -m scripts.context_latency_eval --root . --apply"

METRICS_BEGIN = "<!-- CONTEXT_LATENCY_METRICS_BEGIN -->"
METRICS_END = "<!-- CONTEXT_LATENCY_METRICS_END -->"

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test"

WARMUP_PASSES = 2
SAMPLES_PER_QUERY = 10
THRESHOLD_P95_MS = 250.0
VERDICT_ACCEPTABLE = "acceptable"
VERDICT_TOO_SLOW = "too_slow"
STAT_KEYS = ("p50_ms", "p95_ms", "max_ms", "mean_ms")
DECIMALS = 2


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (`numpy.percentile` default), `q` in 0..100."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    if not 0.0 <= q <= 100.0:
        raise ValueError(f"percentile rank {q} outside 0..100")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(samples_ms: Sequence[float]) -> dict[str, float]:
    return {
        "p50_ms": round(percentile(samples_ms, 50.0), DECIMALS),
        "p95_ms": round(percentile(samples_ms, 95.0), DECIMALS),
        "max_ms": round(max(samples_ms), DECIMALS),
        "mean_ms": round(sum(samples_ms) / len(samples_ms), DECIMALS),
    }


def verdict(p95_ms: float, threshold_ms: float = THRESHOLD_P95_MS) -> str:
    return VERDICT_ACCEPTABLE if p95_ms <= threshold_ms else VERDICT_TOO_SLOW


def build_metrics(
    samples: dict[str, list[float]],
    *,
    environment: dict[str, str],
    parameters: dict[str, int],
) -> dict[str, Any]:
    all_samples = [value for values in samples.values() for value in values]
    global_stats = summarize(all_samples)
    return {
        "format": METRICS_FORMAT,
        "command": COMMAND,
        "environment": environment,
        "parameters": parameters,
        "threshold_p95_ms": THRESHOLD_P95_MS,
        "global": global_stats,
        "verdict": verdict(global_stats["p95_ms"]),
        "queries": list(samples),
        "per_query": [
            {"id": query_id, **summarize(values)} for query_id, values in samples.items()
        ],
    }


def _decision_row(note: CorpusNote, project_id: uuid.UUID, user_id: uuid.UUID) -> DecisionModel:
    return DecisionModel(
        id=note.id,
        readable_id=note.readable_id,
        project_id=project_id,
        task_id=None,
        title=note.title,
        body=note.body,
        status=note.status,
        proposed_by_type="user",
        proposed_by_id=user_id,
    )


async def _purge_corpus(session: AsyncSession, corpus: list[CorpusNote]) -> None:
    readable_ids = [note.readable_id for note in corpus]
    await session.execute(
        delete(VaultNoteModel).where(VaultNoteModel.readable_id.in_(readable_ids))
    )
    await session.execute(delete(DecisionModel).where(DecisionModel.readable_id.in_(readable_ids)))
    await session.commit()


async def _insert_corpus(
    session: AsyncSession, corpus: list[CorpusNote], project_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    for note in corpus:
        session.add(_decision_row(note, project_id, user_id))
        session.add(VaultNoteModel(**_note_fields(note), project_id=project_id, author_id=user_id))
    await session.commit()


async def _cleanup(
    session: AsyncSession,
    project_id: uuid.UUID,
    machine_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    await session.rollback()
    await session.execute(delete(VaultNoteModel).where(VaultNoteModel.project_id == project_id))
    await session.execute(delete(DecisionModel).where(DecisionModel.project_id == project_id))
    await session.execute(
        delete(ProjectMembershipModel).where(ProjectMembershipModel.project_id == project_id)
    )
    await session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
    await session.execute(delete(MachineModel).where(MachineModel.id == machine_id))
    await session.execute(delete(UserModel).where(UserModel.id == user_id))
    await session.commit()


async def _time_call(
    session_factory: async_sessionmaker[AsyncSession],
    principal: Principal,
    project_id: uuid.UUID,
    objective: str,
    *,
    limit: int,
    max_chars: int,
) -> float:
    async with session_factory() as session:
        started = time.perf_counter()
        await prepare_project_context(
            session, principal, project_id, objective, limit=limit, max_chars=max_chars
        )
        return (time.perf_counter() - started) * 1000.0


async def _measure(
    session_factory: async_sessionmaker[AsyncSession],
    principal: Principal,
    project_id: uuid.UUID,
    queries: list[dict[str, Any]],
    *,
    limit: int,
    max_chars: int,
    warmup_passes: int,
    samples_per_query: int,
) -> dict[str, list[float]]:
    for _ in range(warmup_passes):
        for query in queries:
            await _time_call(
                session_factory,
                principal,
                project_id,
                query["objective"],
                limit=limit,
                max_chars=max_chars,
            )
    samples: dict[str, list[float]] = {}
    for query in queries:
        samples[query["id"]] = [
            await _time_call(
                session_factory,
                principal,
                project_id,
                query["objective"],
                limit=limit,
                max_chars=max_chars,
            )
            for _ in range(samples_per_query)
        ]
    return samples


async def _run_db_eval(
    queries: dict[str, Any],
    corpus: list[CorpusNote],
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
            server_version = (await session.execute(text("SHOW server_version"))).scalar_one()
            await _purge_corpus(session, corpus)
            user = await provisioning_service.create_user(
                session,
                "Context Latency Eval",
                f"context-latency-eval-{uuid.uuid4().hex}@example.test",
                "admin",
            )
            machine, _token = await provisioning_service.create_machine(
                session, user.id, "context-latency-eval"
            )
            project = await projects_service.create_project(
                session,
                f"context-latency-eval-{uuid.uuid4().hex[:8]}",
                "Context Latency Eval",
                None,
                creator=user,
            )
            user_id = user.id
            machine_id = machine.id
            project_id = project.id
            principal = await load_principal(session, machine)
            try:
                await _insert_corpus(session, corpus, project_id, user_id)
                samples = await _measure(
                    session_factory,
                    principal,
                    project_id,
                    list(queries["queries"]),
                    limit=limit,
                    max_chars=max_chars,
                    warmup_passes=WARMUP_PASSES,
                    samples_per_query=SAMPLES_PER_QUERY,
                )
            finally:
                await _cleanup(session, project_id, machine_id, user_id)
    finally:
        await engine.dispose()

    environment = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "postgresql": str(server_version),
    }
    parameters = {
        "limit": limit,
        "max_chars": max_chars,
        "warmup_passes": WARMUP_PASSES,
        "samples_per_query": SAMPLES_PER_QUERY,
        "decisions": len(corpus),
        "vault_notes": len(corpus),
    }
    return build_metrics(samples, environment=environment, parameters=parameters)


def run_eval(
    queries: dict[str, Any],
    corpus: list[CorpusNote],
    *,
    limit: int,
    max_chars: int,
    database_url: str,
) -> dict[str, Any]:
    return asyncio.run(
        _run_db_eval(queries, corpus, limit=limit, max_chars=max_chars, database_url=database_url)
    )


def canonical_json(metrics: dict[str, Any]) -> str:
    return json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True)


def extract_metrics(report: str) -> dict[str, Any]:
    if METRICS_BEGIN not in report or METRICS_END not in report:
        raise ValueError("metrics markers missing from the report")
    block = report.split(METRICS_BEGIN, 1)[1].split(METRICS_END, 1)[0].strip()
    if block.startswith("```json"):
        block = block[len("```json") :]
    if block.endswith("```"):
        block = block[: -len("```")]
    return cast(dict[str, Any], json.loads(block.strip()))


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _stats_errors(where: str, stats: object) -> list[str]:
    if not isinstance(stats, dict):
        return [f"{where}: not an object"]
    return [
        f"{where}.{key}: missing or not a number"
        for key in STAT_KEYS
        if not _is_number(stats.get(key))
    ]


def validate_metrics(metrics: dict[str, Any], expected_ids: list[str]) -> list[str]:
    errors: list[str] = []
    if metrics.get("format") != METRICS_FORMAT:
        errors.append(f"format: expected {METRICS_FORMAT!r}, got {metrics.get('format')!r}")
    errors += _stats_errors("global", metrics.get("global"))
    if not _is_number(metrics.get("threshold_p95_ms")):
        errors.append("threshold_p95_ms: missing or not a number")
    if metrics.get("verdict") not in (VERDICT_ACCEPTABLE, VERDICT_TOO_SLOW):
        errors.append(f"verdict: unexpected value {metrics.get('verdict')!r}")
    queries = metrics.get("queries")
    if not isinstance(queries, list) or set(queries) != set(expected_ids):
        errors.append("queries: ids differ from the query set")
    per_query = metrics.get("per_query")
    if not isinstance(per_query, list):
        errors.append("per_query: not a list")
    else:
        if {row.get("id") for row in per_query if isinstance(row, dict)} != set(expected_ids):
            errors.append("per_query: ids differ from the query set")
        for index, row in enumerate(per_query):
            errors += _stats_errors(f"per_query[{index}]", row)
    return errors


def _ms(value: float) -> str:
    return f"{value:.2f}"


def render_markdown(metrics: dict[str, Any]) -> str:
    env = metrics["environment"]
    params = metrics["parameters"]
    glob = metrics["global"]
    accepted = metrics["verdict"] == VERDICT_ACCEPTABLE
    verdict_text = (
        "**acceptable** : le p95 global respecte le seuil."
        if accepted
        else "**too_slow** : le p95 global dépasse le seuil."
    )
    lines = [
        "# Latence de `prepare_project_context` — P16",
        "",
        "## Commande",
        "",
        "```",
        metrics["command"],
        "```",
        "",
        "## Méthodologie",
        "",
        f"- Corpus : `{CORPUS_RELATIVE_PATH}` chargé dans un projet jetable sur un vrai "
        f"PostgreSQL, à la fois comme {params['decisions']} décisions (table `decisions`) et "
        f"comme {params['vault_notes']} notes vault de type `decision`. Le `task_id` des "
        "décisions n'est pas reporté (aucune tâche correspondante dans le projet jetable).",
        f"- Requêtes : `{QUERIES_RELATIVE_PATH}` ({len(metrics['queries'])} objectifs), "
        "rejouées en processus via `studio_api.services.project_context."
        f"prepare_project_context` (limit={params['limit']}, max_chars={params['max_chars']}), "
        "avec un principal admin réel chargé par `load_principal`.",
        f"- {params['warmup_passes']} passes d'échauffement sur toutes les requêtes, puis "
        f"{params['samples_per_query']} mesures par requête avec `time.perf_counter` ; "
        "une session SQLAlchemy neuve par appel, comme une requête HTTP.",
        "- Percentiles par interpolation linéaire ; la mesure exclut le transport HTTP/MCP.",
        "- Le projet, ses décisions, ses notes, la machine et l'utilisateur sont supprimés "
        "en fin d'exécution.",
        "",
        "## Environnement",
        "",
        f"- OS : {env['os']}",
        f"- Python : {env['python']}",
        f"- PostgreSQL : {env['postgresql']}",
        "",
        "## Résultat global",
        "",
        "| Mesures | p50 (ms) | p95 (ms) | max (ms) | moyenne (ms) |",
        "|---|---|---|---|---|",
        f"| {len(metrics['queries']) * params['samples_per_query']} | {_ms(glob['p50_ms'])} "
        f"| {_ms(glob['p95_ms'])} | {_ms(glob['max_ms'])} | {_ms(glob['mean_ms'])} |",
        "",
        "## Seuil et verdict",
        "",
        f"Seuil d'acceptation : p95 global ≤ {metrics['threshold_p95_ms']:.0f} ms en processus.",
        "",
        f"Verdict : {verdict_text} (p95 = {_ms(glob['p95_ms'])} ms)",
        "",
        "## Détail par requête",
        "",
        "| id | p50 (ms) | p95 (ms) | max (ms) | moyenne (ms) |",
        "|---|---|---|---|---|",
    ]
    for row in metrics["per_query"]:
        lines.append(
            f"| {row['id']} | {_ms(row['p50_ms'])} | {_ms(row['p95_ms'])} "
            f"| {_ms(row['max_ms'])} | {_ms(row['mean_ms'])} |"
        )
    lines += [
        "",
        "## Métriques machine (structure vérifiée par `--check`)",
        "",
        METRICS_BEGIN,
        "```json",
        canonical_json(metrics),
        "```",
        METRICS_END,
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if the report is invalid")
    mode.add_argument("--apply", action="store_true", help="measure and (re)write the report")
    parser.add_argument("--stdout", action="store_true", help="also print the report")
    args = parser.parse_args(argv)

    queries = load_queries(args.root / QUERIES_RELATIVE_PATH)
    expected_ids = [query["id"] for query in queries["queries"]]
    target = args.root / REPORT_RELATIVE_PATH

    if args.check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        try:
            published = extract_metrics(current)
        except ValueError:
            print(
                f"{REPORT_RELATIVE_PATH} is missing or has no metrics block -- rerun with --apply."
            )
            return 1
        errors = validate_metrics(published, expected_ids)
        if errors:
            for error in errors:
                print(f"{REPORT_RELATIVE_PATH}: {error}")
            return 1
        print(f"{REPORT_RELATIVE_PATH} is structurally valid.")
        return 0

    corpus = load_corpus(args.root / CORPUS_RELATIVE_PATH)
    selection = queries.get("selection", {})
    database_url = os.environ.get("STUDIO_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
    metrics = run_eval(
        queries,
        corpus,
        limit=int(selection.get("limit", 5)),
        max_chars=int(selection.get("max_chars", 12000)),
        database_url=database_url,
    )
    rendered = render_markdown(metrics)
    if args.stdout:
        sys.stdout.write(rendered)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8", newline="\n")
    glob = metrics["global"]
    print(
        f"Wrote {REPORT_RELATIVE_PATH}: p50={glob['p50_ms']} ms, p95={glob['p95_ms']} ms, "
        f"max={glob['max_ms']} ms, verdict={metrics['verdict']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
