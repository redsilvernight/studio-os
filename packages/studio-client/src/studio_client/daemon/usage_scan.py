"""Daemon loop that keeps the local usage readers running in the background."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from studio_client.usage.local.scanner import LocalUsageScanner

logger = logging.getLogger(__name__)


class UsageScanLoop:
    """Scans local harness stores on an interval, tolerating every failure.

    A scan never blocks the daemon's other services: parsing runs in worker
    threads and an exception is logged, not propagated — a broken harness
    format must never stop the daemon or the outbox replay."""

    def __init__(
        self,
        scanner: LocalUsageScanner,
        interval_seconds: float,
        *,
        stop_event: asyncio.Event,
        stopped: Callable[[], bool] | None = None,
        initial_delay_seconds: float | None = None,
    ) -> None:
        self._scanner = scanner
        self._interval = max(1.0, interval_seconds)
        self._stop_event = stop_event
        self._stopped = stopped or (lambda: False)
        self._initial_delay = (
            min(self._interval, 15.0)
            if initial_delay_seconds is None
            else max(0.0, initial_delay_seconds)
        )

    async def run(self) -> None:
        delay = self._initial_delay
        while not self._stopped() and not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                return
            except TimeoutError:
                pass
            try:
                report = await self._scanner.scan()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("local usage scan failed", exc_info=True)
            else:
                if report.entries or report.corrections or report.unattributed:
                    logger.info(
                        "local usage scan: %d session(s), %d entr(y/ies), "
                        "%d correction(s), %d unattributed",
                        report.parsed,
                        report.entries,
                        report.corrections,
                        report.unattributed,
                    )
            delay = self._interval
