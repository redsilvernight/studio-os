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


async def test_system_actor_watcher_event_replays_like_any_other_event(tmp_path: Path) -> None:
    """git/godot watchers (DEC-0032) enqueue `actor_type="system",
    actor_id=machine_id` events — same public `POST /events` replay path as
    every other event, and the server now validates that shape (DEC-0035:
    `actor_type=system` is only accepted with `actor_id == machine.id`)."""
    store = _store(tmp_path / "outbox.sqlite3")
    event = _event(actor_type="system", actor_id=MACHINE_ID, machine_id=MACHINE_ID)
    with transaction(store.connection):
        store.enqueue_event(event)

    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        return httpx.Response(200, json={**received, "server_timestamp": "2026-09-13T00:00:00Z"})

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()

    assert outcome.succeeded == 1
    assert received["actor_type"] == "system"
    assert received["actor_id"] == str(MACHINE_ID)
    assert received["machine_id"] == str(MACHINE_ID)


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


async def test_readonly_forbidden_error_dead_letters_with_actionable_message(
    tmp_path: Path,
) -> None:
    """DEC-0036 risk: a 403 from the authorization gate (e.g. a queued event
    replayed under a `readonly`-role token) is never retryable
    (`ForbiddenError`, `.claude/rules python-conventions.md`-style whitelist
    in `retry.is_retryable`) — it must dead-letter immediately rather than
    burn the backoff budget, and the recorded error must carry the server's
    machine-readable reason, not a bare status code."""
    store = _store(tmp_path / "outbox.sqlite3")
    event = _event()
    with transaction(store.connection):
        store.enqueue_event(event)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"detail": {"error_code": "forbidden", "resource": "event", "action": "write"}},
        )

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()

    assert outcome.dead_lettered == 1
    assert outcome.stopped_on_transient_error is False
    assert store.list_pending(OutboxTable.EVENTS, ready_only=False) == []
    dead = store.connection.execute("SELECT * FROM dead_letter").fetchall()
    assert len(dead) == 1
    assert "forbidden" in dead[0]["error"]


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


async def test_mark_succeeded_is_durable_after_crash(tmp_path: Path) -> None:
    """A row cleared by `replay_ready` must actually be committed, not just
    visible to the connection that cleared it — otherwise a crash right
    after replay resends an operation the server already accepted."""
    db_path = tmp_path / "outbox.sqlite3"
    store = _store(db_path)
    event = _event()
    with transaction(store.connection):
        store.enqueue_event(event)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={**event.model_dump(mode="json"), "server_timestamp": "2026-09-13T00:00:00Z"},
        )

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()
    assert outcome.succeeded == 1
    store.connection.close()

    second_connection_store = OutboxStore(connect(db_path))
    assert second_connection_store.list_pending(OutboxTable.EVENTS, ready_only=False) == []


async def test_mark_failed_backoff_is_durable_after_crash(tmp_path: Path) -> None:
    """The `attempt_count`/`next_attempt_at`/`last_error` written after a
    transient failure must survive a crash — otherwise a restart forgets the
    backoff and hammers the server immediately."""
    db_path = tmp_path / "outbox.sqlite3"
    store = _store(db_path)
    event = _event()
    with transaction(store.connection):
        store.enqueue_event(event)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": {"error_code": "server_error"}})

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()
    assert outcome.stopped_on_transient_error is True
    store.connection.close()

    second_connection_store = OutboxStore(connect(db_path))
    rows = second_connection_store.list_pending(OutboxTable.EVENTS, ready_only=False)
    assert len(rows) == 1
    assert rows[0].attempt_count == 1
    assert rows[0].last_error is not None


async def test_dead_letter_move_is_durable_after_crash(tmp_path: Path) -> None:
    """A definitive failure must be durably removed from pending and
    durably recorded in `dead_letter` in the same commit — a crash between
    the two would either resurrect a dead row or lose the record of it."""
    db_path = tmp_path / "outbox.sqlite3"
    store = _store(db_path)
    event = _event()
    with transaction(store.connection):
        store.enqueue_event(event)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": {"error_code": "not_found"}})

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()
    assert outcome.dead_lettered == 1
    store.connection.close()

    second_connection_store = OutboxStore(connect(db_path))
    assert second_connection_store.list_pending(OutboxTable.EVENTS, ready_only=False) == []
    dead = second_connection_store.connection.execute("SELECT * FROM dead_letter").fetchall()
    assert len(dead) == 1
    assert dead[0]["source_table"] == OutboxTable.EVENTS.value


_PROJECT_DENIED = {"detail": {"error_code": "forbidden", "resource": "project", "action": "write"}}


async def test_project_isolation_403_dead_letters_with_visible_diagnostic(
    tmp_path: Path, caplog: Any
) -> None:
    """Project isolation: a queued event for a project the account cannot
    access is refused with a final 403 `resource: project`. The row is
    dead-lettered (never retried), tagged `project_access_denied project=<id>`,
    reported on the outcome and logged with the project — not a bare 403."""
    store = _store(tmp_path / "outbox.sqlite3")
    denied_event = _event()
    other_project = uuid4()
    with transaction(store.connection):
        store.enqueue_event(denied_event)
    with transaction(store.connection):
        store.enqueue_mutation(
            str(uuid4()), "task.update", "PATCH", f"/api/v1/projects/{other_project}/tasks/x", {}
        )
    since = datetime.now(UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json=_PROJECT_DENIED)

    async with _client(handler) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        with caplog.at_level("WARNING", logger="studio_client.outbox.replay"):
            outcome = await replayer.replay_ready()

    assert outcome.dead_lettered == 2
    assert outcome.stopped_on_transient_error is False
    assert outcome.project_access_denied == [str(denied_event.project_id), str(other_project)]
    errors = [
        row["error"]
        for row in store.connection.execute("SELECT error FROM dead_letter ORDER BY failed_at")
    ]
    assert errors[0].startswith(f"project_access_denied project={denied_event.project_id}: 403")
    assert str(denied_event.project_id) in caplog.text
    assert "no access to project" in caplog.text

    count, projects = store.project_access_denied_since(since)
    assert count == 2
    assert projects == [str(denied_event.project_id), str(other_project)]
    assert store.project_access_denied_since(datetime.now(UTC))[0] == 0


async def test_role_403_is_not_reported_as_project_isolation(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    with transaction(store.connection):
        store.enqueue_event(_event())
    since = datetime.now(UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"detail": {"error_code": "forbidden", "resource": "event", "action": "write"}},
        )

    async with _client(handler) as client:
        outcome = await OutboxReplayer(store, client, RetryPolicy(max_attempts=1)).replay_ready()

    assert outcome.dead_lettered == 1
    assert outcome.project_access_denied == []
    assert store.project_access_denied_since(since) == (0, [])
