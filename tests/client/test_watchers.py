from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.daemon.heartbeat import build_watchers
from studio_client.outbox import OutboxStore, OutboxTable, connect
from studio_client.watchers import GitState, GitWatcher, GodotWatcher
from studio_contracts.events import EventType

PROJECT_ID = uuid4()
MACHINE_ID = uuid4()


def _store(path: Path) -> OutboxStore:
    return OutboxStore(connect(path))


def _git_reader(states: list[GitState | None]) -> Callable[[], Awaitable[GitState | None]]:
    async def _read() -> GitState | None:
        return states.pop(0)

    return _read


def _process_probe(values: list[bool]) -> Callable[[], Awaitable[bool]]:
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

    watcher._sleep = _stop_after_first_wait
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

    watcher._sleep = _stop_after_first_wait
    await asyncio.wait_for(watcher.run(), timeout=1.0)

    assert watcher.stopped


# --- Multi-repo Git watching (DEC-0032 addendum) ---------------------------


def _config(**overrides: object) -> ClientConfig:
    return ClientConfig(
        api_base_url="https://vps.example.com",
        machine_id=MACHINE_ID,
        **overrides,  # type: ignore[arg-type]
    )


def _git_watch(path: Path, project_id: object) -> dict[str, object]:
    return {"repo_path": str(path), "project_id": str(project_id)}


def test_build_watchers_without_git_config_yields_no_git_watcher(tmp_path: Path) -> None:
    assert build_watchers(_config(), _store(tmp_path / "o.sqlite3")) == []


def test_build_watchers_legacy_single_repo_yields_one_watcher(tmp_path: Path) -> None:
    watchers = build_watchers(
        _config(git_watch_repo_path=tmp_path, git_watch_project_id=PROJECT_ID),
        _store(tmp_path / "o.sqlite3"),
    )

    assert [type(w) for w in watchers] == [GitWatcher]


@pytest.mark.parametrize("count", [1, 3])
def test_build_watchers_one_git_watcher_per_git_watch(tmp_path: Path, count: int) -> None:
    watches = [_git_watch(tmp_path / f"repo{i}", uuid4()) for i in range(count)]

    watchers = build_watchers(_config(git_watches=watches), _store(tmp_path / "o.sqlite3"))

    assert [type(w) for w in watchers] == [GitWatcher] * count


def test_build_watchers_git_and_godot_coexist(tmp_path: Path) -> None:
    watchers = build_watchers(
        _config(
            git_watches=[_git_watch(tmp_path / "a", uuid4())],
            godot_watch_process_pattern="godot",
            godot_watch_project_id=uuid4(),
        ),
        _store(tmp_path / "o.sqlite3"),
    )

    assert [type(w) for w in watchers] == [GitWatcher, GodotWatcher]


_needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git executable required")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> str:
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    return _commit(path, "initial")


def _commit(repo: Path, name: str) -> str:
    (repo / f"{name}.txt").write_text(name)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _events(store: OutboxStore) -> list[tuple[EventType, str, dict[str, object]]]:
    return [
        (EventType(str(row.extra["event_type"])), str(row.extra["project_id"]), row.payload)
        for row in store.list_pending(OutboxTable.EVENTS, ready_only=False)
    ]


def _real_watchers(
    tmp_path: Path, repos: dict[Path, object], store: OutboxStore
) -> list[GitWatcher]:
    config = _config(git_watches=[_git_watch(repo, pid) for repo, pid in repos.items()])
    watchers = build_watchers(config, store)
    assert all(isinstance(w, GitWatcher) for w in watchers)
    return [w for w in watchers if isinstance(w, GitWatcher)]


@_needs_git
async def test_two_repos_commits_are_isolated_per_project(tmp_path: Path) -> None:
    repo_a, repo_b = tmp_path / "a", tmp_path / "b"
    project_a, project_b = uuid4(), uuid4()
    _init_repo(repo_a)
    _init_repo(repo_b)
    store = _store(tmp_path / "outbox.sqlite3")
    watcher_a, watcher_b = _real_watchers(tmp_path, {repo_a: project_a, repo_b: project_b}, store)

    await watcher_a.poll_once()
    await watcher_b.poll_once()
    assert _events(store) == []

    sha_a = _commit(repo_a, "a1")
    await watcher_a.poll_once()
    await watcher_b.poll_once()
    assert _events(store) == [
        (EventType.GIT_COMMIT, str(project_a), {"sha": sha_a, "branch": "main"})
    ]

    sha_b = _commit(repo_b, "b1")
    await watcher_a.poll_once()
    await watcher_b.poll_once()
    assert _events(store)[1:] == [
        (EventType.GIT_COMMIT, str(project_b), {"sha": sha_b, "branch": "main"})
    ]
    assert store.get_sync_state(f"git_watcher:{repo_a}") != store.get_sync_state(
        f"git_watcher:{repo_b}"
    )


@_needs_git
async def test_branch_change_in_one_repo_only_reports_its_project(tmp_path: Path) -> None:
    repo_a, repo_b = tmp_path / "a", tmp_path / "b"
    project_a, project_b = uuid4(), uuid4()
    _init_repo(repo_a)
    _init_repo(repo_b)
    store = _store(tmp_path / "outbox.sqlite3")
    watchers = _real_watchers(tmp_path, {repo_a: project_a, repo_b: project_b}, store)
    for watcher in watchers:
        await watcher.poll_once()

    _git(repo_a, "checkout", "-q", "-b", "feature")
    for watcher in watchers:
        await watcher.poll_once()

    assert _events(store) == [
        (EventType.GIT_BRANCH_CHANGED, str(project_a), {"from": "main", "to": "feature"})
    ]


@_needs_git
async def test_rebuilt_watchers_keep_baselines_without_false_events(tmp_path: Path) -> None:
    repo_a, repo_b = tmp_path / "a", tmp_path / "b"
    project_a, project_b = uuid4(), uuid4()
    _init_repo(repo_a)
    _init_repo(repo_b)
    store = _store(tmp_path / "outbox.sqlite3")
    repos = {repo_a: project_a, repo_b: project_b}
    for watcher in _real_watchers(tmp_path, repos, store):
        await watcher.poll_once()
    sha_b = _commit(repo_b, "b1")

    # Daemon restart: fresh watchers over the same persisted store.
    for watcher in _real_watchers(tmp_path, repos, store):
        await watcher.poll_once()

    assert _events(store) == [
        (EventType.GIT_COMMIT, str(project_b), {"sha": sha_b, "branch": "main"})
    ]


async def test_watchers_share_one_outbox_without_collision(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    project_a, project_b = uuid4(), uuid4()
    watchers = [
        GitWatcher(
            repo_path=tmp_path / name,
            project_id=pid,
            machine_id=MACHINE_ID,
            outbox=store,
            reader=_git_reader(
                [GitState(commit_sha="c1", branch="main"), GitState(commit_sha="c2", branch="main")]
            ),
        )
        for name, pid in (("a", project_a), ("b", project_b))
    ]

    for _ in range(2):
        await asyncio.gather(*(w.poll_once() for w in watchers))

    assert sorted(project for _, project, _ in _events(store)) == sorted(
        [str(project_a), str(project_b)]
    )
