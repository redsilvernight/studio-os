"""Structure and pure functions of the Mission Control baseline metrics, without
any database: percentiles, size summaries, noise aggregation, sync redundancy,
and the `--check` validation of the published JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import mission_metrics as mm

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

EVENT_ROWS: list[dict[str, Any]] = [
    {"event_type": "task.created", "payload": {"status": "todo"}},
    {"event_type": "ai_work.started", "payload": {"ai_work_id": "w1", "status": "started"}},
    {"event_type": "ai_work.completed", "payload": {"ai_work_id": "w1", "status": "completed"}},
    {"event_type": "ai_work.started", "payload": {"ai_work_id": "w2", "status": "started"}},
    {"event_type": "ai_work.completed", "payload": {"ai_work_id": "w2", "status": "completed"}},
]

SYNC_CALLS: list[list[dict[str, Any]]] = [
    [{"kind": "event", "why": "own_task", "seq": 7, "event_type": "task.updated"}],
    [
        {"kind": "event", "why": "own_task", "seq": 7, "event_type": "task.updated"},
        {"kind": "claim", "why": "claim_overlap", "claim_id": "c1", "resource_path": "a.py"},
    ],
    [
        {
            "kind": "event",
            "why": "coordination",
            "seq": None,
            "coordination": {"event_id": "e9", "intent": "handoff"},
        },
        {"kind": "claim", "why": "claim_overlap", "claim_id": "c1", "resource_path": "a.py"},
    ],
]

ENVIRONMENT = {
    "os": "TestOS-1.0",
    "python": "3.12.0",
    "postgresql": "16.4",
    "alembic_head": "0029",
    "git_sha": "0123456789abcdef",
}


def _sample(chars: int, latency: float, **kwargs: Any) -> mm.CallSample:
    return mm.CallSample(chars=chars, latency_ms=latency, **kwargs)


def _measured() -> dict[str, list[mm.CallSample]]:
    return {
        kind: [
            _sample(1000 + index * 10, 10.0 + index, items={"items": 4}, omitted={"ai_work": 1})
            for index in range(4)
        ]
        for kind in mm.CALL_KINDS
    }


def _metrics() -> dict[str, Any]:
    return mm.build_metrics(_measured(), EVENT_ROWS, SYNC_CALLS, environment=dict(ENVIRONMENT))


def test_percentile_interpolates_linearly() -> None:
    values = [40.0, 10.0, 30.0, 20.0]
    assert mm.percentile(values, 0.0) == 10.0
    assert mm.percentile(values, 50.0) == 25.0
    assert mm.percentile(values, 100.0) == 40.0
    assert mm.percentile(values, 95.0) == pytest.approx(38.5)
    assert mm.percentile([7.0], 95.0) == 7.0


def test_percentile_rejects_empty_and_out_of_range() -> None:
    with pytest.raises(ValueError):
        mm.percentile([], 50.0)
    with pytest.raises(ValueError):
        mm.percentile([1.0], 101.0)


def test_summaries_round_latency_size_and_tokens() -> None:
    assert mm.summarize_latency([1.0, 2.0, 3.0, 4.0]) == {
        "p50_ms": 2.5,
        "p95_ms": 3.85,
        "max_ms": 4.0,
    }
    assert mm.summarize_size([100, 200, 300]) == {"min": 100.0, "mean": 200.0, "max": 300.0}
    assert mm.approximate_tokens(1000) == 250.0


def test_aggregate_event_noise_counts_types_and_ai_work_ratio() -> None:
    noise = mm.aggregate_event_noise(EVENT_ROWS)
    assert noise["events_total"] == 5
    assert noise["by_type"] == {
        "ai_work.completed": 2,
        "ai_work.started": 2,
        "task.created": 1,
    }
    assert noise["unique_ai_work_ids"] == 2
    assert noise["ai_work_events"] == 4
    assert noise["events_per_ai_work"] == 2.0
    assert noise["total_events_per_ai_work_id"] == 2.5


def test_aggregate_event_noise_without_ai_work_stays_unknown() -> None:
    noise = mm.aggregate_event_noise([{"event_type": "task.created", "payload": {}}])
    assert noise["events_total"] == 1
    assert noise["unique_ai_work_ids"] == 0
    assert noise["events_per_ai_work"] is None
    assert noise["total_events_per_ai_work_id"] is None


def test_sync_item_key_prefers_seq_then_claim_then_coordination() -> None:
    assert mm.sync_item_key(SYNC_CALLS[0][0]) == "event:7"
    assert mm.sync_item_key(SYNC_CALLS[1][1]) == "claim:c1"
    assert mm.sync_item_key(SYNC_CALLS[2][0]) == "coordination:e9"


def test_count_redundant_sync_items_sees_repeated_entities() -> None:
    counted = mm.count_redundant_sync_items(SYNC_CALLS)
    assert counted == {"calls": 3, "items": 5, "unique_entities": 3, "redundant_items": 2}
    assert mm.count_redundant_sync_items([]) == {
        "calls": 0,
        "items": 0,
        "unique_entities": 0,
        "redundant_items": 0,
    }


def test_summarize_call_keeps_counters_of_the_last_sample() -> None:
    summary = mm.summarize_call(mm.CALL_SYNC, _measured()[mm.CALL_SYNC])
    assert summary["service"] == "studio_api.services.sync.sync"
    assert summary["samples"] == 4
    assert summary["warmup_passes"] == mm.WARMUP_PASSES
    assert summary["items"] == {"items": 4.0}
    assert summary["omitted_for_budget"] == {"ai_work": 1}
    assert summary["overflow"] == {}
    assert summary["latency_ms"]["max_ms"] == 13.0
    assert summary["response_chars"]["max"] == 1030.0


def test_build_metrics_is_self_consistent() -> None:
    metrics = _metrics()
    assert metrics["format"] == mm.METRICS_FORMAT
    assert metrics["command"] == mm.COMMAND
    assert metrics["sample"]["seeded"] == {
        "projects": 1,
        "machines": mm.MACHINE_COUNT,
        "agents": mm.MACHINE_COUNT,
        "tasks": mm.TASK_COUNT,
        "claims": mm.CLAIM_COUNT,
        "ai_work_entries": mm.AI_WORK_COUNT,
        "ai_work_completions": mm.AI_WORK_COUNT,
        "roadmaps": 1,
    }
    assert metrics["sample"]["measured_calls"] == 4 * 4
    assert metrics["noise"]["sync_redundancy"]["redundant_items"] == 2
    assert [entry["metric"] for entry in metrics["missing"]] == [
        "harness_tokens_per_ai_work",
        "harness_cost_per_ai_work",
        "usage_collector_coverage",
        "pilot_thresholds",
    ]
    assert all(entry["status"] == "unknown" for entry in metrics["missing"])
    assert mm.validate_metrics(metrics) == []


def test_validate_reports_structural_errors() -> None:
    metrics = _metrics()
    metrics["calls"].pop(mm.CALL_SYNC)
    del metrics["calls"][mm.CALL_START_WORK_TASK]["latency_ms"]["p95_ms"]
    metrics["noise"]["by_type"] = {"task.created": "many"}
    metrics["missing"][0]["status"] = "0"
    errors = mm.validate_metrics(metrics)
    assert "calls: kinds differ from the measured call set" in errors
    assert "calls.start_work_with_task.latency_ms.p95_ms: missing or not a number" in errors
    assert "noise.by_type: missing or not a count map" in errors
    assert "missing[0].status: expected 'unknown', got '0'" in errors


def test_validate_flags_a_zero_for_an_unmeasurable_metric() -> None:
    metrics = _metrics()
    metrics["missing"][1]["tokens"] = 0
    errors = mm.validate_metrics(metrics)
    assert "missing[1]: an unmeasurable metric carries a number, never 0" in errors


def test_validate_flags_an_invalid_date_or_missing_environment() -> None:
    metrics = _metrics()
    metrics["generated_at"] = "2026-10-10"
    metrics["environment"]["git_sha"] = ""
    errors = mm.validate_metrics(metrics)
    assert "generated_at: no timezone offset" in errors
    assert "environment.git_sha: missing or not a non-empty string" in errors


def test_check_accepts_a_written_document(tmp_path: Path) -> None:
    (tmp_path / "docs" / "mission-control").mkdir(parents=True)
    (tmp_path / "docs" / "mission-control" / "metrics.json").write_text(
        mm.canonical_json(_metrics()), encoding="utf-8"
    )
    assert mm.main(["--root", str(tmp_path), "--check"]) == 0


def test_check_rejects_a_broken_document_and_a_missing_one(tmp_path: Path) -> None:
    broken = _metrics()
    del broken["calls"]
    target = tmp_path / "docs" / "mission-control" / "metrics.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(broken), encoding="utf-8")
    assert mm.main(["--root", str(tmp_path), "--check"]) == 1

    target.write_text("{not json", encoding="utf-8")
    assert mm.main(["--root", str(tmp_path), "--check"]) == 1

    target.unlink()
    assert mm.main(["--root", str(tmp_path), "--check"]) == 1


def test_check_validates_the_published_baseline() -> None:
    """The committed `docs/mission-control/metrics.json` must stay valid, and
    `--check` must never open the database to prove it."""
    published = json.loads((REPOSITORY_ROOT / mm.METRICS_RELATIVE_PATH).read_text(encoding="utf-8"))
    assert mm.validate_metrics(published) == []
    assert mm.main(["--root", str(REPOSITORY_ROOT), "--check"]) == 0
