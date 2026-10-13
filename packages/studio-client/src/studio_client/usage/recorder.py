"""Turns one launched run into a `UsageLedgerEntryCreate` queued in the outbox.

The entry is keyed by the launch (`task-launch.<id>`), so a resumed daemon or a
second collection of the same run replays the same fact instead of adding one.
Recording is best effort by construction: `record` never raises, a launch never
fails because its usage could not be measured.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from studio_contracts.task_launch import TaskLaunch
from studio_contracts.usage import UsageLedgerEntryCreate, UsageProvenance

from studio_client.usage import UsageWriteQueue
from studio_client.usage.collectors import CollectedUsage, CollectorRegistry, RunObservation

logger = logging.getLogger(__name__)


def launch_source_event_id(launch: TaskLaunch) -> str:
    return f"task-launch.{launch.id}"


def build_launch_entry(
    launch: TaskLaunch, run: RunObservation, collected: CollectedUsage
) -> UsageLedgerEntryCreate:
    finished = run.finished_at or datetime.now(UTC)
    started = run.started_at or finished
    return UsageLedgerEntryCreate(
        project_id=launch.project_id,
        machine_id=launch.machine_id,
        source_event_id=launch_source_event_id(launch),
        provenance=UsageProvenance(
            collector=collected.collector,
            collector_version=collected.collector_version,
            harness=launch.harness_id,
            harness_version=collected.harness_version,
            provider=collected.provider,
            model=collected.model,
        ),
        period_start=started,
        period_end=max(started, finished),
        task_id=launch.task_id,
        task_launch_id=launch.id,
        tokens_in=collected.metrics.tokens_in,
        tokens_out=collected.metrics.tokens_out,
        tokens_cached=collected.metrics.tokens_cached,
        cached_tokens_scope=collected.metrics.cached_tokens_scope,
        cost=collected.metrics.cost,
        duration=collected.metrics.duration,
    )


@dataclass(frozen=True)
class RecordedUsage:
    collected: CollectedUsage
    entry: UsageLedgerEntryCreate
    enqueued: bool


class LaunchUsageRecorder:
    def __init__(self, queue: UsageWriteQueue, registry: CollectorRegistry | None = None) -> None:
        self._queue = queue
        self._registry = registry or CollectorRegistry()

    @property
    def registry(self) -> CollectorRegistry:
        return self._registry

    def record(self, launch: TaskLaunch, run: RunObservation) -> RecordedUsage | None:
        try:
            collected = self._registry.collect(run)
            entry = build_launch_entry(launch, run, collected)
            key = uuid5(NAMESPACE_URL, f"studio:usage:{launch.machine_id}:{entry.source_event_id}")
            enqueued = self._queue.enqueue_entry(entry, idempotency_key=key)
        except Exception:  # noqa: BLE001
            logger.warning("usage recording failed for a launch", exc_info=True)
            return None
        if collected.diagnostics:
            logger.info(
                "usage collected with diagnostics: %s",
                ",".join(collected.diagnostics),
            )
        return RecordedUsage(collected=collected, entry=entry, enqueued=enqueued)
