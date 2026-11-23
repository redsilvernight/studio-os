"""Hourly HTTP counters feeding the operator console (fiche C1/C3).

No database: the collector is in-process; persistence is checked against a
stub session that records the `infra_measurements` rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request, Response
from starlette.responses import JSONResponse
from studio_api.middleware import HttpMetricsMiddleware
from studio_api.services import http_metrics as metrics_module


class _StubSession:
    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.commits = 0

    def add_all(self, rows: list[Any]) -> None:
        self.rows.extend(rows)

    async def commit(self) -> None:
        self.commits += 1


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
        }
    )


def test_requests_errors_and_percentiles_are_bucketed_by_hour() -> None:
    collector = metrics_module.HttpMetrics()
    base = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
    for index in range(1, 101):
        collector.record(500 if index <= 5 else 200, index, now=base + timedelta(minutes=1))

    bucket = collector.buckets[metrics_module.hour_of(base)]
    assert bucket.requests == 100
    assert bucket.errors_5xx == 5
    assert bucket.p50 == 50
    assert bucket.p95 == 95


async def test_completed_hours_are_flushed_once_through_infra_measurements() -> None:
    collector = metrics_module.HttpMetrics()
    base = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
    collector.record(200, 42, now=base + timedelta(minutes=5))
    collector.record(503, 84, now=base + timedelta(minutes=6))
    # The hour is still running: nothing to persist yet.
    assert collector.complete_buckets(now=base + timedelta(minutes=30)) == []

    session = _StubSession()
    written = await metrics_module.flush(
        session, collector, now=datetime(2026, 11, 21, 11, 1, tzinfo=UTC)
    )
    assert written == 4
    assert session.commits == 1
    by_metric = {row.metric: row for row in session.rows}
    assert by_metric[metrics_module.METRIC_REQUESTS].value == 2
    assert by_metric[metrics_module.METRIC_ERRORS_5XX].value == 1
    assert by_metric[metrics_module.METRIC_LATENCY_P50].value == 42
    assert by_metric[metrics_module.METRIC_LATENCY_P95].value == 84
    assert by_metric[metrics_module.METRIC_REQUESTS].subject == "2026-11-21T10"
    assert by_metric[metrics_module.METRIC_REQUESTS].measured_at == base

    again = _StubSession()
    assert (
        await metrics_module.flush(again, collector, now=datetime(2026, 11, 21, 11, 2, tzinfo=UTC))
        == 0
    )


async def test_middleware_counts_api_calls_and_5xx_but_skips_probes() -> None:
    metrics_module.METRICS.reset()
    middleware = HttpMetricsMiddleware(app=None)  # type: ignore[arg-type]

    async def call_503(_: Request) -> Response:
        return Response(status_code=503)

    await middleware.dispatch(_request("/api/v1/dashboard"), call_503)
    await middleware.dispatch(_request("/healthz"), call_503)

    assert len(metrics_module.METRICS.buckets) == 1
    bucket = next(iter(metrics_module.METRICS.buckets.values()))
    assert bucket.requests == 1
    assert bucket.errors_5xx == 1


async def test_middleware_counts_an_unhandled_error_as_a_5xx() -> None:
    metrics_module.METRICS.reset()
    middleware = HttpMetricsMiddleware(app=None)  # type: ignore[arg-type]

    async def boom(_: Request) -> Response:
        raise RuntimeError("boom")

    try:
        await middleware.dispatch(_request("/api/v1/tasks"), boom)
    except RuntimeError:
        pass
    else:  # pragma: no cover - the error must propagate
        raise AssertionError("the exception must propagate")

    bucket = next(iter(metrics_module.METRICS.buckets.values()))
    assert bucket.errors_5xx == 1
    assert bucket.requests == 1


async def test_success_is_counted_without_errors() -> None:
    metrics_module.METRICS.reset()
    middleware = HttpMetricsMiddleware(app=None)  # type: ignore[arg-type]

    async def ok(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    await middleware.dispatch(_request("/api/v1/version"), ok)
    bucket = next(iter(metrics_module.METRICS.buckets.values()))
    assert bucket.requests == 1
    assert bucket.errors_5xx == 0
