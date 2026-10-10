"""P01-metrics — baseline mesurée de Mission Control.

Scénario seedé déterministe (graine fixe) sur un vrai PostgreSQL
(`STUDIO_TEST_DATABASE_URL`) : un projet jetable, deux machines et leurs agents,
20 tâches, 5 claims, 30 entrées `ai_work` (started puis completed) et une
roadmap active. Les mesures passent par les *vrais* services
(`studio_api.services.start_work.start_work` avec et sans `task_id`,
`prepare_project_context`, `services.sync.sync`) : taille JSON de la réponse,
tokens approchés, latence p50/p95/max, nombre d'items et compteurs
`omitted_for_budget` / `overflow`.

Le bruit est mesuré sur le même scénario : événements émis par type, ratio
événements / `ai_work_id` unique, items `sync` redondants (même entité
répétée). Le projet jetable, ses lignes et les machines/utilisateur sont
supprimés à la fin.

Publié dans `docs/mission-control/metrics.json`. Les latences ne sont pas
déterministes : `--check` ne valide que la structure du JSON publié et n'ouvre
jamais la base.

Usage:
    uv run python -m scripts.mission_metrics --root . --check   # exit 1 si invalide
    uv run python -m scripts.mission_metrics --root . --apply   # mesurer et (ré)écrire
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.roadmap import RoadmapModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.user import UserModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import agents as agents_service
from studio_api.services import ai_work as ai_work_service
from studio_api.services import claims as claims_service
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services import roadmaps as roadmaps_service
from studio_api.services import start_work as start_work_service
from studio_api.services import sync as sync_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal, load_principal
from studio_api.services.project_context import prepare_project_context
from studio_api.settings import Settings, get_settings
from studio_contracts.ai_work import AIWorkLogCreate, AIWorkLogUpdate, AIWorkStatus
from studio_contracts.auth import AgentCreate
from studio_contracts.claims import ResourceClaimCreate
from studio_contracts.roadmaps import (
    RoadmapImport,
    RoadmapTransition,
    TransitionRequest,
)
from studio_contracts.start_work import StartWorkRequest
from studio_contracts.sync import SYNC_DEFAULT_LIMIT
from studio_contracts.tasks import TaskCreate

METRICS_FORMAT = "studio.eval.mission-metrics/v1"
METRICS_RELATIVE_PATH = "docs/mission-control/metrics.json"
COMMAND = "uv run python -m scripts.mission_metrics --root . --apply"

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test"

SEED = 20261009
MACHINE_COUNT = 2
TASK_COUNT = 20
CLAIM_COUNT = 5
AI_WORK_COUNT = 30
ROADMAP_STEP_KEYS = ("S1", "S2", "S3")
ROADMAP_STEP_LINKS = 3

OBJECTIVE = (
    "baseline mission control : budget de contexte, latence des lectures et bruit "
    "des evenements par entree de travail"
)

WARMUP_PASSES = 2
SAMPLES_PER_CALL = 10
CONTEXT_LIMIT = 5
CONTEXT_MAX_CHARS = 12_000
CHARS_PER_TOKEN = 4
DECIMALS = 2

CALL_START_WORK_TASK = "start_work_with_task"
CALL_START_WORK_PROJECT = "start_work_without_task"
CALL_PREPARE_CONTEXT = "prepare_project_context"
CALL_SYNC = "sync"
CALL_KINDS = (
    CALL_START_WORK_TASK,
    CALL_START_WORK_PROJECT,
    CALL_PREPARE_CONTEXT,
    CALL_SYNC,
)

SERVICE_OF = {
    CALL_START_WORK_TASK: "studio_api.services.start_work.start_work",
    CALL_START_WORK_PROJECT: "studio_api.services.start_work.start_work",
    CALL_PREPARE_CONTEXT: "studio_api.services.project_context.prepare_project_context",
    CALL_SYNC: "studio_api.services.sync.sync",
}

LATENCY_KEYS = ("p50_ms", "p95_ms", "max_ms")
SIZE_KEYS = ("min", "mean", "max")
ENVIRONMENT_KEYS = ("os", "python", "postgresql", "alembic_head", "git_sha")
SEEDED_KEYS = (
    "projects",
    "machines",
    "agents",
    "tasks",
    "claims",
    "ai_work_entries",
    "ai_work_completions",
    "roadmaps",
)

TOPICS = (
    "budget de contexte",
    "cur de synchronisation",
    "roadmap actif",
    "claim de ressource",
    "session agent",
    "note vault",
    "handoff",
    "revue de travail",
    "resolution agent",
    "migration api",
)
VERBS = ("mesurer", "corriger", "documenter", "verifier", "refactorer")
NOUNS = ("service", "route", "modele", "evenement", "contrat")
BUDGETS = (4_000, 8_000, 12_000, 24_000)

ROADMAP_DOCUMENT: dict[str, Any] = {
    "format": "studio.roadmap/v1",
    "title": "Plan Mission Control",
    "objective": "Mesurer la baseline Mission Control avant toute representation nouvelle",
    "phases": [
        {
            "key": "P1",
            "title": "Baseline",
            "steps": [
                {
                    "key": "S1",
                    "title": "Mesurer les lectures",
                    "acceptance_criteria": ["latence p95 sous le seuil pilote"],
                },
                {
                    "key": "S2",
                    "title": "Mesurer le bruit",
                    "depends_on": ["S1"],
                    "acceptance_criteria": ["ratio evenements par ai_work connu"],
                },
            ],
        },
        {
            "key": "P2",
            "title": "Suite",
            "steps": [
                {
                    "key": "S3",
                    "title": "Cadrer la gate architecture",
                    "depends_on": ["S2"],
                    "acceptance_criteria": ["contrats ecrits et valides"],
                }
            ],
        },
    ],
}

MISSING_METRICS: tuple[dict[str, str], ...] = (
    {
        "metric": "harness_tokens_per_ai_work",
        "status": "unknown",
        "reason": (
            "Aucun run de harness dans ce scenario : rien ne compte les tokens "
            "d'une execution reelle Claude Code, OpenCode ou Codex, la valeur "
            "reste inconnue et jamais 0."
        ),
    },
    {
        "metric": "harness_cost_per_ai_work",
        "status": "unknown",
        "reason": (
            "Aucun tarif date n'est applique et aucune facture provider n'est "
            "lue : un cout absent reste inconnu, jamais 0."
        ),
    },
    {
        "metric": "usage_collector_coverage",
        "status": "unknown",
        "reason": (
            "Les 30 entrees ont ete ecrites par ce script, pas par un collecteur "
            "versionne par harness : la part des runs reels qui serait ingeree "
            "n'est pas observable ici."
        ),
    },
    {
        "metric": "pilot_thresholds",
        "status": "unknown",
        "reason": (
            "Une graine synthetique n'a ni fenetre pilote ni usage reel : aucun "
            "seuil d'acceptation ne peut en etre tire."
        ),
    },
)


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


def summarize_latency(samples_ms: Sequence[float]) -> dict[str, float]:
    return {
        "p50_ms": round(percentile(samples_ms, 50.0), DECIMALS),
        "p95_ms": round(percentile(samples_ms, 95.0), DECIMALS),
        "max_ms": round(max(samples_ms), DECIMALS),
    }


def summarize_size(samples: Sequence[float]) -> dict[str, float]:
    return {
        "min": round(min(samples), DECIMALS),
        "mean": round(sum(samples) / len(samples), DECIMALS),
        "max": round(max(samples), DECIMALS),
    }


def approximate_tokens(chars: float) -> float:
    """Tokenizer-independent proxy: the budget contracts count characters, so a
    token is approximated by `CHARS_PER_TOKEN` characters. An estimate, never a
    provider count."""
    return round(chars / CHARS_PER_TOKEN, DECIMALS)


def _mean_counters(samples: Sequence[Mapping[str, int]]) -> dict[str, float]:
    keys = sorted({key for sample in samples for key in sample})
    return {
        key: round(sum(sample.get(key, 0) for sample in samples) / len(samples), DECIMALS)
        for key in keys
    }


def summarize_call(kind: str, samples: Sequence[CallSample]) -> dict[str, Any]:
    chars = [sample.chars for sample in samples]
    latencies = [sample.latency_ms for sample in samples]
    last = samples[-1]
    return {
        "service": SERVICE_OF[kind],
        "samples": len(samples),
        "warmup_passes": WARMUP_PASSES,
        "response_chars": summarize_size(chars),
        "approx_tokens": summarize_size([approximate_tokens(value) for value in chars]),
        "latency_ms": summarize_latency(latencies),
        "items": _mean_counters([sample.items for sample in samples]),
        "omitted_for_budget": dict(last.omitted),
        "overflow": dict(last.overflow),
    }


def aggregate_event_noise(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Events of the scenario by type, and how many of them each unique
    `ai_work_id` carries. Pure: rows are `{"event_type": ..., "payload": ...}`."""
    by_type = Counter(cast(str, row["event_type"]) for row in rows)
    ai_work_ids = {
        str(row["payload"]["ai_work_id"])
        for row in rows
        if isinstance(row.get("payload"), Mapping) and row["payload"].get("ai_work_id")
    }
    ai_work_events = sum(
        1
        for row in rows
        if isinstance(row.get("payload"), Mapping) and row["payload"].get("ai_work_id")
    )
    unique = len(ai_work_ids)
    return {
        "events_total": len(rows),
        "by_type": dict(sorted(by_type.items())),
        "ai_work_events": ai_work_events,
        "unique_ai_work_ids": unique,
        "events_per_ai_work": round(ai_work_events / unique, 3) if unique else None,
        "total_events_per_ai_work_id": round(len(rows) / unique, 3) if unique else None,
    }


def sync_item_key(item: Mapping[str, Any]) -> str:
    """Identity of the entity a sync item carries: its `seq` for an event (the
    cursor identity, DEC-0018), the claim id for live claim state."""
    if item.get("seq") is not None:
        return f"event:{item['seq']}"
    if item.get("claim_id") is not None:
        return f"claim:{item['claim_id']}"
    coordination = item.get("coordination") or {}
    return f"coordination:{coordination.get('event_id')}"


def count_redundant_sync_items(calls: Sequence[Sequence[Mapping[str, Any]]]) -> dict[str, int]:
    """Items delivered again across successive sync answers: the same entity
    (`seq`, claim id, coordination event id) reappears because no cursor was
    acknowledged — at-least-once by design, counted here as noise."""
    seen: set[str] = set()
    total = 0
    redundant = 0
    for call in calls:
        for item in call:
            total += 1
            key = sync_item_key(item)
            if key in seen:
                redundant += 1
            seen.add(key)
    return {
        "calls": len(calls),
        "items": total,
        "unique_entities": len(seen),
        "redundant_items": redundant,
    }


def canonical_json(metrics: dict[str, Any]) -> str:
    return json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def git_sha(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() or "unknown"


def alembic_head(root: Path) -> str:
    api = root / "services" / "api"
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "alembic"))
    return ",".join(sorted(ScriptDirectory.from_config(config).get_heads()))


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_count_map(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and _is_number(count) for key, count in value.items()
    )


def _number_errors(where: str, section: object, keys: Sequence[str]) -> list[str]:
    if not isinstance(section, dict):
        return [f"{where}: not an object"]
    return [
        f"{where}.{key}: missing or not a number"
        for key in keys
        if not _is_number(section.get(key))
    ]


def validate_metrics(metrics: dict[str, Any]) -> list[str]:
    """Structure only: no database, no timing, nothing environment-specific."""
    errors: list[str] = []
    if metrics.get("format") != METRICS_FORMAT:
        errors.append(f"format: expected {METRICS_FORMAT!r}, got {metrics.get('format')!r}")
    if not isinstance(metrics.get("command"), str) or not metrics["command"]:
        errors.append("command: missing or not a string")
    generated_at = metrics.get("generated_at")
    if not isinstance(generated_at, str):
        errors.append("generated_at: missing or not a string")
    else:
        try:
            parsed = datetime.fromisoformat(generated_at)
        except ValueError:
            errors.append(f"generated_at: {generated_at!r} is not an ISO 8601 date")
        else:
            if parsed.tzinfo is None:
                errors.append("generated_at: no timezone offset")

    environment = metrics.get("environment")
    if not isinstance(environment, dict):
        errors.append("environment: not an object")
    else:
        for key in ENVIRONMENT_KEYS:
            value = environment.get(key)
            if not isinstance(value, str) or not value:
                errors.append(f"environment.{key}: missing or not a non-empty string")

    sample = metrics.get("sample")
    if not isinstance(sample, dict):
        errors.append("sample: not an object")
    else:
        seeded = sample.get("seeded")
        if not isinstance(seeded, dict):
            errors.append("sample.seeded: not an object")
        else:
            errors += _number_errors("sample.seeded", seeded, SEEDED_KEYS)
        errors += _number_errors(
            "sample",
            sample,
            ("seed", "warmup_passes", "samples_per_call", "call_kinds", "measured_calls"),
        )

    calls = metrics.get("calls")
    if not isinstance(calls, dict):
        errors.append("calls: not an object")
    else:
        if set(calls) != set(CALL_KINDS):
            errors.append("calls: kinds differ from the measured call set")
        for kind in CALL_KINDS:
            row = calls.get(kind)
            if not isinstance(row, dict):
                errors.append(f"calls.{kind}: not an object")
                continue
            errors += _number_errors(
                f"calls.{kind}.latency_ms", row.get("latency_ms"), LATENCY_KEYS
            )
            for size in ("response_chars", "approx_tokens"):
                errors += _number_errors(f"calls.{kind}.{size}", row.get(size), SIZE_KEYS)
            if not isinstance(row.get("service"), str) or not row["service"]:
                errors.append(f"calls.{kind}.service: missing or not a non-empty string")
            errors += _number_errors(f"calls.{kind}", row, ("samples", "warmup_passes"))
            for counters in ("items", "omitted_for_budget", "overflow"):
                if not _is_count_map(row.get(counters)):
                    errors.append(f"calls.{kind}.{counters}: missing or not a count map")

    noise = metrics.get("noise")
    if not isinstance(noise, dict):
        errors.append("noise: not an object")
    else:
        errors += _number_errors(
            "noise",
            noise,
            ("events_total", "ai_work_events", "unique_ai_work_ids"),
        )
        if not _is_count_map(noise.get("by_type")):
            errors.append("noise.by_type: missing or not a count map")
        for ratio in ("events_per_ai_work", "total_events_per_ai_work_id"):
            if not _is_number(noise.get(ratio)):
                errors.append(f"noise.{ratio}: missing or not a number")
        errors += _number_errors(
            "noise.sync_redundancy",
            noise.get("sync_redundancy"),
            ("calls", "items", "unique_entities", "redundant_items"),
        )

    missing = metrics.get("missing")
    if not isinstance(missing, list) or not missing:
        errors.append("missing: expected a non-empty list of unmeasurable metrics")
    else:
        for index, entry in enumerate(missing):
            if not isinstance(entry, dict):
                errors.append(f"missing[{index}]: not an object")
                continue
            for field_name in ("metric", "status", "reason"):
                value = entry.get(field_name)
                if not isinstance(value, str) or not value:
                    errors.append(f"missing[{index}].{field_name}: missing or not a string")
            if entry.get("status") != "unknown":
                errors.append(
                    f"missing[{index}].status: expected 'unknown', got {entry.get('status')!r}"
                )
            if any(_is_number(value) for value in entry.values()):
                errors.append(f"missing[{index}]: an unmeasurable metric carries a number, never 0")
    return errors


def scenario_text(rng: random.Random, index: int) -> tuple[str, str]:
    """Title and description of one seeded task: a function of the seed and the
    index only, never of the clock or the run."""
    topic = TOPICS[index % len(TOPICS)]
    verb = VERBS[index % len(VERBS)]
    noun = NOUNS[index % len(NOUNS)]
    budget = rng.choice(BUDGETS)
    tests = rng.randint(2, 40)
    title = f"{verb} le {topic} - {noun} {index:02d}"
    description = (
        f"Contexte {topic} pour la machine {index % MACHINE_COUNT + 1}. "
        f"Le {noun} {index:02d} doit rester borne a {budget} caracteres de contexte. "
        f"Verification: {tests} assertions couvrent ce chemin. "
        f"Suite: rejouer la mesure et comparer la latence p95 a la baseline precedente."
    )
    return title, description


def claim_path(index: int) -> str:
    return f"src/module_{index:02d}/service.py"


def ai_work_summary(rng: random.Random, index: int) -> str:
    """Summary of one seeded work entry: a function of the seed and the index,
    so the handoff packet is the same shape on every run."""
    title, description = scenario_text(rng, index)
    return f"{title} — etape {index // 2 + 1}. {description}"


@dataclass
class CallSample:
    chars: int
    latency_ms: float
    items: dict[str, int] = field(default_factory=dict)
    omitted: dict[str, int] = field(default_factory=dict)
    overflow: dict[str, int] = field(default_factory=dict)
    raw_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Scenario:
    project_id: uuid.UUID
    agent_a: uuid.UUID
    task_ids: list[uuid.UUID]
    files: list[str]
    objective: str
    session_id: uuid.UUID | None = None


def _context_items(context: Any) -> dict[str, int]:
    return {
        **{f"context_{name}": count for name, count in context.returned.items()},
        "context_chars_used": context.limits.chars_used,
    }


def _why_items(items: Sequence[Any]) -> dict[str, int]:
    counts = Counter(cast(str, item.why) for item in items)
    return {"items": len(items), **{f"by_why_{why}": n for why, n in sorted(counts.items())}}


async def _time_call(
    kind: str,
    session_factory: async_sessionmaker[AsyncSession],
    principal: Principal,
    scenario: Scenario,
    settings: Settings,
) -> CallSample:
    """One real service call, timed like a request would be: a fresh session,
    `time.perf_counter` around the service call only (no transport)."""
    async with session_factory() as session:
        started = time.perf_counter()
        if kind == CALL_START_WORK_TASK:
            result = await start_work_service.start_work(
                session,
                principal,
                StartWorkRequest(
                    project_id=scenario.project_id,
                    agent_id=scenario.agent_a,
                    task_id=scenario.task_ids[0],
                    objective=scenario.objective,
                    files=scenario.files,
                    limit=CONTEXT_LIMIT,
                    max_chars=CONTEXT_MAX_CHARS,
                ),
                settings,
            )
            assert result.session is not None
            scenario.session_id = result.session.id
            payload = result.model_dump_json()
            elapsed = (time.perf_counter() - started) * 1000.0
            context = result.prepared_context
            assert context is not None and result.sync is not None
            return CallSample(
                chars=len(payload),
                latency_ms=elapsed,
                items={
                    "candidates": len(result.candidates),
                    "sync_items": len(result.sync.items),
                    **_context_items(context),
                },
                omitted=dict(context.omitted_for_budget),
                overflow=dict(result.sync.overflow),
            )

        if kind == CALL_START_WORK_PROJECT:
            result = await start_work_service.start_work(
                session,
                principal,
                StartWorkRequest(
                    project_id=scenario.project_id,
                    agent_id=scenario.agent_a,
                    objective=scenario.objective,
                    limit=CONTEXT_LIMIT,
                    max_chars=CONTEXT_MAX_CHARS,
                ),
                settings,
            )
            payload = result.model_dump_json()
            elapsed = (time.perf_counter() - started) * 1000.0
            context = result.prepared_context
            assert context is not None
            return CallSample(
                chars=len(payload),
                latency_ms=elapsed,
                items={"candidates": len(result.candidates), **_context_items(context)},
                omitted=dict(context.omitted_for_budget),
            )

        if kind == CALL_PREPARE_CONTEXT:
            context = await prepare_project_context(
                session,
                principal,
                scenario.project_id,
                scenario.objective,
                task_id=scenario.task_ids[0],
                files=scenario.files,
                limit=CONTEXT_LIMIT,
                max_chars=CONTEXT_MAX_CHARS,
            )
            payload = context.model_dump_json()
            elapsed = (time.perf_counter() - started) * 1000.0
            return CallSample(
                chars=len(payload),
                latency_ms=elapsed,
                items=_context_items(context),
                omitted=dict(context.omitted_for_budget),
            )

        assert scenario.session_id is not None
        sync_result = await sync_service.sync(
            session, principal, session_id=scenario.session_id, limit=SYNC_DEFAULT_LIMIT
        )
        payload = sync_result.model_dump_json()
        elapsed = (time.perf_counter() - started) * 1000.0
        return CallSample(
            chars=len(payload),
            latency_ms=elapsed,
            items=_why_items(sync_result.items),
            overflow=dict(sync_result.overflow),
            raw_items=[item.model_dump(mode="json") for item in sync_result.items],
        )


async def _seed_scenario(
    session: AsyncSession,
    principals: list[Principal],
    rng: random.Random,
    project_id: uuid.UUID,
    machines: list[uuid.UUID],
    agents: list[uuid.UUID],
) -> Scenario:
    principal = principals[0]
    task_ids: list[uuid.UUID] = []
    for index in range(TASK_COUNT):
        title, description = scenario_text(rng, index)
        task = await tasks_service.create_task(
            session,
            principal,
            TaskCreate(project_id=project_id, title=title, description=description),
        )
        task_ids.append(task.id)

    for index in range(CLAIM_COUNT):
        await claims_service.create_claim(
            session,
            principals[index % MACHINE_COUNT],
            ResourceClaimCreate(
                project_id=project_id,
                task_id=task_ids[index * 3],
                resource_path=claim_path(index),
                resource_type="file",
                ttl_seconds=3600,
            ),
            machines[index % MACHINE_COUNT],
            agents[index % MACHINE_COUNT],
        )

    roadmap = await roadmaps_service.import_roadmap(
        session, principal, RoadmapImport(project_id=project_id, document=ROADMAP_DOCUMENT)
    )
    await roadmaps_service.transition_roadmap(
        session,
        principal,
        roadmap.id,
        TransitionRequest(transition=RoadmapTransition.ACTIVATE, expected_version=roadmap.version),
    )
    for index, step_key in enumerate(ROADMAP_STEP_KEYS[:ROADMAP_STEP_LINKS]):
        await roadmaps_service.link_task_by_step_key(
            session, principal, roadmap.id, step_key, task_ids[index]
        )

    for index in range(AI_WORK_COUNT):
        machine_principal = principals[index % MACHINE_COUNT]
        created = await ai_work_service.create_ai_work(
            session,
            machine_principal,
            AIWorkLogCreate(
                task_id=task_ids[index % TASK_COUNT],
                project_id=project_id,
                agent_id=agents[index % MACHINE_COUNT],
                machine_id=machines[index % MACHINE_COUNT],
                summary=ai_work_summary(rng, index),
                status=AIWorkStatus.STARTED,
                changed_files=[claim_path(index % CLAIM_COUNT)],
                tests_run=[f"tests/scripts/test_mission_metrics.py::case-{index:02d}"],
                harness="claude-code" if index % MACHINE_COUNT == 0 else "opencode",
            ),
        )
        await ai_work_service.update_ai_work(
            session,
            machine_principal,
            created,
            AIWorkLogUpdate(status=AIWorkStatus.COMPLETED, summary=created.summary),
        )

    return Scenario(
        project_id=project_id,
        agent_a=agents[0],
        task_ids=task_ids,
        files=[claim_path(index) for index in range(CLAIM_COUNT)][:2],
        objective=OBJECTIVE,
    )


async def _cleanup(
    session: AsyncSession, project_id: uuid.UUID, machine_ids: list[uuid.UUID], user_id: uuid.UUID
) -> None:
    await session.rollback()
    await session.execute(delete(EventModel).where(EventModel.project_id == project_id))
    await session.execute(delete(AIWorkLogModel).where(AIWorkLogModel.project_id == project_id))
    await session.execute(
        delete(ResourceClaimModel).where(ResourceClaimModel.project_id == project_id)
    )
    await session.execute(
        delete(WorkSessionModel).where(WorkSessionModel.machine_id.in_(machine_ids))
    )
    await session.execute(delete(RoadmapModel).where(RoadmapModel.project_id == project_id))
    await session.execute(delete(TaskModel).where(TaskModel.project_id == project_id))
    await session.execute(delete(AgentModel).where(AgentModel.machine_id.in_(machine_ids)))
    await session.execute(
        delete(ProjectMembershipModel).where(ProjectMembershipModel.project_id == project_id)
    )
    await session.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
    await session.execute(delete(MachineModel).where(MachineModel.id.in_(machine_ids)))
    await session.execute(delete(UserModel).where(UserModel.id == user_id))
    await session.commit()


async def _run_db_eval(root: Path, database_url: str) -> dict[str, Any]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    rng = random.Random(SEED)
    settings = get_settings()
    user_id = uuid.uuid4()
    machine_ids: list[uuid.UUID] = []
    project_id = uuid.uuid4()
    try:
        async with session_factory() as session:
            server_version = str((await session.execute(text("SHOW server_version"))).scalar_one())
            user = await provisioning_service.create_user(
                session,
                "Mission Metrics",
                f"mission-metrics-{uuid.uuid4().hex}@example.test",
                "admin",
            )
            user_id = user.id
            machines: list[uuid.UUID] = []
            agents: list[uuid.UUID] = []
            principals: list[Principal] = []
            machine_ids = machines
            for index in range(MACHINE_COUNT):
                machine, _token = await provisioning_service.create_machine(
                    session, user.id, f"mission-metrics-{index}"
                )
                machine_principal = await load_principal(session, machine)
                agent, _created = await agents_service.ensure_agent(
                    session,
                    machine_principal,
                    AgentCreate(
                        display_name=f"mission-metrics-agent-{index}",
                        stable_key=f"mission-metrics-agent-{index}",
                    ),
                )
                machines.append(machine.id)
                agents.append(agent.id)
                principals.append(machine_principal)
            principal = principals[0]

            project = await projects_service.create_project(
                session,
                f"mission-metrics-{uuid.uuid4().hex[:8]}",
                "Mission Metrics",
                "Projet jetable de la baseline Mission Control (P01-metrics).",
                creator=user,
            )
            project_id = project.id
            try:
                scenario = await _seed_scenario(
                    session, principals, rng, project.id, machines, agents
                )
                measured, sync_payloads = await _measure(
                    session_factory, principal, scenario, settings
                )
                event_rows = await _scenario_event_rows(session, project_id)
            finally:
                await _cleanup(session, project_id, machine_ids, user_id)
    finally:
        await engine.dispose()

    return build_metrics(
        measured,
        event_rows,
        sync_payloads,
        environment={
            "os": platform.platform(),
            "python": platform.python_version(),
            "postgresql": server_version,
            "alembic_head": alembic_head(root),
            "git_sha": git_sha(root),
        },
    )


async def _measure(
    session_factory: async_sessionmaker[AsyncSession],
    principal: Principal,
    scenario: Scenario,
    settings: Settings,
) -> tuple[dict[str, list[CallSample]], list[list[dict[str, Any]]]]:
    for _ in range(WARMUP_PASSES):
        for kind in CALL_KINDS:
            await _time_call(kind, session_factory, principal, scenario, settings)
    measured: dict[str, list[CallSample]] = {}
    for kind in CALL_KINDS:
        samples: list[CallSample] = []
        for _ in range(SAMPLES_PER_CALL):
            samples.append(await _time_call(kind, session_factory, principal, scenario, settings))
        measured[kind] = samples
    return measured, [sample.raw_items for sample in measured[CALL_SYNC]]


async def _scenario_event_rows(
    session: AsyncSession, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(EventModel.event_type, EventModel.payload).where(
                EventModel.project_id == project_id
            )
        )
    ).all()
    return [{"event_type": row.event_type, "payload": row.payload or {}} for row in rows]


def build_metrics(
    measured: Mapping[str, Sequence[CallSample]],
    event_rows: Sequence[Mapping[str, Any]],
    sync_payloads: Sequence[Sequence[Mapping[str, Any]]],
    *,
    environment: dict[str, str],
) -> dict[str, Any]:
    noise: dict[str, Any] = dict(aggregate_event_noise(event_rows))
    noise["sync_redundancy"] = count_redundant_sync_items(sync_payloads)
    seeded = {
        "projects": 1,
        "machines": MACHINE_COUNT,
        "agents": MACHINE_COUNT,
        "tasks": TASK_COUNT,
        "claims": CLAIM_COUNT,
        "ai_work_entries": AI_WORK_COUNT,
        "ai_work_completions": AI_WORK_COUNT,
        "roadmaps": 1,
    }
    return {
        "format": METRICS_FORMAT,
        "command": COMMAND,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": environment,
        "sample": {
            "seed": SEED,
            "seeded": seeded,
            "warmup_passes": WARMUP_PASSES,
            "samples_per_call": SAMPLES_PER_CALL,
            "call_kinds": len(CALL_KINDS),
            "measured_calls": sum(len(samples) for samples in measured.values()),
            "context_limit": CONTEXT_LIMIT,
            "context_max_chars": CONTEXT_MAX_CHARS,
            "sync_limit": SYNC_DEFAULT_LIMIT,
        },
        "calls": {kind: summarize_call(kind, measured[kind]) for kind in CALL_KINDS},
        "noise": noise,
        "missing": [dict(entry) for entry in MISSING_METRICS],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if the JSON is invalid")
    mode.add_argument("--apply", action="store_true", help="measure and (re)write the JSON")
    parser.add_argument("--stdout", action="store_true", help="also print the JSON")
    args = parser.parse_args(argv)

    target = args.root / METRICS_RELATIVE_PATH
    if args.check:
        if not target.is_file():
            print(f"{METRICS_RELATIVE_PATH} is missing -- rerun with --apply.")
            return 1
        try:
            published = cast(dict[str, Any], json.loads(target.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            print(f"{METRICS_RELATIVE_PATH}: not valid JSON ({exc})")
            return 1
        errors = validate_metrics(published)
        if errors:
            for error in errors:
                print(f"{METRICS_RELATIVE_PATH}: {error}")
            return 1
        print(f"{METRICS_RELATIVE_PATH} is structurally valid.")
        return 0

    database_url = os.environ.get("STUDIO_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
    metrics = asyncio.run(_run_db_eval(args.root, database_url))
    rendered = canonical_json(metrics)
    if args.stdout:
        sys.stdout.write(rendered)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8", newline="\n")
    latency = metrics["calls"][CALL_START_WORK_TASK]["latency_ms"]
    noise = metrics["noise"]
    print(
        f"Wrote {METRICS_RELATIVE_PATH}: start_work(task) p50={latency['p50_ms']} ms, "
        f"p95={latency['p95_ms']} ms, events={noise['events_total']}, "
        f"redundant sync items={noise['sync_redundancy']['redundant_items']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
