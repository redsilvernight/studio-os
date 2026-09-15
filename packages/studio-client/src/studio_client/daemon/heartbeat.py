from __future__ import annotations

import argparse
import asyncio
import logging
import random
import signal
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.errors import StudioApiError
from studio_client.outbox import OutboxReplayer, OutboxStore, connect, default_outbox_path
from studio_client.retry import RetryPolicy
from studio_client.watchers import GitWatcher, GodotWatcher, PollingWatcher

logger = logging.getLogger(__name__)

SleepFn = Callable[[float], Awaitable[None]]


class HeartbeatDaemon:
    """Long-running loop maintaining this machine's online state (sous-etape
    6.2, docs/ROADMAP_STEP6_BREAKDOWN.md): sends a heartbeat via
    `StudioApiClient.send_heartbeat` at a jittered interval. `request_stop()`
    only gates the wait between iterations — a heartbeat already in flight
    always completes before `run()` returns.

    A successful heartbeat is this daemon's reconnection signal (sous-etape
    6.4): it is direct proof the server is reachable right now, so an
    optional `replayer` is drained immediately afterwards rather than the
    daemon tracking a separate "was offline" state that would only
    duplicate what the outbox's own per-row backoff already paces."""

    def __init__(
        self,
        client: StudioApiClient,
        config: ClientConfig,
        *,
        agent_id: UUID | None = None,
        interval_seconds: float | None = None,
        jitter_ratio: float | None = None,
        sleep: SleepFn | None = None,
        random_fn: Callable[[], float] | None = None,
        replayer: OutboxReplayer | None = None,
    ) -> None:
        if config.machine_id is None:
            raise ValueError("ClientConfig.machine_id must be set to run the heartbeat daemon")
        resolved_interval = (
            config.heartbeat_interval_seconds if interval_seconds is None else interval_seconds
        )
        resolved_jitter = config.heartbeat_jitter_ratio if jitter_ratio is None else jitter_ratio
        if resolved_interval <= 0:
            raise ValueError("interval_seconds must be positive")
        if not 0 <= resolved_jitter < 1:
            raise ValueError("jitter_ratio must be in [0, 1)")

        self._client = client
        self._machine_id = config.machine_id
        self._agent_id = agent_id
        self._interval_seconds = resolved_interval
        self._jitter_ratio = resolved_jitter
        self._sleep = sleep or asyncio.sleep
        self._random = random_fn or random.random
        self._replayer = replayer
        self._stop_event = asyncio.Event()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def request_stop(self) -> None:
        self._stop_event.set()

    def _next_delay(self) -> float:
        span = self._interval_seconds * self._jitter_ratio
        return self._interval_seconds + (self._random() * 2 - 1) * span

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._client.send_heartbeat(self._machine_id, self._agent_id)
            except StudioApiError:
                logger.warning("heartbeat failed", exc_info=True)
            else:
                await self._replay_outbox()
            if self._stop_event.is_set():
                break
            await self._wait(self._next_delay())

    async def _replay_outbox(self) -> None:
        if self._replayer is None:
            return
        try:
            await self._replayer.replay_ready()
        except StudioApiError:
            logger.warning("outbox replay failed", exc_info=True)

    async def _wait(self, delay: float) -> None:
        """Waits up to `delay`, but returns as soon as `request_stop()` is
        called instead of sleeping out the full (possibly ~minutes-long)
        interval — a plain `await self._sleep(delay)` would leave shutdown
        latency bounded only by the jittered interval, not by the signal."""
        stop_wait = asyncio.ensure_future(self._stop_event.wait())
        sleep_wait = asyncio.ensure_future(self._sleep(delay))
        try:
            await asyncio.wait({stop_wait, sleep_wait}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (stop_wait, sleep_wait):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stop_wait, sleep_wait, return_exceptions=True)


def install_signal_handlers(stop: Callable[[], None]) -> list[signal.Signals]:
    """Registers `stop` on SIGINT/SIGTERM where the interpreter exposes them.
    SIGTERM delivery is unreliable on Windows, but registering the handler is
    harmless there — returns only the signals actually installed."""
    installed: list[signal.Signals] = []
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, lambda *_: stop())
        except (ValueError, OSError):
            continue
        installed.append(sig)
    return installed


def build_watchers(config: ClientConfig, store: OutboxStore) -> list[PollingWatcher]:
    """A watcher only starts when both its repo/pattern and its
    `*_project_id` are configured — either alone leaves it disabled."""
    if config.machine_id is None:
        return []
    watchers: list[PollingWatcher] = []
    if config.git_watch_repo_path is not None and config.git_watch_project_id is not None:
        watchers.append(
            GitWatcher(
                repo_path=config.git_watch_repo_path,
                project_id=config.git_watch_project_id,
                machine_id=config.machine_id,
                outbox=store,
                interval_seconds=config.git_watch_interval_seconds,
            )
        )
    if config.godot_watch_process_pattern is not None and config.godot_watch_project_id is not None:
        watchers.append(
            GodotWatcher(
                project_id=config.godot_watch_project_id,
                machine_id=config.machine_id,
                outbox=store,
                process_pattern=config.godot_watch_process_pattern,
                interval_seconds=config.godot_watch_interval_seconds,
            )
        )
    return watchers


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="studio-client-daemon",
        description="Run the Studio OS heartbeat daemon until interrupted.",
    )
    parser.add_argument("--agent-id", type=UUID, default=None)
    args = parser.parse_args(argv)
    config = ClientConfig()  # type: ignore[call-arg]  # fields resolved from STUDIO_CLIENT_* env/TOML

    async def _run() -> None:
        async with StudioApiClient(config) as client:
            store = OutboxStore(connect(default_outbox_path()))
            retry_policy = RetryPolicy(
                config.max_attempts, config.backoff_initial, config.backoff_max
            )
            replayer = OutboxReplayer(store, client, retry_policy)
            daemon = HeartbeatDaemon(client, config, agent_id=args.agent_id, replayer=replayer)
            watchers = build_watchers(config, store)

            def _stop_all() -> None:
                daemon.request_stop()
                for watcher in watchers:
                    watcher.request_stop()

            install_signal_handlers(_stop_all)
            await asyncio.gather(daemon.run(), *(watcher.run() for watcher in watchers))

    asyncio.run(_run())


if __name__ == "__main__":
    main()
