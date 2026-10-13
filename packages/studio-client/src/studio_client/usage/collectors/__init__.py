"""Local usage collectors, versioned per harness (DEC-0197).

`CollectorRegistry.collect` is the only entry point a runner needs: it picks
the certified collector of the harness, falls back to the unmetered collector
for any other harness, and never raises — a collector bug degrades to the
runner's own duration plus a `collector_failed` diagnostic.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from studio_contracts.usage import UsageMetrics

from studio_client.usage.collectors.base import (
    CollectedUsage,
    CollectorDiagnostic,
    RunObservation,
    UsageCollector,
    measured_duration,
)
from studio_client.usage.collectors.claude_code import ClaudeCodeCollector

logger = logging.getLogger(__name__)

UNMETERED_COLLECTOR_ID = "studio-runner"
UNMETERED_COLLECTOR_VERSION = "1.0.0"

__all__ = [
    "ClaudeCodeCollector",
    "CollectedUsage",
    "CollectorDiagnostic",
    "CollectorRegistry",
    "RunObservation",
    "UnmeteredCollector",
    "UsageCollector",
]


class UnmeteredCollector:
    """Degraded mode for a harness without a certified collector: tokens and
    cost stay `unknown`, the duration is the runner's own measure."""

    collector_id = UNMETERED_COLLECTOR_ID
    collector_version = UNMETERED_COLLECTOR_VERSION
    harness_ids: frozenset[str] = frozenset()

    def collect(
        self,
        run: RunObservation,
        *,
        reason: CollectorDiagnostic = CollectorDiagnostic.UNCERTIFIED_HARNESS,
    ) -> CollectedUsage:
        diagnostics = [reason]
        if run.interrupted:
            diagnostics.append(CollectorDiagnostic.RUN_INTERRUPTED)
        duration = measured_duration(run)
        if run.duration_seconds is None:
            diagnostics.append(CollectorDiagnostic.TIMING_MISSING)
        return CollectedUsage(
            collector=self.collector_id,
            collector_version=self.collector_version,
            harness=run.harness_id,
            metrics=UsageMetrics(duration=duration),
            diagnostics=tuple(diagnostics),
        )


DEFAULT_COLLECTORS: tuple[UsageCollector, ...] = (ClaudeCodeCollector(),)


class CollectorRegistry:
    def __init__(self, collectors: Iterable[UsageCollector] = DEFAULT_COLLECTORS) -> None:
        self._by_harness: dict[str, UsageCollector] = {}
        for collector in collectors:
            for harness_id in collector.harness_ids:
                self._by_harness[harness_id] = collector
        self._fallback = UnmeteredCollector()

    def certified(self, harness_id: str) -> bool:
        return harness_id in self._by_harness

    def for_harness(self, harness_id: str) -> UsageCollector:
        return self._by_harness.get(harness_id, self._fallback)

    def collect(self, run: RunObservation) -> CollectedUsage:
        collector = self._by_harness.get(run.harness_id)
        if collector is None:
            return self._fallback.collect(run)
        try:
            return collector.collect(run)
        except Exception:  # noqa: BLE001
            logger.warning("usage collector %s failed", collector.collector_id, exc_info=True)
            return self._fallback.collect(run, reason=CollectorDiagnostic.COLLECTOR_FAILED)
