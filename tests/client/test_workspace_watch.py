"""P4 x P5: the P5 watch plan drives the P4 GitWatcher lifecycle."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import studio_client.daemon.runtime as runtime_module
from studio_client.config import ClientConfig
from studio_client.daemon.runtime import DaemonRuntime
from studio_client.daemon.workspace_watch import (
    RepoStatus,
    WorkspaceWatch,
    WorkspaceWatchSet,
    probe_repo,
)
from studio_client.outbox import OutboxStore, OutboxTable, connect
from studio_client.watchers import PollingWatcher
from studio_contracts.local.workspace import LocalFeatures, WatcherConfig
from studio_workspaces import daemon_watch_plan

from tests.workspaces.factories import make_config

WS_A = UUID("11111111-1111-4111-8111-111111111111")
WS_B = UUID("22222222-2222-4222-8222-222222222222")
PROJECT = UUID("33333333-3333-4333-8333-333333333333")
MACHINE = uuid4()


class FakeWatcher(PollingWatcher):
    instances: list[FakeWatcher] = []

    def __init__(self, path: Path) -> None:
        super().__init__(interval_seconds=0.01)
        self.path = path
        self.polls = 0
        FakeWatcher.instances.append(self)

    async def poll_once(self) -> None:
        self.polls += 1


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeWatcher.instances = []


def repo(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    (path / ".git").mkdir(parents=True)
    return path


def plan_for(workspace_id: UUID, *paths: Path, enabled: bool = True, project: UUID = PROJECT):
    config = make_config(
        workspace_id,
        str(paths[0]) if paths else "C:/Work/none",
        [(f"r{i}", str(p)) for i, p in enumerate(paths)],
        project_id=project,
    )
    if enabled:
        config = config.model_copy(
            update={"features": LocalFeatures(watchers=True), "watchers": WatcherConfig()}
        )
    return WorkspaceWatch(workspace_id, project, daemon_watch_plan(config))


def make_set(tmp_path: Path, **kwargs) -> WorkspaceWatchSet:
    return WorkspaceWatchSet(
        machine_id=MACHINE,
        outbox=OutboxStore(connect(tmp_path / "outbox.sqlite3")),
        watcher_factory=lambda path, project_id: FakeWatcher(path),
        **kwargs,
    )


def statuses(observations) -> list[RepoStatus]:
    return [o.status for o in observations]


async def test_valid_repo_is_watched_and_stopped_cleanly(tmp_path: Path) -> None:
    watches = make_set(tmp_path)
    path = repo(tmp_path, "game")
    observed = await watches.reconcile([plan_for(WS_A, path)])
    assert statuses(observed) == [RepoStatus.WATCHING]
    await asyncio.sleep(0.05)
    assert watches.watched_paths == [path]
    assert FakeWatcher.instances[0].polls >= 1
    assert [h.condition.value for h in watches.health()] == ["healthy"]
    await watches.stop()
    assert watches.watched_paths == []
    assert FakeWatcher.instances[0].stopped


async def test_no_repository_is_reported_and_not_watched(tmp_path: Path) -> None:
    watches = make_set(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    observed = await watches.reconcile([plan_for(WS_A, plain)])
    assert statuses(observed) == [RepoStatus.NOT_A_REPOSITORY]
    assert FakeWatcher.instances == []
    await watches.stop()


async def test_vanished_repo_is_stopped_on_the_next_reconcile(tmp_path: Path) -> None:
    watches = make_set(tmp_path)
    path = repo(tmp_path, "game")
    plan = [plan_for(WS_A, path)]
    await watches.reconcile(plan)
    shutil.rmtree(path)
    observed = await watches.reconcile(plan)
    assert statuses(observed) == [RepoStatus.MISSING]
    assert watches.watched_paths == []
    assert FakeWatcher.instances[0].stopped
    await watches.stop()


async def test_inaccessible_repo_is_refused_not_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self: Path) -> bool:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "exists", boom)
    assert probe_repo(tmp_path) is RepoStatus.INACCESSIBLE
    assert probe_repo(Path("relative/repo")) is RepoStatus.INACCESSIBLE


async def test_workspace_change_restarts_only_what_changed(tmp_path: Path) -> None:
    watches = make_set(tmp_path)
    first, second = repo(tmp_path, "a"), repo(tmp_path, "b")
    await watches.reconcile([plan_for(WS_A, first, second)])
    assert len(FakeWatcher.instances) == 2
    await watches.reconcile([plan_for(WS_A, first)])
    assert watches.watched_paths == [first]
    assert [w.stopped for w in FakeWatcher.instances] == [False, True]
    assert len(FakeWatcher.instances) == 2
    await watches.stop()


async def test_watcher_disabled_stops_everything(tmp_path: Path) -> None:
    watches = make_set(tmp_path)
    path = repo(tmp_path, "game")
    await watches.reconcile([plan_for(WS_A, path)])
    observed = await watches.reconcile([plan_for(WS_A, path, enabled=False)])
    assert statuses(observed) == [RepoStatus.DISABLED]
    assert watches.watched_paths == []
    await watches.stop()


async def test_multiple_workspaces_share_one_watcher_per_repo(tmp_path: Path) -> None:
    watches = make_set(tmp_path)
    shared, own = repo(tmp_path, "shared"), repo(tmp_path, "own")
    observed = await watches.reconcile(
        [plan_for(WS_A, shared, own), plan_for(WS_B, shared, project=uuid4())]
    )
    assert sorted(watches.watched_paths) == sorted([shared, own])
    assert RepoStatus.ALREADY_WATCHED in statuses(observed)
    assert len(FakeWatcher.instances) == 2
    await watches.stop()


async def test_reconcile_is_idempotent_no_duplicate_watchers(tmp_path: Path) -> None:
    watches = make_set(tmp_path)
    path = repo(tmp_path, "game")
    plans = [plan_for(WS_A, path)]
    for _ in range(3):
        await watches.reconcile(plans)
    assert len(FakeWatcher.instances) == 1
    await watches.stop()


async def test_crashed_watcher_task_is_replaced_once(tmp_path: Path) -> None:
    watches = make_set(tmp_path)
    path = repo(tmp_path, "game")
    plans = [plan_for(WS_A, path)]
    await watches.reconcile(plans)
    running = watches._running[path]  # noqa: SLF001
    running.task.cancel()
    await asyncio.gather(running.task, return_exceptions=True)
    assert [h.condition.value for h in watches.health()] == ["offline"]
    await watches.reconcile(plans)
    assert len(FakeWatcher.instances) == 2
    assert [h.condition.value for h in watches.health()] == ["healthy"]
    await watches.stop()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
async def test_real_git_watcher_reports_a_new_commit_through_the_outbox(tmp_path: Path) -> None:
    path = tmp_path / "real"
    path.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=path,
            check=True,
            capture_output=True,
        )

    git("init")
    git("commit", "--allow-empty", "-m", "one")
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    watches = WorkspaceWatchSet(machine_id=MACHINE, outbox=store, interval_seconds=0.05)
    await watches.reconcile([plan_for(WS_A, path)])
    await asyncio.sleep(0.3)
    git("commit", "--allow-empty", "-m", "two")
    for _ in range(60):
        if store.list_pending(OutboxTable.EVENTS, ready_only=False):
            break
        await asyncio.sleep(0.1)
    await watches.stop()
    assert store.list_pending(OutboxTable.EVENTS, ready_only=False)


async def test_daemon_runtime_applies_plans_at_start_and_stops_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeHeartbeat:
        def __init__(self, _client, _config, *, agent_id=None, replayer=None):
            self.stop = asyncio.Event()
            self.last_attempt_at = None
            self.last_success_at = None
            self.last_error = None
            self.last_replay = None

        def request_stop(self) -> None:
            self.stop.set()

        async def run(self) -> None:
            await self.stop.wait()

    monkeypatch.setattr(runtime_module, "StudioApiClient", lambda _config: FakeClient())
    monkeypatch.setattr(runtime_module, "HeartbeatDaemon", FakeHeartbeat)
    path = repo(tmp_path, "game")
    runtime = DaemonRuntime(
        ClientConfig(
            api_base_url="https://studio.example/api/v1",
            profile_id="main",
            machine_id=MACHINE,
            heartbeat_interval_seconds=0.01,
            heartbeat_jitter_ratio=0,
            git_watch_interval_seconds=0.05,
        ),
        data_root=tmp_path / "data",
    )
    runtime._legacy_outbox_path = tmp_path / "absent.sqlite3"  # noqa: SLF001
    await runtime.reconcile_workspace_watchers([plan_for(WS_A, path)])
    task = asyncio.create_task(runtime.run())
    for _ in range(100):
        if runtime._workspace_watches is not None and runtime._workspace_watches.watched_paths:  # noqa: SLF001
            break
        await asyncio.sleep(0.02)
    health = runtime.health()
    assert [w.service.value for w in health.git_watchers] == ["git_watcher"]
    await runtime.reconcile_workspace_watchers([])
    assert runtime._workspace_watches.watched_paths == []  # noqa: SLF001
    runtime.request_stop()
    await asyncio.wait_for(task, timeout=5)
    assert runtime._workspace_watches is None  # noqa: SLF001
