"""The P16 before/after report is deterministic, reads the P00/P04/P07 blocks,
replays the shipped selection and degrades cleanly when latency is unmeasured."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import vault_eval_p16 as p16

ROOT = Path(__file__).resolve().parents[2]


def _copy_inputs(target: Path) -> None:
    shutil.copytree(ROOT / "tests" / "eval", target / "tests" / "eval")
    (target / "docs").mkdir()
    for relative in (p16.P00_RELATIVE_PATH, p16.P04_RELATIVE_PATH, p16.P07_RELATIVE_PATH):
        shutil.copy(ROOT / relative, target / relative)


def _latency_doc(verdict: str) -> str:
    payload = {
        "format": p16.LATENCY_FORMAT,
        "global": {"p50_ms": 40.0, "p95_ms": 90.0, "max_ms": 120.0},
        "threshold_p95_ms": 500,
        "verdict": verdict,
    }
    return "# Latence\n\n```json\n" + json.dumps(payload) + "\n```\n"


def _criterion(metrics: dict, number: int) -> str:
    return next(row["verdict"] for row in metrics["criteria"] if row["id"] == number)


def test_metrics_are_deterministic_and_cover_every_phase(tmp_path: Path) -> None:
    _copy_inputs(tmp_path)
    first = p16.compute_metrics(tmp_path)
    second = p16.compute_metrics(tmp_path)
    assert first == second
    assert set(first["phases"]) == set(p16.PHASES)
    assert first["query_ids"]["count"] == 45
    assert _criterion(first, 1) == p16.MET


def test_recall_gap_accounts_for_the_true_positive_delta(tmp_path: Path) -> None:
    _copy_inputs(tmp_path)
    metrics = p16.compute_metrics(tmp_path)
    gap = metrics["recall_gap_vs_p00"]
    assert gap["lost_total"] - gap["gained_total"] == (
        gap["true_positives_p00"] - gap["true_positives_p16"]
    )
    assert metrics["lexical_ceiling"]["unreachable_total"] >= 0
    assert _criterion(metrics, 2) in (p16.MET, p16.MET_EXPLAINED)


def test_recall_changes_lists_lost_and_gained() -> None:
    before = {
        "per_query": [
            {"id": "q1", "objective": "o", "retrieved": ["A", "B"], "expected": ["A", "C"]},
            {"id": "q2", "objective": "o", "retrieved": ["X"], "expected": ["X"]},
        ]
    }
    after = {
        "per_query": [
            {"id": "q1", "objective": "o", "retrieved": ["C"], "expected": ["A", "C"]},
            {"id": "q2", "objective": "o", "retrieved": ["X"], "expected": ["X"]},
        ]
    }
    assert p16.recall_changes(before, after) == [
        {"id": "q1", "objective": "o", "lost": ["A"], "gained": ["C"]}
    ]


def test_missing_latency_fails_criterion_3_but_not_check(tmp_path: Path) -> None:
    _copy_inputs(tmp_path)
    assert p16.main(["--root", str(tmp_path), "--apply"]) == 0
    assert p16.main(["--root", str(tmp_path), "--check"]) == 0
    report = (tmp_path / p16.REPORT_RELATIVE_PATH).read_text(encoding="utf-8")
    assert "Latence non mesurée" in report
    metrics = json.loads(p16._extract_metrics(report))
    assert metrics["latency"] is None
    assert _criterion(metrics, 3) == p16.NOT_MET


@pytest.mark.parametrize(("verdict", "expected"), [("acceptable", "met"), ("too_slow", "not_met")])
def test_latency_block_drives_criterion_3(tmp_path: Path, verdict: str, expected: str) -> None:
    _copy_inputs(tmp_path)
    (tmp_path / p16.LATENCY_RELATIVE_PATH).write_text(_latency_doc(verdict), encoding="utf-8")
    metrics = p16.compute_metrics(tmp_path)
    assert metrics["latency"]["p95_ms"] == 90.0
    assert _criterion(metrics, 3) == expected


def test_check_detects_stale_report(tmp_path: Path) -> None:
    _copy_inputs(tmp_path)
    assert p16.main(["--root", str(tmp_path), "--check"]) == 1
    assert p16.main(["--root", str(tmp_path), "--apply"]) == 0
    (tmp_path / p16.LATENCY_RELATIVE_PATH).write_text(_latency_doc("acceptable"), encoding="utf-8")
    assert p16.main(["--root", str(tmp_path), "--check"]) == 1


def test_wrong_latency_format_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "latency.md"
    path.write_text('```json\n{"format": "other"}\n```\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected format"):
        p16.load_latency(path)


def test_committed_report_matches_the_current_inputs() -> None:
    assert p16.main(["--root", str(ROOT), "--check"]) == 0
