from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

SleepFn = Callable[[float], Awaitable[None]]


class PollingWatcher(ABC):
    """Shared poll/stop loop for Git and Godot watchers. Mirrors
    `daemon.heartbeat.HeartbeatDaemon`'s shutdown behaviour: `request_stop()`
    only gates the wait between polls, never cancels a poll already in
    flight, and `_wait` returns as soon as a stop is requested instead of
    sleeping out the full interval. A single failed poll (git/tasklist
    unavailable, transient FS error) is logged and skipped rather than
    crashing the loop — offline/degraded tolerance applies to watchers too
    (`.claude/rules/offline-sync.md`)."""

    def __init__(self, *, interval_seconds: float, sleep: SleepFn | None = None) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._interval_seconds = interval_seconds
        self._sleep = sleep or asyncio.sleep
        self._stop_event = asyncio.Event()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def request_stop(self) -> None:
        self._stop_event.set()

    @abstractmethod
    async def poll_once(self) -> None: ...

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.poll_once()
            except Exception:
                logger.warning("%s poll failed", type(self).__name__, exc_info=True)
            if self._stop_event.is_set():
                break
            await self._wait(self._interval_seconds)

    async def _wait(self, delay: float) -> None:
        stop_wait = asyncio.ensure_future(self._stop_event.wait())
        sleep_wait = asyncio.ensure_future(self._sleep(delay))
        try:
            await asyncio.wait({stop_wait, sleep_wait}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (stop_wait, sleep_wait):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stop_wait, sleep_wait, return_exceptions=True)
