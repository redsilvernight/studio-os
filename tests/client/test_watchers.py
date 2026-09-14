from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from studio_client.outbox import OutboxStore, OutboxTable, connect
from studio_client.watchers import GitState, GitWatcher, GodotWatcher
from studio_contracts.events import EventType

PROJECT_ID = uuid4()
MACHINE_ID = uuid4()


def _store(path: Path) -> OutboxStore:
    return OutboxStore(connect(path))


def _git_reader(states: list[GitState | None]):
    async def _read() -> GitState | None:
        return states.pop(0)

    return _read


def _process_probe(values: list[bool]):
    async def _probe() -> bool:
        return values.pop(0)

    return _probe


def _pending_event_types(store: OutboxStore) -> list[EventType]:
    rows = store.list_pending(OutboxTable.EVENTS, ready_only=False)
    return [EventType(str(row.extra["event_type"])) for row in rows]


async def test_git_watcher_first_poll_establishes_baseline_without_event(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    state = GitState(commit_sha="c1", branch="main")
    watcher = GitWatcher(
        repo_path=tmp_path,
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        reader=_git_reader([state]),
    )

    await watcher.poll_once()

    assert _pending_event_types(store) == []
    assert store.get_sync_state(f"git_watcher:{tmp_path}") == {
        "commit_sha": "c1",
        "branch": "main",
    }


async def test_git_watcher_commit_change_emits_git_commit(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    watcher = GitWatcher(
        repo_path=tmp_path,
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        reader=_git_reader(
            [GitState(commit_sha="c1", branch="main"), GitState(commit_sha="c2", branch="main")]
        ),
    )

    await watcher.poll_once()
    await watcher.poll_once()

    rows = store.list_pending(OutboxTable.EVENTS, ready_only=False)
    assert len(rows) == 1
    assert EventType(str(rows[0].extra["event_type"])) == EventType.GIT_COMMIT
    assert rows[0].payload == {"sha": "c2", "branch": "main"}
    assert store.get_sync_state(f"git_watcher:{tmp_path}") == {
        "commit_sha": "c2",
        "branch": "main",
    }


async def test_git_watcher_branch_change_emits_git_branch_changed_only(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    watcher = GitWatcher(
        repo_path=tmp_path,
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        reader=_git_reader(
            [GitState(commit_sha="c1", branch="main"), GitState(commit_sha="c1", branch="feature")]
        ),
    )

    await watcher.poll_once()
    await watcher.poll_once()

    rows = store.list_pending(OutboxTable.EVENTS, ready_only=False)
    assert len(rows) == 1
    assert EventType(str(rows[0].extra["event_type"])) == EventType.GIT_BRANCH_CHANGED
    assert rows[0].payload == {"from": "main", "to": "feature"}


async def test_git_watcher_commit_and_branch_change_emits_both_events(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    watcher = GitWatcher(
        repo_path=tmp_path,
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        reader=_git_reader(
            [GitState(commit_sha="c1", branch="main"), GitState(commit_sha="c2", branch="feature")]
        ),
    )

    await watcher.poll_once()
    await watcher.poll_once()

    assert _pending_event_types(store) == [EventType.GIT_BRANCH_CHANGED, EventType.GIT_COMMIT]


async def test_git_watcher_unreadable_repo_skips_poll_without_baseline(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    watcher = GitWatcher(
        repo_path=tmp_path,
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        reader=_git_reader([None]),
    )

    await watcher.poll_once()

    assert _pending_event_types(store) == []
    assert store.get_sync_state(f"git_watcher:{tmp_path}") is None


async def test_git_watcher_run_stops_promptly(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    watcher = GitWatcher(
        repo_path=tmp_path,
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        interval_seconds=100.0,
        reader=_git_reader([GitState(commit_sha="c1", branch="main")] * 5),
    )

    async def _stop_after_first_wait(_delay: float) -> None:
        watcher.request_stop()

    watcher._sleep = _stop_after_first_wait  # type: ignore[attr-defined]
    await asyncio.wait_for(watcher.run(), timeout=1.0)

    assert watcher.stopped


async def test_godot_watcher_first_poll_establishes_baseline_without_event(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    watcher = GodotWatcher(
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        probe=_process_probe([True]),
    )

    await watcher.poll_once()

    assert _pending_event_types(store) == []
    assert store.get_sync_state("godot_watcher:godot") == {"running": True}


async def test_godot_watcher_start_transition_emits_started(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    watcher = GodotWatcher(
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        probe=_process_probe([False, True]),
    )

    await watcher.poll_once()
    await watcher.poll_once()

    assert _pending_event_types(store) == [EventType.GODOT_STARTED]


async def test_godot_watcher_stop_transition_emits_stopped(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    watcher = GodotWatcher(
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        probe=_process_probe([True, False]),
    )

    await watcher.poll_once()
    await watcher.poll_once()

    assert _pending_event_types(store) == [EventType.GODOT_STOPPED]


async def test_godot_watcher_no_transition_emits_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    watcher = GodotWatcher(
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=store,
        probe=_process_probe([True, True, True]),
    )

    await watcher.poll_once()
    await watcher.poll_once()
    await watcher.poll_once()

    assert _pending_event_types(store) == []


async def test_watcher_poll_failure_is_logged_and_does_not_crash_run(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")

    async def _boom() -> bool:
        raise RuntimeError("tasklist unavailable")

    watcher = GodotWatcher(project_id=PROJECT_ID, machine_id=MACHINE_ID, outbox=store, probe=_boom)

    async def _stop_after_first_wait(_delay: float) -> None:
        watcher.request_stop()

    watcher._sleep = _stop_after_first_wait  # type: ignore[attr-defined]
    await asyncio.wait_for(watcher.run(), timeout=1.0)

    assert watcher.stopped
