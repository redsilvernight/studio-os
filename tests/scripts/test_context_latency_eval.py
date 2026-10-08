"""Percentiles, verdict and report rendering of the context latency evaluation,
without any database."""

from __future__ import annotations

import pytest

from scripts import context_latency_eval as cl

ENVIRONMENT = {"os": "TestOS-1.0", "python": "3.12.0", "postgresql": "16.4"}
PARAMETERS = {
    "limit": 5,
    "max_chars": 12000,
    "warmup_passes": 2,
    "samples_per_query": 4,
    "decisions": 3,
    "vault_notes": 3,
}


def _metrics(samples: dict[str, list[float]]) -> dict[str, object]:
    return cl.build_metrics(samples, environment=ENVIRONMENT, parameters=PARAMETERS)


def test_percentile_interpolates_linearly() -> None:
    values = [40.0, 10.0, 30.0, 20.0]
    assert cl.percentile(values, 0.0) == 10.0
    assert cl.percentile(values, 50.0) == 25.0
    assert cl.percentile(values, 100.0) == 40.0
    assert cl.percentile(values, 95.0) == pytest.approx(38.5)
    assert cl.percentile([7.0], 95.0) == 7.0


def test_percentile_rejects_empty_and_out_of_range() -> None:
    with pytest.raises(ValueError):
        cl.percentile([], 50.0)
    with pytest.raises(ValueError):
        cl.percentile([1.0], 101.0)


def test_summarize_rounds_stats() -> None:
    stats = cl.summarize([1.0, 2.0, 3.0, 4.0])
    assert stats == {"p50_ms": 2.5, "p95_ms": 3.85, "max_ms": 4.0, "mean_ms": 2.5}


def test_verdict_threshold_is_inclusive() -> None:
    assert cl.verdict(cl.THRESHOLD_P95_MS) == cl.VERDICT_ACCEPTABLE
    assert cl.verdict(cl.THRESHOLD_P95_MS + 0.01) == cl.VERDICT_TOO_SLOW


def test_build_metrics_aggregates_all_samples() -> None:
    metrics = _metrics({"q01": [10.0, 20.0, 30.0, 40.0], "q02": [300.0, 300.0, 300.0, 300.0]})
    assert metrics["format"] == cl.METRICS_FORMAT
    assert metrics["queries"] == ["q01", "q02"]
    assert metrics["global"]["max_ms"] == 300.0
    assert metrics["global"]["mean_ms"] == 162.5
    assert metrics["verdict"] == cl.VERDICT_TOO_SLOW
    assert metrics["threshold_p95_ms"] == cl.THRESHOLD_P95_MS
    assert [row["id"] for row in metrics["per_query"]] == ["q01", "q02"]


def test_render_round_trips_and_validates() -> None:
    metrics = _metrics({"q01": [10.0, 20.0, 30.0, 40.0], "q02": [5.0, 6.0, 7.0, 8.0]})
    report = cl.render_markdown(metrics)
    assert cl.COMMAND in report
    assert "TestOS-1.0" in report and "3.12.0" in report and "16.4" in report
    assert "| q01 | 25.00 | 38.50 | 40.00 | 25.00 |" in report
    assert "**acceptable**" in report
    published = cl.extract_metrics(report)
    assert published == metrics
    assert cl.validate_metrics(published, ["q02", "q01"]) == []


def test_validate_reports_structural_errors() -> None:
    metrics = _metrics({"q01": [1.0, 2.0]})
    metrics["verdict"] = "fast"
    del metrics["global"]["p95_ms"]
    errors = cl.validate_metrics(metrics, ["q01", "q02"])
    assert "global.p95_ms: missing or not a number" in errors
    assert "verdict: unexpected value 'fast'" in errors
    assert "queries: ids differ from the query set" in errors
    assert "per_query: ids differ from the query set" in errors


def test_extract_rejects_report_without_markers() -> None:
    with pytest.raises(ValueError):
        cl.extract_metrics("# no metrics here")
