"""Workspace configuration -> daemon -> `WorkspaceWatchSet` -> `GitWatcher`."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import studio_client.daemon.heartbeat as heartbeat_module
import studio_client.daemon.runtime as runtime_module
from studio_client.config import ClientConfig, GitWatchConfig
from studio_client.daemon.runtime import DaemonRuntime
from studio_client.daemon.workspace_watch import WorkspaceWatch, WorkspaceWatchSet
from studio_client.outbox import OutboxStore, connect
from studio_client.watchers import PollingWatcher
from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import LocalFeatures, WatcherConfig
from studio_workspaces import daemon_watch_plan

from tests.workspaces.factories import make_config

WS_A = UUID("11111111-1111-4111-8111-111111111111")
WS_B = UUID("22222222-2222-4222-8222-222222222222")
PROJECT = UUID("33333333-3333-4333-8333-333333333333")
ORIGIN = "https://studio.example"


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


class RecordingWatcher(PollingWatcher):
    instances: list[RecordingWatcher] = []

    def __init__(self, repo_path: Path, **_kwargs: object) -> None:
        super().__init__(interval_seconds=0.01)
        self.path = Path(repo_path)
        RecordingWatcher.instances.append(self)

    async def poll_once(self) -> None:
        return None

    @classmethod
    def live_paths(cls) -> list[Path]:
        return sorted(w.path for w in cls.instances if not w.stopped)


class FakeClient:
    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeHeartbeat:
    instances: list[FakeHeartbeat] = []

    def __init__(self, _client, _config, *, agent_id=None, replayer=None) -> None:
        self.stop = asyncio.Event()
        self.last_attempt_at = None
        self.last_success_at = None
        self.last_error = None
        self.last_replay = None
        FakeHeartbeat.instances.append(self)

    def request_stop(self) -> None:
        self.stop.set()

    async def run(self) -> None:
        await self.stop.wait()


@pytest.fixture(autouse=True)
def _patched(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    RecordingWatcher.instances = []
    FakeHeartbeat.instances = []
    monkeypatch.setattr(runtime_module, "StudioApiClient", lambda _config: FakeClient())
    monkeypatch.setattr(runtime_module, "HeartbeatDaemon", FakeHeartbeat)
    monkeypatch.setattr(heartbeat_module, "GitWatcher", RecordingWatcher)
    original = runtime_module.WorkspaceWatchSet

    def build(**kwargs: object) -> WorkspaceWatchSet:
        return original(
            watcher_factory=lambda path, _project: RecordingWatcher(path),
            **kwargs,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(runtime_module, "WorkspaceWatchSet", build)
    yield


def repo(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    (path / ".git").mkdir(parents=True)
    return path


def entry(workspace_id: UUID, *paths: Path, enabled: bool = True) -> WorkspaceWatch:
    config = make_config(
        workspace_id,
        str(paths[0]) if paths else "C:/Work/none",
        [(f"r{i}", str(p)) for i, p in enumerate(paths)],
    )
    if enabled:
        config = config.model_copy(
            update={"features": LocalFeatures(watchers=True), "watchers": WatcherConfig()}
        )
    return WorkspaceWatch(workspace_id, PROJECT, daemon_watch_plan(config))


class Source:
    def __init__(self) -> None:
        self.entries: list[WorkspaceWatch] = []
        self.calls: list[ProfileRef] = []
        self.failure: Exception | None = None

    def __call__(self, profile: ProfileRef) -> list[WorkspaceWatch]:
        self.calls.append(profile)
        if self.failure is not None:
            raise self.failure
        return list(self.entries)


def make_runtime(
    tmp_path: Path, source: Source, git_watches: tuple[GitWatchConfig, ...] = ()
) -> DaemonRuntime:
    runtime = DaemonRuntime(
        ClientConfig(
            api_base_url=ORIGIN,
            profile_id="main",
            machine_id=uuid4(),
            heartbeat_interval_seconds=0.01,
            heartbeat_jitter_ratio=0,
            git_watch_interval_seconds=0.05,
            git_watches=git_watches,
        ),
        data_root=tmp_path / "data",
        workspace_source=source,
        workspace_sync_seconds=0.02,
    )
    runtime._legacy_outbox_path = tmp_path / "absent.sqlite3"  # noqa: SLF001
    return runtime


async def until(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


async def stop(runtime: DaemonRuntime, task: asyncio.Task[None]) -> None:
    runtime.request_stop()
    await asyncio.wait_for(task, timeout=5)


async def test_the_product_source_drives_the_watcher_at_start(tmp_path: Path) -> None:
    game = repo(tmp_path, "game")
    source = Source()
    source.entries = [entry(WS_A, game)]
    runtime = make_runtime(tmp_path, source)
    task = asyncio.create_task(runtime.run())
    await until(lambda: RecordingWatcher.live_paths() == [game])
    assert source.calls[0] == runtime.profile
    await stop(runtime, task)
    assert RecordingWatcher.live_paths() == []


async def test_a_workspace_without_repository_creates_no_watcher(tmp_path: Path) -> None:
    source = Source()
    source.entries = [entry(WS_A)]
    runtime = make_runtime(tmp_path, source)
    task = asyncio.create_task(runtime.run())
    await until(lambda: len(source.calls) >= 2)
    assert RecordingWatcher.instances == []
    await stop(runtime, task)


async def test_a_disabled_watcher_creates_none(tmp_path: Path) -> None:
    source = Source()
    source.entries = [entry(WS_A, repo(tmp_path, "game"), enabled=False)]
    runtime = make_runtime(tmp_path, source)
    task = asyncio.create_task(runtime.run())
    await until(lambda: len(source.calls) >= 2)
    assert RecordingWatcher.instances == []
    await stop(runtime, task)


async def test_a_moved_repository_follows_the_configuration(tmp_path: Path) -> None:
    old, new = repo(tmp_path, "old"), repo(tmp_path, "new")
    source = Source()
    source.entries = [entry(WS_A, old)]
    runtime = make_runtime(tmp_path, source)
    task = asyncio.create_task(runtime.run())
    await until(lambda: RecordingWatcher.live_paths() == [old])
    source.entries = [entry(WS_A, new)]
    await until(lambda: RecordingWatcher.live_paths() == [new])
    await stop(runtime, task)


async def test_a_vanished_repository_is_dropped(tmp_path: Path) -> None:
    game = repo(tmp_path, "game")
    source = Source()
    source.entries = [entry(WS_A, game)]
    runtime = make_runtime(tmp_path, source)
    task = asyncio.create_task(runtime.run())
    await until(lambda: RecordingWatcher.live_paths() == [game])
    (game / ".git").rmdir()
    await until(lambda: RecordingWatcher.live_paths() == [])
    await stop(runtime, task)


async def test_a_removed_association_stops_its_watcher(tmp_path: Path) -> None:
    game, other = repo(tmp_path, "game"), repo(tmp_path, "other")
    source = Source()
    source.entries = [entry(WS_A, game), entry(WS_B, other)]
    runtime = make_runtime(tmp_path, source)
    task = asyncio.create_task(runtime.run())
    await until(lambda: RecordingWatcher.live_paths() == sorted([game, other]))
    source.entries = [entry(WS_B, other)]
    await until(lambda: RecordingWatcher.live_paths() == [other])
    assert len([w for w in RecordingWatcher.instances if w.path == other]) == 1
    await stop(runtime, task)


async def test_an_unreadable_source_keeps_the_current_watchers(tmp_path: Path) -> None:
    game = repo(tmp_path, "game")
    source = Source()
    source.entries = [entry(WS_A, game)]
    runtime = make_runtime(tmp_path, source)
    task = asyncio.create_task(runtime.run())
    await until(lambda: RecordingWatcher.live_paths() == [game])
    source.failure = OSError("registry locked")
    calls = len(source.calls)
    await until(lambda: len(source.calls) >= calls + 3)
    assert RecordingWatcher.live_paths() == [game]
    assert len(RecordingWatcher.instances) == 1
    await stop(runtime, task)


async def test_a_repository_in_git_watches_is_watched_exactly_once(tmp_path: Path) -> None:
    game = repo(tmp_path, "game")
    source = Source()
    source.entries = [entry(WS_A, game)]
    runtime = make_runtime(tmp_path, source, (GitWatchConfig(repo_path=game, project_id=PROJECT),))
    task = asyncio.create_task(runtime.run())
    await until(lambda: len(source.calls) >= 3)
    assert [w.path for w in RecordingWatcher.instances] == [game]
    assert len(runtime.health().git_watchers) == 1
    assert len(FakeHeartbeat.instances) == 1
    await stop(runtime, task)


async def test_git_watches_and_workspaces_coexist_without_overlap(tmp_path: Path) -> None:
    configured, discovered = repo(tmp_path, "configured"), repo(tmp_path, "discovered")
    source = Source()
    source.entries = [entry(WS_A, configured, discovered)]
    runtime = make_runtime(
        tmp_path, source, (GitWatchConfig(repo_path=configured, project_id=PROJECT),)
    )
    task = asyncio.create_task(runtime.run())
    await until(lambda: len(RecordingWatcher.instances) == 2)
    await asyncio.sleep(0.1)
    assert sorted(w.path for w in RecordingWatcher.instances) == sorted([configured, discovered])
    assert len(runtime.health().git_watchers) == 2
    await stop(runtime, task)


async def test_without_a_source_nothing_is_watched_beyond_the_configuration(
    tmp_path: Path,
) -> None:
    runtime = DaemonRuntime(
        ClientConfig(
            api_base_url=ORIGIN,
            profile_id="main",
            machine_id=uuid4(),
            heartbeat_interval_seconds=0.01,
            heartbeat_jitter_ratio=0,
        ),
        data_root=tmp_path / "data",
    )
    runtime._legacy_outbox_path = tmp_path / "absent.sqlite3"  # noqa: SLF001
    task = asyncio.create_task(runtime.run())
    await asyncio.sleep(0.1)
    assert RecordingWatcher.instances == []
    await stop(runtime, task)


async def test_health_can_be_read_while_watchers_change(tmp_path: Path) -> None:
    watches = WorkspaceWatchSet(
        machine_id=uuid4(),
        outbox=OutboxStore(connect(tmp_path / "outbox.sqlite3")),
        watcher_factory=lambda path, _project: RecordingWatcher(path),
    )
    repos = [repo(tmp_path, f"r{i}") for i in range(4)]
    failures: list[BaseException] = []
    done = threading.Event()

    def reader() -> None:
        try:
            while not done.is_set():
                watches.health()
                _ = watches.watched_paths
                time.sleep(0.001)
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    for round_index in range(24):
        chosen = repos[: (round_index % 4) + 1]
        await watches.reconcile([entry(WS_A, *chosen)])
    await watches.stop()
    done.set()
    for thread in threads:
        thread.join(timeout=5)
    assert failures == []
    assert watches.health() == []
