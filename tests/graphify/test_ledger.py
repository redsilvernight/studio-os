"""Tests for the Graphify cost ledger: reading old cost.json files,
recording new per-attempt entries without fabricating measurements, and the
file/backend/period/ratio/top-cost reports.

The ledger engine (`graphify_ledger.py`) is canonically global -- shipped
once next to `~/.claude/scripts/graphify_incremental_update.py` -- so it is
loaded here by path rather than as a `scripts.*` package import."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

GLOBAL_ENGINE = Path.home() / ".claude" / "scripts" / "graphify_ledger.py"
if not GLOBAL_ENGINE.exists():
    pytest.skip(
        f"global ledger engine not present on this machine: {GLOBAL_ENGINE}",
        allow_module_level=True,
    )

_spec = importlib.util.spec_from_file_location("graphify_ledger", GLOBAL_ENGINE)
_ledger_engine = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _ledger_engine
assert _spec.loader is not None
_spec.loader.exec_module(_ledger_engine)
Attempt = _ledger_engine.Attempt
ast_semantic_ratio = _ledger_engine.ast_semantic_ratio
build_attempt = _ledger_engine.build_attempt
cost_by_backend = _ledger_engine.cost_by_backend
cost_by_file = _ledger_engine.cost_by_file
cost_by_period = _ledger_engine.cost_by_period
load_ledger = _ledger_engine.load_ledger
record_attempts = _ledger_engine.record_attempts
top_cost_files = _ledger_engine.top_cost_files


def test_reads_pre_phase3_cost_json_without_error(tmp_path: Path) -> None:
    legacy = {
        "runs": [
            {"date": "2026-09-12T22:50:47Z", "input_tokens": 0, "output_tokens": 0, "files": 18}
        ],
        "total_input_tokens": 11335,
        "total_output_tokens": 1805,
    }
    cost_path = tmp_path / "cost.json"
    cost_path.write_text(json.dumps(legacy), encoding="utf-8")

    ledger = load_ledger(cost_path)
    assert ledger["runs"] == legacy["runs"]
    assert ledger["attempts"] == []
    assert ledger["total_input_tokens"] == 11335


def test_record_attempts_preserves_existing_runs_untouched(tmp_path: Path) -> None:
    legacy = {
        "runs": [{"date": "x", "input_tokens": 5, "output_tokens": 1, "files": 1}],
        "total_input_tokens": 5,
        "total_output_tokens": 1,
    }
    cost_path = tmp_path / "cost.json"
    cost_path.write_text(json.dumps(legacy), encoding="utf-8")

    attempt = Attempt(
        date="2026-09-14T00:00:00Z",
        project="studio-os",
        files=["a.py"],
        backend="ast",
        processing_type="ast",
        outcome="success",
        input_tokens=0,
        output_tokens=0,
        tokens_status="measured",
    )
    ledger = record_attempts(cost_path, [attempt])
    assert ledger["runs"] == legacy["runs"]
    assert len(ledger["attempts"]) == 1
    reloaded = json.loads(cost_path.read_text(encoding="utf-8"))
    assert reloaded["runs"] == legacy["runs"]


def test_unmeasured_tokens_never_become_zero(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "doc.md").write_text("hello", encoding="utf-8")
    cost_path = tmp_path / "cost.json"

    attempt = build_attempt(
        project="studio-os",
        files=["doc.md"],
        root=root,
        backend="gemini",
        processing_type="semantic",
        outcome="error",
        input_tokens=None,
        output_tokens=None,
        error="timeout",
    )
    assert attempt.tokens_status == "unmeasured"

    ledger = record_attempts(cost_path, [attempt])
    assert ledger["total_input_tokens"] == 0  # untouched by the unmeasured attempt
    entry = ledger["attempts"][0]
    assert entry["input_tokens"] is None
    assert entry["output_tokens"] is None
    assert entry["tokens_status"] == "unmeasured"
    assert entry["content_hashes"]["doc.md"].startswith("sha256:")


def test_cost_by_file_and_backend_aggregate_measured_attempts_only() -> None:
    ledger = {
        "attempts": [
            {
                "files": ["a.py", "b.py"],
                "backend": "ast",
                "processing_type": "ast",
                "tokens_status": "measured",
                "input_tokens": 0,
                "output_tokens": 0,
            },
            {
                "files": ["c.md"],
                "backend": "gemini",
                "processing_type": "semantic",
                "tokens_status": "measured",
                "input_tokens": 100,
                "output_tokens": 20,
            },
            {
                "files": ["d.md"],
                "backend": "gemini",
                "processing_type": "semantic",
                "tokens_status": "unmeasured",
                "input_tokens": None,
                "output_tokens": None,
            },
        ]
    }
    by_file = cost_by_file(ledger)
    assert by_file["c.md"]["input_tokens"] == 100
    assert by_file["d.md"]["unmeasured_attempts"] == 1
    assert (
        by_file["d.md"]["input_tokens"] == 0
    )  # aggregate of zero measured attempts, not a fabricated cost

    by_backend = cost_by_backend(ledger)
    assert by_backend["gemini"]["input_tokens"] == 100
    assert by_backend["gemini"]["unmeasured_attempts"] == 1
    assert by_backend["ast"]["attempts"] == 1


def test_cost_by_period_buckets_by_day() -> None:
    ledger = {
        "attempts": [
            {
                "date": "2026-09-12T10:00:00Z",
                "files": ["a"],
                "tokens_status": "measured",
                "input_tokens": 10,
                "output_tokens": 1,
            },
            {
                "date": "2026-09-12T20:00:00Z",
                "files": ["b"],
                "tokens_status": "measured",
                "input_tokens": 5,
                "output_tokens": 1,
            },
            {
                "date": "2026-09-13T09:00:00Z",
                "files": ["c"],
                "tokens_status": "measured",
                "input_tokens": 1,
                "output_tokens": 1,
            },
        ]
    }
    by_day = cost_by_period(ledger, "day")
    assert by_day["2026-09-12"]["input_tokens"] == 15
    assert by_day["2026-09-13"]["input_tokens"] == 1


def test_ast_semantic_ratio_counts_distinct_files() -> None:
    ledger = {
        "attempts": [
            {"processing_type": "ast", "files": ["a.py", "b.py"]},
            {"processing_type": "semantic", "files": ["c.md"]},
            {"processing_type": "sidecar", "files": ["d.gd"]},
        ]
    }
    ratio = ast_semantic_ratio(ledger)
    assert ratio["ast_files"] == 2
    assert ratio["semantic_files"] == 2
    assert ratio["ast_to_semantic_ratio"] == 1.0


def test_top_cost_files_orders_by_total_tokens() -> None:
    ledger = {
        "attempts": [
            {
                "files": ["small.md"],
                "tokens_status": "measured",
                "input_tokens": 5,
                "output_tokens": 1,
            },
            {
                "files": ["big.md"],
                "tokens_status": "measured",
                "input_tokens": 500,
                "output_tokens": 50,
            },
        ]
    }
    top = top_cost_files(ledger, n=1)
    assert top == [("big.md", 550)]
