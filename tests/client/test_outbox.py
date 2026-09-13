from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.outbox import OutboxStore, OutboxTable, connect, transaction
from studio_client.retry import RetryPolicy
from studio_contracts.events import EventCreate, EventType


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


def _store(path: Path) -> OutboxStore:
    return OutboxStore(connect(path))


def test_default_outbox_path_is_sibling_of_config_path() -> None:
    from studio_client.config import default_config_path
    from studio_client.outbox import default_outbox_path

    assert default_outbox_path().parent == default_config_path().parent
    assert default_outbox_path().name == "outbox.sqlite3"


def test_enqueue_event_duplicate_id_produces_single_row(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    event = _event()

    with transaction(store.connection):
        first = store.enqueue_event(event)
    with transaction(store.connection):
        second = store.enqueue_event(event)

    assert first is True
    assert second is False
    rows = store.list_pending(OutboxTable.EVENTS, ready_only=False)
    assert len(rows) == 1
    assert rows[0].id == str(event.event_id)


def test_enqueue_mutation_duplicate_key_produces_single_row(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    key = str(uuid4())

    with transaction(store.connection):
        first = store.enqueue_mutation(key, "task.create", "POST", "/api/v1/tasks", {"title": "a"})
    with transaction(store.connection):
        second = store.enqueue_mutation(key, "task.create", "POST", "/api/v1/tasks", {"title": "a"})

    assert first is True
    assert second is False
    assert len(store.list_pending(OutboxTable.MUTATIONS, ready_only=False)) == 1


def test_enqueue_marker_duplicate_id_produces_single_row(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    marker_id = uuid4()

    with transaction(store.connection):
        first = store.enqueue_marker(marker_id, "recording.marker", {"t": 1})
    with transaction(store.connection):
        second = store.enqueue_marker(marker_id, "recording.marker", {"t": 1})

    assert first is True
    assert second is False
    assert len(store.list_pending(OutboxTable.MARKERS, ready_only=False)) == 1


def test_restart_does_not_lose_pending_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "outbox.sqlite3"
    first_conn = connect(db_path)
    event = _event()
    with transaction(first_conn):
        OutboxStore(first_conn).enqueue_event(event)
    first_conn.close()

    reopened = OutboxStore(connect(db_path))
    rows = reopened.list_pending(OutboxTable.EVENTS, ready_only=False)
    assert len(rows) == 1
    assert rows[0].id == str(event.event_id)


def test_enqueue_shares_transaction_with_local_write_and_rolls_back_together(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "outbox.sqlite3")
    conn.execute("CREATE TABLE local_state (id TEXT PRIMARY KEY)")
    conn.commit()
    store = OutboxStore(conn)

    with pytest.raises(RuntimeError, match="simulated"):
        with transaction(conn):
            store.enqueue_event(_event())
            conn.execute("INSERT INTO local_state (id) VALUES ('x')")
            raise RuntimeError("simulated failure after both writes")

    assert store.list_pending(OutboxTable.EVENTS, ready_only=False) == []
    assert conn.execute("SELECT COUNT(*) FROM local_state").fetchone()[0] == 0


def test_mark_failed_bumps_attempt_and_schedules_bounded_backoff(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    event = _event()
    with transaction(store.connection):
        store.enqueue_event(event)
    policy = RetryPolicy(max_attempts=99, backoff_initial=1.0, backoff_max=2.0)

    with transaction(store.connection):
        store.mark_failed(OutboxTable.EVENTS, str(event.event_id), "boom", policy)

    rows = store.list_pending(OutboxTable.EVENTS, ready_only=False)
    assert len(rows) == 1
    assert rows[0].attempt_count == 1
    assert rows[0].last_error == "boom"
    assert rows[0].next_attempt_at > datetime.now(UTC)


def test_list_pending_ready_only_excludes_future_next_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    event = _event()
    with transaction(store.connection):
        store.enqueue_event(event)
    policy = RetryPolicy(max_attempts=99, backoff_initial=60.0, backoff_max=60.0)
    with transaction(store.connection):
        store.mark_failed(OutboxTable.EVENTS, str(event.event_id), "boom", policy)

    assert store.list_pending(OutboxTable.EVENTS, ready_only=True) == []
    assert len(store.list_pending(OutboxTable.EVENTS, ready_only=False)) == 1


def test_move_to_dead_letter_removes_from_pending_and_records_it(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    event = _event()
    with transaction(store.connection):
        store.enqueue_event(event)

    with transaction(store.connection):
        store.move_to_dead_letter(OutboxTable.EVENTS, str(event.event_id), "not_found")

    assert store.list_pending(OutboxTable.EVENTS, ready_only=False) == []
    dead = store.connection.execute("SELECT * FROM dead_letter").fetchall()
    assert len(dead) == 1
    assert dead[0]["error"] == "not_found"
    assert dead[0]["source_table"] == OutboxTable.EVENTS.value


def test_mark_succeeded_deletes_row(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    event = _event()
    with transaction(store.connection):
        store.enqueue_event(event)

    with transaction(store.connection):
        store.mark_succeeded(OutboxTable.EVENTS, str(event.event_id))

    assert store.list_pending(OutboxTable.EVENTS, ready_only=False) == []


def test_sync_state_roundtrip_and_overwrite(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    assert store.get_sync_state("cursor") is None

    with transaction(store.connection):
        store.set_sync_state("cursor", {"seq": 1})
    assert store.get_sync_state("cursor") == {"seq": 1}

    with transaction(store.connection):
        store.set_sync_state("cursor", {"seq": 2})
    assert store.get_sync_state("cursor") == {"seq": 2}
