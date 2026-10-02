from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from studio_client.daemon.launch_executor import LaunchExecutor, ResolvedLaunch
from studio_client.daemon.launch_prepare import LaunchPreparer
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.daemon.launch_runner import LaunchRunner
from studio_client.harness.base import HarnessAdapter, HarnessContext
from studio_client.outbox import OutboxStore
from studio_client.outbox.models import OutboxTable
from studio_client.outbox.store import connect
from studio_contracts.task_launch import TaskLaunch, TaskLaunchStatus


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.email", "studio@example.test")
    _git(repo, "config", "user.name", "Studio Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


def _launch(*, status: TaskLaunchStatus = TaskLaunchStatus.ACCEPTED) -> TaskLaunch:
    now = datetime.now(UTC)
    return TaskLaunch(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        version=1,
        project_id=uuid4(),
        task_id=uuid4(),
        machine_id=uuid4(),
        requested_by_user_id=uuid4(),
        harness_id="fake",
        status=status,
        expires_at=now + timedelta(minutes=15),
    )


class FakeAdapter(HarnessAdapter):
    adapter_id = "fake"
    harness_id = "fake"
    display_name = "Fake"

    def __init__(self, argv: tuple[str, ...]) -> None:
        self._argv = argv

    def resolve_executable(self, ctx: HarnessContext) -> Path:
        return Path(sys.executable)

    def headless_argv(self, prompt: str) -> tuple[str, ...]:
        return self._argv

    def headless_environment(
        self, ctx: HarnessContext, *, model: str | None, isolation_dir: Path
    ) -> dict[str, str]:
        assert isolation_dir.is_dir()
        return {"FAKE_MODEL": model or "", "FAKE_ISOLATION": str(isolation_dir)}

    def detect(self, ctx: HarnessContext) -> Any:
        raise NotImplementedError

    def plan(self, ctx: HarnessContext, *, renew: bool = False) -> Any:
        raise NotImplementedError

    def read_user_entry(self, ctx: HarnessContext) -> Any:
        raise NotImplementedError

    def write_user_entry(self, ctx: HarnessContext, entry: dict[str, object]) -> None:
        raise NotImplementedError

    def remove_user_entry(self, ctx: HarnessContext) -> None:
        raise NotImplementedError

    def build_entry(self, mcp_url: str, token: str) -> dict[str, object]:
        raise NotImplementedError


class FakeClient:
    def __init__(self) -> None:
        self.statuses: dict[UUID, TaskLaunchStatus] = {}

    async def get_task_launch(self, launch_id: UUID) -> TaskLaunch:
        return _launch(status=self.statuses.get(launch_id, TaskLaunchStatus.RUNNING))

    async def get_task(self, task_id: UUID) -> Any:
        return SimpleNamespace(title="Demo task")


def _executor(
    tmp_path: Path,
    repo: Path,
    adapter: FakeAdapter,
    client: FakeClient,
    *,
    timeout: float = 30.0,
    secrets: tuple[str, ...] = (),
    models: dict[str, str] | None = None,
) -> tuple[LaunchExecutor, OutboxStore]:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))

    async def resolve(launch: TaskLaunch) -> ResolvedLaunch | None:
        return ResolvedLaunch(
            repo_root=repo,
            task_title="Demo task",
            adapter=adapter,
            ctx=HarnessContext(workspace_root=repo, mcp_url="http://x", env={}, probe_cwd=repo),
        )

    executor = LaunchExecutor(
        client=client,  # type: ignore[arg-type]
        reporter=LaunchReporter(store),
        preparer=LaunchPreparer(),
        runner=LaunchRunner(),
        resolve=resolve,
        timeout_seconds=timeout,
        secrets=secrets,
        models=models,
    )
    return executor, store


def _statuses(store: OutboxStore) -> list[str]:
    return [str(row.payload["status"]) for row in store.list_pending(OutboxTable.MUTATIONS)]


async def test_success_reports_preparing_running_succeeded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    executor, store = _executor(tmp_path, repo, FakeAdapter(("-c", "print('ok')")), FakeClient())
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    rows = store.list_pending(OutboxTable.MUTATIONS)
    assert [row.payload["status"] for row in rows] == ["preparing", "running", "succeeded"]
    assert [row.payload["expected_version"] for row in rows] == [1, 2, 3]
    assert rows[-1].payload["output_excerpt"].strip() == "ok"


async def test_forced_model_and_isolation_reach_the_process_and_are_cleaned(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    script = "import os; print(os.environ['FAKE_MODEL'], os.environ['FAKE_ISOLATION'])"
    executor, store = _executor(
        tmp_path,
        repo,
        FakeAdapter(("-c", script)),
        FakeClient(),
        models={"fake": "provider/forced"},
    )
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    rows = store.list_pending(OutboxTable.MUTATIONS)
    model, isolation = str(rows[-1].payload["output_excerpt"]).split()
    assert model == "provider/forced"
    assert not Path(isolation).exists()


async def test_nonzero_exit_reports_failed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    executor, store = _executor(
        tmp_path, repo, FakeAdapter(("-c", "import sys; sys.exit(3)")), FakeClient()
    )
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    rows = store.list_pending(OutboxTable.MUTATIONS)
    assert [row.payload["status"] for row in rows] == ["preparing", "running", "failed"]
    assert rows[-1].payload["reason_code"] == "harness_exited"


async def test_timeout_reports_failed_with_timeout_reason(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    executor, store = _executor(
        tmp_path,
        repo,
        FakeAdapter(("-c", "import time; time.sleep(30)")),
        FakeClient(),
        timeout=0.3,
    )
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    rows = store.list_pending(OutboxTable.MUTATIONS)
    assert [row.payload["status"] for row in rows] == ["preparing", "running", "failed"]
    assert rows[-1].payload["reason_code"] == "expired_timeout"


async def test_excerpt_is_redacted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    script = "print('Authorization: Bearer supersecret'); print('TOKENVALUE')"
    executor, store = _executor(
        tmp_path, repo, FakeAdapter(("-c", script)), FakeClient(), secrets=("TOKENVALUE",)
    )
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    excerpt = store.list_pending(OutboxTable.MUTATIONS)[-1].payload["output_excerpt"]
    assert "supersecret" not in excerpt
    assert "TOKENVALUE" not in excerpt
    assert excerpt.count("<token>") == 2


async def test_terminal_before_start_reports_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = FakeClient()
    executor, store = _executor(tmp_path, repo, FakeAdapter(("-c", "print('ok')")), client)
    launch = _launch()
    client.statuses[launch.id] = TaskLaunchStatus.CANCELLED
    executor.submit(launch)
    await executor._tasks[launch.id]

    assert store.list_pending(OutboxTable.MUTATIONS) == []


async def test_cancellation_while_running_stops_without_terminal_report(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = FakeClient()
    executor, store = _executor(
        tmp_path,
        repo,
        FakeAdapter(("-c", "import time; time.sleep(30)")),
        client,
        timeout=30,
    )
    launch = _launch()
    executor.submit(launch)
    task = executor._tasks[launch.id]
    await asyncio.sleep(0.6)
    client.statuses[launch.id] = TaskLaunchStatus.CANCELLED
    await executor._observe()
    await asyncio.gather(task, return_exceptions=True)

    assert [row.payload["status"] for row in store.list_pending(OutboxTable.MUTATIONS)] == [
        "preparing",
        "running",
    ]


async def test_expired_while_running_is_stopped(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = FakeClient()
    executor, store = _executor(
        tmp_path,
        repo,
        FakeAdapter(("-c", "import time; time.sleep(30)")),
        client,
        timeout=30,
    )
    launch = _launch()
    executor.submit(launch)
    task = executor._tasks[launch.id]
    await asyncio.sleep(0.6)
    client.statuses[launch.id] = TaskLaunchStatus.EXPIRED
    await executor._observe()
    await asyncio.gather(task, return_exceptions=True)

    assert "succeeded" not in _statuses(store)
    assert "failed" not in _statuses(store)
