from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import httpx
import pytest
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.daemon import HeartbeatDaemon
from studio_client.tokens import MemoryTokenStore

MACHINE_ID = uuid4()


def _config(**overrides: Any) -> ClientConfig:
    params: dict[str, Any] = {
        "api_base_url": "http://test",
        "machine_id": MACHINE_ID,
        "max_attempts": 1,
    }
    params.update(overrides)
    return ClientConfig(**params)


def _client(handler: Any) -> StudioApiClient:
    store = MemoryTokenStore()
    store.set_token("http://test", "test-token")
    return StudioApiClient(_config(), store, transport=httpx.MockTransport(handler))


def _heartbeat_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "machine_id": str(MACHINE_ID),
            "status": "online",
            "last_seen_at": "2026-09-13T00:00:00Z",
            "server_timestamp": "2026-09-13T00:00:00Z",
        },
    )


async def _fake_sleep_counting(calls: list[float], stop_after: int, daemon: HeartbeatDaemon):
    async def _sleep(delay: float) -> None:
        calls.append(delay)
        if len(calls) >= stop_after:
            daemon.request_stop()

    return _sleep


def test_requires_configured_machine_id() -> None:
    config = _config(machine_id=None)
    client = StudioApiClient(config, MemoryTokenStore())
    with pytest.raises(ValueError, match="machine_id"):
        HeartbeatDaemon(client, config)


def test_rejects_non_positive_interval() -> None:
    config = _config()
    client = StudioApiClient(config, MemoryTokenStore())
    with pytest.raises(ValueError, match="interval_seconds"):
        HeartbeatDaemon(client, config, interval_seconds=0)


async def test_sends_heartbeat_on_every_tick_with_no_real_sleep() -> None:
    heartbeat_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        heartbeat_count["n"] += 1
        return _heartbeat_response(request)

    async with _client(handler) as client:
        sleep_calls: list[float] = []
        daemon = HeartbeatDaemon(
            client,
            _config(),
            interval_seconds=30.0,
            jitter_ratio=0.0,
            random_fn=lambda: 0.5,
        )
        daemon._sleep = await _fake_sleep_counting(sleep_calls, stop_after=3, daemon=daemon)  # type: ignore[attr-defined]

        await asyncio.wait_for(daemon.run(), timeout=1.0)

    assert heartbeat_count["n"] == 3
    assert sleep_calls == [30.0, 30.0, 30.0]


async def test_jitter_spreads_delay_around_interval() -> None:
    async with _client(_heartbeat_response) as client:
        daemon = HeartbeatDaemon(
            client,
            _config(),
            interval_seconds=100.0,
            jitter_ratio=0.1,
            random_fn=lambda: 1.0,
        )
        assert daemon._next_delay() == pytest.approx(110.0)  # type: ignore[attr-defined]

        daemon2 = HeartbeatDaemon(
            client,
            _config(),
            interval_seconds=100.0,
            jitter_ratio=0.1,
            random_fn=lambda: 0.0,
        )
        assert daemon2._next_delay() == pytest.approx(90.0)  # type: ignore[attr-defined]


async def test_stop_during_wait_returns_promptly() -> None:
    """A plain `await self._sleep(delay)` would block shutdown for up to the
    full jittered interval once a heartbeat has landed — `_wait` must return
    as soon as `request_stop()` fires instead of waiting it out."""
    async with _client(_heartbeat_response) as client:
        daemon = HeartbeatDaemon(client, _config(), interval_seconds=5.0, jitter_ratio=0.0)
        run_task = asyncio.create_task(daemon.run())
        await asyncio.sleep(0.05)  # let the first heartbeat land and _wait start

        start = asyncio.get_event_loop().time()
        daemon.request_stop()
        await asyncio.wait_for(run_task, timeout=1.0)
        elapsed = asyncio.get_event_loop().time() - start

    assert elapsed < 1.0


async def test_in_flight_heartbeat_completes_before_stop() -> None:
    heartbeat_started = asyncio.Event()
    release_heartbeat = asyncio.Event()
    completed = {"value": False}

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        heartbeat_started.set()
        await release_heartbeat.wait()
        completed["value"] = True
        return _heartbeat_response(request)

    transport = httpx.MockTransport(slow_handler)
    store = MemoryTokenStore()
    store.set_token("http://test", "test-token")

    async with StudioApiClient(_config(), store, transport=transport) as client:
        daemon = HeartbeatDaemon(client, _config())
        run_task = asyncio.create_task(daemon.run())

        await heartbeat_started.wait()
        daemon.request_stop()
        # The daemon must not abandon the in-flight call just because a stop
        # was requested concurrently.
        assert not completed["value"]
        release_heartbeat.set()

        await asyncio.wait_for(run_task, timeout=1.0)

    assert completed["value"]
    assert daemon.stopped
