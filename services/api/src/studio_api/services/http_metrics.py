"""Hourly HTTP counters (operator console fiche C1/C3).

The console needs "5xx error rate", "median response time" and "API calls"
without an observability stack. A middleware feeds an in-process, per-hour
collector; a background task persists completed hours through the existing
`infra_measurements` table (no new table, no migration):

- `http_requests` — requests served in the hour,
- `http_requests_5xx` — among them, 5xx responses (and unhandled errors),
- `http_latency_p50_ms` / `http_latency_p95_ms` — nearest-rank percentiles.

Rows carry `subject = "YYYY-MM-DDTHH"` and `measured_at` = the hour start, so a
reader can sum/aggregate per hour deterministically. Probes (`/healthz`,
`/metrics`, `/version`, docs) are not counted: these are not client API calls.
Percentile samples are capped per hour (20 000) so a flood cannot grow memory
without bound; past the cap the hour keeps counting requests/errors and freezes
its percentile sample.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.infra_measurement import InfraMeasurementModel
from studio_api.db.session import get_session_factory
from studio_api.settings import Settings

logger = logging.getLogger(__name__)

METRIC_REQUESTS = "http_requests"
METRIC_ERRORS_5XX = "http_requests_5xx"
METRIC_LATENCY_P50 = "http_latency_p50_ms"
METRIC_LATENCY_P95 = "http_latency_p95_ms"

MAX_SAMPLES_PER_HOUR = 20_000
KEEP_HOURS = 48


def hour_of(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _percentile(sorted_values: list[float], percent: float) -> int:
    if not sorted_values:
        return 0
    rank = max(0, math.ceil(percent / 100 * len(sorted_values)) - 1)
    return int(round(sorted_values[rank]))


@dataclass
class HourBucket:
    hour: datetime
    requests: int = 0
    errors_5xx: int = 0
    durations_ms: list[float] = field(default_factory=list)

    @property
    def p50(self) -> int:
        return _percentile(sorted(self.durations_ms), 50)

    @property
    def p95(self) -> int:
        return _percentile(sorted(self.durations_ms), 95)

    def rows(self) -> list[InfraMeasurementModel]:
        subject = self.hour.strftime("%Y-%m-%dT%H")
        rows = [
            InfraMeasurementModel(
                metric=METRIC_REQUESTS,
                subject=subject,
                value=self.requests,
                measured_at=self.hour,
            ),
            InfraMeasurementModel(
                metric=METRIC_ERRORS_5XX,
                subject=subject,
                value=self.errors_5xx,
                measured_at=self.hour,
            ),
        ]
        if self.durations_ms:
            rows.append(
                InfraMeasurementModel(
                    metric=METRIC_LATENCY_P50,
                    subject=subject,
                    value=self.p50,
                    measured_at=self.hour,
                )
            )
            rows.append(
                InfraMeasurementModel(
                    metric=METRIC_LATENCY_P95,
                    subject=subject,
                    value=self.p95,
                    measured_at=self.hour,
                )
            )
        return rows


class HttpMetrics:
    def __init__(self) -> None:
        self.buckets: dict[datetime, HourBucket] = {}
        self.written: set[datetime] = set()

    def record(self, status_code: int, duration_ms: float, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(UTC)
        hour = hour_of(moment)
        bucket = self.buckets.setdefault(hour, HourBucket(hour=hour))
        bucket.requests += 1
        if status_code >= 500:
            bucket.errors_5xx += 1
        if len(bucket.durations_ms) < MAX_SAMPLES_PER_HOUR:
            bucket.durations_ms.append(duration_ms)

    def complete_buckets(self, *, now: datetime | None = None) -> list[HourBucket]:
        current = hour_of(now or datetime.now(UTC))
        return [
            bucket
            for hour, bucket in sorted(self.buckets.items())
            if hour < current and hour not in self.written
        ]

    def prune(self, *, now: datetime | None = None) -> None:
        cutoff = hour_of(now or datetime.now(UTC)) - timedelta(hours=KEEP_HOURS)
        self.buckets = {hour: bucket for hour, bucket in self.buckets.items() if hour >= cutoff}
        self.written = {hour for hour in self.written if hour >= cutoff}

    def reset(self) -> None:
        self.buckets.clear()
        self.written.clear()


METRICS = HttpMetrics()


async def flush(
    session: AsyncSession, metrics: HttpMetrics | None = None, *, now: datetime | None = None
) -> int:
    """Persist completed hours not written yet. Idempotent per process."""
    collector = metrics or METRICS
    buckets = collector.complete_buckets(now=now)
    rows: list[InfraMeasurementModel] = []
    for bucket in buckets:
        rows.extend(bucket.rows())
    if rows:
        session.add_all(rows)
        await session.commit()
        collector.written.update(bucket.hour for bucket in buckets)
    collector.prune(now=now)
    return len(rows)


async def run_forever(settings: Settings) -> None:
    interval = settings.http_measure_flush_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            async with get_session_factory()() as session:
                await flush(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the loop must survive any failure
            logger.warning("http metrics flush failed: %s", type(exc).__name__)
