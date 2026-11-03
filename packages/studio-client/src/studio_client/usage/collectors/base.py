"""Shared shapes of the local usage collectors (DEC-0197, Bloc B).

A collector turns what a launched harness printed into a `CollectedUsage`:
measures with their coverage, the provenance of the collector, and stable
diagnostic reasons. A collector never raises on a bad output and never invents
a value: whatever it cannot read stays `unknown`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from studio_contracts.usage import (
    DurationMeasurement,
    MeasurementCoverage,
    UsageMetrics,
)

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_:@/\[\]-]{0,127}$")
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")


class CollectorDiagnostic(StrEnum):
    """Stable reasons a collector attaches to its result. Never a raw message,
    never an excerpt of the output."""

    UNCERTIFIED_HARNESS = "uncertified_harness"
    OUTPUT_EMPTY = "output_empty"
    OUTPUT_TRUNCATED = "output_truncated"
    NO_RESULT_DOCUMENT = "no_result_document"
    CORRUPTED_OUTPUT = "corrupted_output"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    USAGE_MISSING = "usage_missing"
    COST_MISSING = "cost_missing"
    INVALID_COUNTER = "invalid_counter"
    MULTIPLE_MODELS = "multiple_models"
    HARNESS_ERROR_RESULT = "harness_error_result"
    RUN_INTERRUPTED = "run_interrupted"
    TIMING_MISSING = "timing_missing"
    COLLECTOR_FAILED = "collector_failed"


@dataclass(frozen=True)
class RunObservation:
    """What the runner observed of one harness process. `output` is bounded
    and not redacted: a collector reads counters from it and never forwards it."""

    harness_id: str
    output: str
    truncated: bool
    exit_code: int | None
    timed_out: bool
    cancelled: bool
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None

    @property
    def interrupted(self) -> bool:
        return self.timed_out or self.cancelled


@dataclass(frozen=True)
class CollectedUsage:
    collector: str
    collector_version: str
    harness: str
    metrics: UsageMetrics
    diagnostics: tuple[CollectorDiagnostic, ...] = ()
    harness_version: str | None = None
    provider: str | None = None
    model: str | None = None
    result_text: str | None = None

    @property
    def coverage(self) -> dict[str, MeasurementCoverage]:
        return self.metrics.coverage_by_metric


class UsageCollector(Protocol):
    collector_id: str
    collector_version: str
    harness_ids: frozenset[str]

    def collect(self, run: RunObservation) -> CollectedUsage: ...


def measured_duration(run: RunObservation) -> DurationMeasurement:
    """The runner's own wall-clock measure of the process: measured whatever the
    harness printed, unknown only when the runner had no timing."""
    if run.duration_seconds is None or run.duration_seconds < 0:
        return DurationMeasurement()
    value = Decimal(str(run.duration_seconds)).quantize(Decimal("0.001"))
    return DurationMeasurement(value=value, coverage=MeasurementCoverage.MEASURED)


def safe_model(value: object) -> str | None:
    if isinstance(value, str) and _MODEL_RE.match(value):
        return value
    return None


def safe_tag(value: object) -> str | None:
    if isinstance(value, str) and _TAG_RE.match(value):
        return value
    return None
