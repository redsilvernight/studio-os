from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from studio_client.usage.collectors import (
    ClaudeCodeCollector,
    CollectedUsage,
    CollectorDiagnostic,
    CollectorRegistry,
    RunObservation,
)
from studio_client.usage.collectors.claude_code import find_result_document
from studio_contracts.usage import CacheTokenScope, MeasurementCoverage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "usage" / "claude_code" / "2.1.287"
MEASURED = MeasurementCoverage.MEASURED
UNKNOWN = MeasurementCoverage.UNKNOWN


def _run(
    output: str,
    *,
    harness: str = "claude-code",
    truncated: bool = False,
    timed_out: bool = False,
    duration: float | None = 10.3834,
) -> RunObservation:
    start = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
    return RunObservation(
        harness_id=harness,
        output=output,
        truncated=truncated,
        exit_code=None if timed_out else 0,
        timed_out=timed_out,
        cancelled=False,
        started_at=start,
        finished_at=start + timedelta(seconds=duration or 0),
        duration_seconds=duration,
    )


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _collect(name: str, **kwargs: object) -> CollectedUsage:
    return CollectorRegistry().collect(_run(_fixture(name), **kwargs))  # type: ignore[arg-type]


def test_success_reads_every_counter_from_the_result_document() -> None:
    collected = _collect("success.json")
    metrics = collected.metrics

    assert collected.collector == "studio-claude-code"
    assert collected.collector_version == "1.0.0"
    assert collected.diagnostics == ()
    assert (metrics.tokens_in.value, metrics.tokens_in.coverage) == (2, MEASURED)
    assert (metrics.tokens_out.value, metrics.tokens_out.coverage) == (4, MEASURED)
    assert metrics.tokens_cached.value == 32926
    assert metrics.cached_tokens_scope is CacheTokenScope.ADDITIONAL_TO_INPUT
    assert metrics.total_tokens == 2 + 4 + 32926
    assert metrics.cost.value == Decimal("0.26349599999999995")
    assert metrics.cost.currency == "USD"
    assert metrics.cost.coverage is MEASURED
    assert metrics.duration.value == Decimal("10.383")
    assert collected.model == "claude-opus-5-5"
    assert collected.provider == "anthropic"
    assert collected.result_text == "OK"


def test_cache_reads_and_creations_are_summed_apart_from_input() -> None:
    metrics = _collect("success_cache_read.json").metrics
    assert metrics.tokens_cached.value == 11973 + 23184
    assert metrics.tokens_in.value == 2


def test_error_result_behind_merged_stderr_is_still_measured() -> None:
    collected = _collect("error_unrecognized_model.txt")
    assert collected.diagnostics == (CollectorDiagnostic.HARNESS_ERROR_RESULT,)
    assert collected.metrics.tokens_in.coverage is MEASURED
    assert collected.metrics.tokens_in.value == 0
    assert collected.metrics.cost.value == Decimal(0)
    assert collected.model is None


def test_stream_json_uses_the_final_result_line() -> None:
    collected = _collect("stream.jsonl")
    assert collected.diagnostics == ()
    assert collected.metrics.tokens_cached.value == 11973 + 23184


def test_missing_usage_stays_unknown_never_zero() -> None:
    collected = _collect("no_usage.json")
    metrics = collected.metrics
    assert set(collected.diagnostics) == {
        CollectorDiagnostic.USAGE_MISSING,
        CollectorDiagnostic.COST_MISSING,
    }
    for measure in (metrics.tokens_in, metrics.tokens_out, metrics.tokens_cached, metrics.cost):
        assert measure.coverage is UNKNOWN
        assert measure.value is None
    assert metrics.total_tokens is None
    assert metrics.duration.coverage is MEASURED


def test_corrupted_output_degrades_with_a_stable_reason() -> None:
    collected = _collect("corrupted.json")
    assert collected.diagnostics == (CollectorDiagnostic.CORRUPTED_OUTPUT,)
    assert collected.metrics.tokens_in.coverage is UNKNOWN
    assert collected.metrics.duration.coverage is MEASURED


def test_truncated_capture_is_reported_as_truncated() -> None:
    collected = _collect("corrupted.json", truncated=True)
    assert collected.diagnostics == (CollectorDiagnostic.OUTPUT_TRUNCATED,)


def test_future_schema_keeps_tokens_and_cost_unknown() -> None:
    collected = _collect("future_schema.json")
    assert CollectorDiagnostic.USAGE_MISSING in collected.diagnostics
    assert CollectorDiagnostic.COST_MISSING in collected.diagnostics
    assert collected.metrics.cost.coverage is UNKNOWN
    assert collected.metrics.tokens_out.coverage is UNKNOWN
    assert collected.model == "claude-opus-5-5"


@pytest.mark.parametrize(
    ("output", "reason"),
    [
        ("", CollectorDiagnostic.OUTPUT_EMPTY),
        ("plain text answer\n", CollectorDiagnostic.NO_RESULT_DOCUMENT),
        ('{"type": "assistant"}', CollectorDiagnostic.UNSUPPORTED_SCHEMA),
        ("[1, 2]", CollectorDiagnostic.UNSUPPORTED_SCHEMA),
    ],
)
def test_unreadable_outputs_map_to_stable_reasons(output: str, reason: CollectorDiagnostic) -> None:
    assert find_result_document(output)[1] is reason


def test_renamed_or_invalid_counters_are_never_coerced() -> None:
    document = json.loads(_fixture("success.json"))
    document["usage"]["output_tokens"] = -1
    del document["usage"]["cache_read_input_tokens"]
    document["total_cost_usd"] = "free"
    collected = ClaudeCodeCollector().collect(_run(json.dumps(document)))
    assert CollectorDiagnostic.INVALID_COUNTER in collected.diagnostics
    assert CollectorDiagnostic.UNSUPPORTED_SCHEMA in collected.diagnostics
    assert collected.metrics.tokens_out.coverage is UNKNOWN
    assert collected.metrics.tokens_cached.coverage is UNKNOWN
    assert collected.metrics.tokens_in.value == 2
    assert collected.metrics.cost.coverage is UNKNOWN


def test_several_models_pick_the_costliest_and_say_so() -> None:
    document = json.loads(_fixture("success.json"))
    document["modelUsage"]["claude-haiku-5"] = {"costUSD": 0.001, "provider": "firstParty"}
    collected = ClaudeCodeCollector().collect(_run(json.dumps(document)))
    assert collected.model == "claude-opus-5-5"
    assert CollectorDiagnostic.MULTIPLE_MODELS in collected.diagnostics


@pytest.mark.parametrize("harness", ["codex", "opencode", "some-new-harness"])
def test_uncertified_harness_keeps_duration_and_marks_the_rest_unknown(harness: str) -> None:
    collected = CollectorRegistry().collect(_run(_fixture("success.json"), harness=harness))
    assert collected.collector == "studio-runner"
    assert collected.diagnostics == (CollectorDiagnostic.UNCERTIFIED_HARNESS,)
    assert collected.coverage == {
        "tokens_in": UNKNOWN,
        "tokens_out": UNKNOWN,
        "tokens_cached": UNKNOWN,
        "cost": UNKNOWN,
        "duration": MEASURED,
    }


def test_interrupted_run_without_timing_is_flagged() -> None:
    collected = CollectorRegistry().collect(_run("", timed_out=True, duration=None))
    assert CollectorDiagnostic.RUN_INTERRUPTED in collected.diagnostics
    assert CollectorDiagnostic.TIMING_MISSING in collected.diagnostics
    assert collected.metrics.duration.coverage is UNKNOWN


def test_a_crashing_collector_degrades_instead_of_raising() -> None:
    class Boom:
        collector_id = "boom"
        collector_version = "0"
        harness_ids = frozenset({"claude-code"})

        def collect(self, run: RunObservation) -> CollectedUsage:
            raise RuntimeError("parser bug")

    collected = CollectorRegistry([Boom()]).collect(_run(_fixture("success.json")))
    assert collected.diagnostics == (CollectorDiagnostic.COLLECTOR_FAILED,)
    assert collected.metrics.duration.coverage is MEASURED
    assert collected.metrics.cost.coverage is UNKNOWN
