from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.outbox import OutboxReplayer, OutboxStore, OutboxTable, connect, transaction
from studio_client.retry import RetryPolicy
from studio_client.tokens import MemoryTokenStore
from studio_contracts.events import EventCreate, EventType

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


def _store(path: Path) -> OutboxStore:
    return OutboxStore(connect(path))


def _event(**overrides: object) -> EventCreate:
    params: dict[str, object] = {
        "event_id": uuid4(),
        "event_type": EventType.TASK_CREATED,
        "project_id": uuid4(),
        "actor_type": "agent",
        "actor_id": uuid4(),
        "client_timestamp": datetime.now(UTC),
        "payload": {"title": "test"},
    }
    params.update(overrides)
    return EventCreate(**params)  # type: ignore[arg-type]


async def test_replays_event_then_mutation_in_creation_order(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    event = _event()
    with transaction(store.connection):
        store.enqueue_event(event)
    key = str(uuid4())
    with transaction(store.connection):
        store.enqueue_mutation(key, "task.create", "POST", "/api/v1/tasks", {"title": "a"})

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/events":
            return httpx.Response(
                200,
                json={**event.model_dump(mode="json"), "server_timestamp": "2026-09-13T00:00:00Z"},
            )
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()

    assert calls == ["/api/v1/events", "/api/v1/tasks"]
    assert outcome.succeeded == 2
    assert outcome.dead_lettered == 0
    assert store.list_pending(OutboxTable.EVENTS, ready_only=False) == []
    assert store.list_pending(OutboxTable.MUTATIONS, ready_only=False) == []


async def test_event_replay_reconstructs_original_payload(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    event = _event(payload={"title": "reconstruct-me"})
    with transaction(store.connection):
        store.enqueue_event(event)

    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        return httpx.Response(200, json={**received, "server_timestamp": "2026-09-13T00:00:00Z"})

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        await replayer.replay_ready()

    assert received["event_id"] == str(event.event_id)
    assert received["project_id"] == str(event.project_id)
    assert received["payload"] == {"title": "reconstruct-me"}


async def test_non_retryable_error_dead_letters_and_pass_continues(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    first_event = _event()
    with transaction(store.connection):
        store.enqueue_event(first_event)
    key = str(uuid4())
    with transaction(store.connection):
        store.enqueue_mutation(key, "task.create", "POST", "/api/v1/tasks", {"title": "a"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/events":
            return httpx.Response(404, json={"detail": {"error_code": "not_found"}})
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()

    assert outcome.dead_lettered == 1
    assert outcome.succeeded == 1
    assert outcome.stopped_on_transient_error is False
    assert store.list_pending(OutboxTable.EVENTS, ready_only=False) == []
    assert store.list_pending(OutboxTable.MUTATIONS, ready_only=False) == []
    dead = store.connection.execute("SELECT * FROM dead_letter").fetchall()
    assert len(dead) == 1
    assert dead[0]["source_table"] == OutboxTable.EVENTS.value


async def test_transient_error_stops_pass_and_preserves_order(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    first_event = _event()
    with transaction(store.connection):
        store.enqueue_event(first_event)
    key = str(uuid4())
    with transaction(store.connection):
        store.enqueue_mutation(key, "task.create", "POST", "/api/v1/tasks", {"title": "a"})

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/events":
            return httpx.Response(500, json={"detail": {"error_code": "server_error"}})
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()

    assert calls == ["/api/v1/events"]
    assert outcome.stopped_on_transient_error is True
    assert outcome.succeeded == 0
    event_rows = store.list_pending(OutboxTable.EVENTS, ready_only=False)
    assert len(event_rows) == 1
    assert event_rows[0].attempt_count == 1
    assert event_rows[0].next_attempt_at > datetime.now(UTC)
    assert len(store.list_pending(OutboxTable.MUTATIONS, ready_only=False)) == 1


async def test_pending_markers_are_never_replayed(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    marker_id = uuid4()
    with transaction(store.connection):
        store.enqueue_marker(marker_id, "recording.marker", {"t": 1})

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected call to {request.url.path}")

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()

    assert outcome.succeeded == 0
    assert len(store.list_pending(OutboxTable.MARKERS, ready_only=False)) == 1


async def test_replay_ready_with_empty_outbox_is_a_noop(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no rows queued, no call expected")

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()

    assert outcome == outcome.__class__()
