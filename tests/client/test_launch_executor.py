from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from studio_client.daemon.launch_executor import LaunchExecutor, ResolvedLaunch
from studio_client.daemon.launch_prepare import LaunchPreparer
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.daemon.launch_runner import LaunchRunner
from studio_client.errors import StudioApiError
from studio_client.harness.base import AccessMode, HarnessAdapter, HarnessContext
from studio_client.outbox import OutboxStore
from studio_client.outbox.models import OutboxTable
from studio_client.outbox.store import connect
from studio_client.usage import USAGE_PATH, UsageWriteQueue
from studio_client.usage.recorder import LaunchUsageRecorder
from studio_contracts.auth import Agent, AgentCreate
from studio_contracts.task_launch import TaskLaunch, TaskLaunchStatus
from studio_contracts.usage import MeasurementCoverage, UsageLedgerEntryCreate


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

    def headless_safety_argv(self, *, allow_production: bool, mode: AccessMode) -> tuple[str, ...]:
        return ()

    def resolve_executable(self, ctx: HarnessContext) -> Path:
        return Path(sys.executable)

    def headless_argv(
        self, prompt: str, *, mode: AccessMode = AccessMode.WORKSPACE_WRITE
    ) -> tuple[str, ...]:
        return self._argv

    def headless_environment(
        self, ctx: HarnessContext, *, model: str | None, isolation_dir: Path, credential: str
    ) -> dict[str, str]:
        assert isolation_dir.is_dir()
        assert credential == "ephemeral-token"  # noqa: S105
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
        self.machine_id = uuid4()
        self.agents: dict[str, Agent] = {}
        self.ensure_inputs: list[AgentCreate] = []
        self.credential_launch_ids: list[UUID] = []

    async def ensure_agent(self, agent_in: AgentCreate) -> tuple[Agent, bool]:
        self.ensure_inputs.append(agent_in)
        assert agent_in.stable_key is not None
        if agent_in.stable_key in self.agents:
            return self.agents[agent_in.stable_key], False
        now = datetime.now(UTC)
        agent = Agent(
            id=uuid4(),
            machine_id=self.machine_id,
            created_at=now,
            updated_at=now,
            version=1,
            **agent_in.model_dump(),
        )
        self.agents[agent_in.stable_key] = agent
        return agent, True

    async def get_task_launch(self, launch_id: UUID) -> TaskLaunch:
        return _launch(status=self.statuses.get(launch_id, TaskLaunchStatus.RUNNING))

    async def get_task(self, task_id: UUID) -> Any:
        return SimpleNamespace(title="Demo task")

    async def issue_launch_credential(self, launch_id: UUID) -> Any:
        self.credential_launch_ids.append(launch_id)
        return SimpleNamespace(token="ephemeral-token")  # noqa: S106


def _executor(
    tmp_path: Path,
    repo: Path,
    adapter: HarnessAdapter,
    client: FakeClient,
    *,
    timeout: float = 30.0,
    secrets: tuple[str, ...] = (),
    models: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
    home: Path | None = None,
) -> tuple[LaunchExecutor, OutboxStore]:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))

    async def resolve(launch: TaskLaunch) -> ResolvedLaunch | None:
        return ResolvedLaunch(
            repo_root=repo,
            task_title="Demo task",
            adapter=adapter,
            ctx=HarnessContext(
                workspace_root=repo,
                mcp_url="http://x",
                env=env or {},
                probe_cwd=repo,
                home=home or tmp_path,
            ),
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


def _body(excerpt: object) -> str:
    lines = str(excerpt).splitlines()
    if lines and lines[0].startswith("[studio:launch_diagnostics]"):
        lines = lines[1:]
    return "\n".join(lines).strip()


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
    assert _body(rows[-1].payload["output_excerpt"]) == "ok"


async def test_requested_launch_model_does_not_invent_an_observed_identity(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = FakeClient()
    prompts: list[str] = []

    class PromptAdapter(FakeAdapter):
        def headless_argv(
            self, prompt: str, *, mode: AccessMode = AccessMode.WORKSPACE_WRITE
        ) -> tuple[str, ...]:
            prompts.append(prompt)
            return super().headless_argv(prompt, mode=mode)

    executor, _ = _executor(tmp_path, repo, PromptAdapter(("-c", "print('ok')")), client)
    for model in ("provider/model-a", "provider/model-a", "provider/model-b", None):
        executor._models = {} if model is None else {"fake": model}
        launch = _launch().model_copy(update={"agent_stable_key": "architect"})
        executor.submit(launch)
        await executor._tasks[launch.id]

    first, repeated, changed, unknown = client.ensure_inputs
    assert first == repeated
    assert first.stable_key == "agents-ensure-fake"
    assert changed.stable_key == "agents-ensure-fake"
    assert unknown.stable_key == "agents-ensure-fake"
    assert len(client.agents) == 1
    assert first.display_name == "studio-fake"
    assert first.harness == "fake"
    assert first.provider is None
    assert first.model is None
    assert changed.model is None
    assert unknown.model is None
    assert unknown.harness == "fake"
    assert unknown.display_name == "studio-fake"
    identities = [
        next(line for line in prompt.splitlines() if line.startswith("agent_id :"))
        for prompt in prompts
    ]
    assert identities[0] == identities[1]
    assert len(set(identities)) == 1
    for prompt, agent_in in zip(prompts, client.ensure_inputs, strict=True):
        assert f"agent_id : {client.agents[agent_in.stable_key or ''].id}" in prompt


async def test_agent_identity_failure_never_starts_or_issues_a_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingClient(FakeClient):
        async def ensure_agent(self, agent_in: AgentCreate) -> tuple[Agent, bool]:
            raise StudioApiError(409, "idempotency_key_payload_mismatch", "durable-token")

    repo = _repo(tmp_path)
    client = FailingClient()
    executor, store = _executor(tmp_path, repo, FakeAdapter(("-c", "print('ok')")), client)
    starts: list[object] = []
    monkeypatch.setattr(executor._runner, "start", lambda *args, **kwargs: starts.append(args))
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    assert starts == []
    assert client.credential_launch_ids == []
    rows = store.list_pending(OutboxTable.MUTATIONS)
    assert _statuses(store) == ["preparing", "failed"]
    assert rows[-1].payload["reason_code"] == "preparation_failed"
    assert rows[-1].payload["output_excerpt"] == "[studio:agent_identity_unavailable]"
    assert "durable-token" not in str(rows[-1].payload)
    assert "durable-token" not in caplog.text


async def test_launched_harness_never_inherits_the_daemon_secrets(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    script = (
        "import os; print(os.environ.get('STUDIO_CLIENT_MACHINE_TOKEN'),"
        " os.environ.get('AWS_SECRET_ACCESS_KEY'), 'PATH' in os.environ)"
    )
    executor, store = _executor(
        tmp_path,
        repo,
        FakeAdapter(("-c", script)),
        FakeClient(),
        env={
            "STUDIO_CLIENT_MACHINE_TOKEN": "durable-token",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "PATH": os.environ.get("PATH", ""),
        },
    )
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    rows = store.list_pending(OutboxTable.MUTATIONS)
    assert _body(rows[-1].payload["output_excerpt"]) == "None None True"


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
    model, isolation = _body(rows[-1].payload["output_excerpt"]).split()
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


async def test_excerpt_strips_ansi_escapes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    script = "print('\\x1b[0mgreen\\x1b[0m')"
    executor, store = _executor(tmp_path, repo, FakeAdapter(("-c", script)), FakeClient())
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    excerpt = store.list_pending(OutboxTable.MUTATIONS)[-1].payload["output_excerpt"]
    assert "\x1b" not in excerpt
    assert _body(excerpt) == "green"


class _MachineTokenAdapter(FakeAdapter):
    def headless_environment(
        self, ctx: HarnessContext, *, model: str | None, isolation_dir: Path, credential: str
    ) -> dict[str, str]:
        env = super().headless_environment(
            ctx, model=model, isolation_dir=isolation_dir, credential=credential
        )
        env["STUDIO_CLIENT_MACHINE_TOKEN"] = credential
        return env


async def test_excerpt_redacts_the_harness_machine_token(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    script = "import os; print(os.environ.get('STUDIO_CLIENT_MACHINE_TOKEN'))"
    executor, store = _executor(tmp_path, repo, _MachineTokenAdapter(("-c", script)), FakeClient())
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    excerpt = store.list_pending(OutboxTable.MUTATIONS)[-1].payload["output_excerpt"]
    assert "ephemeral-token" not in excerpt
    assert "<token>" in excerpt


async def test_terminal_before_start_reports_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = FakeClient()
    executor, store = _executor(tmp_path, repo, FakeAdapter(("-c", "print('ok')")), client)
    launch = _launch()
    client.statuses[launch.id] = TaskLaunchStatus.CANCELLED
    executor.submit(launch)
    await executor._tasks[launch.id]

    assert store.list_pending(OutboxTable.MUTATIONS) == []


async def _wait_for_status(store: OutboxStore, status: str, *, deadline: float = 60.0) -> None:
    async with asyncio.timeout(deadline):
        while not any(
            r.payload["status"] == status for r in store.list_pending(OutboxTable.MUTATIONS)
        ):
            await asyncio.sleep(0.02)


class BlockingPreparer(LaunchPreparer):
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def prepare(self, request: Any) -> Any:
        self.entered.set()
        assert self.release.wait(timeout=60)
        return super().prepare(request)


async def test_cancellation_while_preparing_stops_without_running_report(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    client = FakeClient()
    executor, store = _executor(
        tmp_path, repo, FakeAdapter(("-c", "import time; time.sleep(30)")), client, timeout=30
    )
    preparer = BlockingPreparer()
    executor._preparer = preparer
    launch = _launch()
    executor.submit(launch)
    task = executor._tasks[launch.id]
    await asyncio.to_thread(preparer.entered.wait, 60)
    client.statuses[launch.id] = TaskLaunchStatus.CANCELLED
    await executor._observe()
    preparer.release.set()
    await asyncio.gather(task, return_exceptions=True)

    assert _statuses(store) == ["preparing"]
    assert executor._processes == {}


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
    await _wait_for_status(store, "running")
    client.statuses[launch.id] = TaskLaunchStatus.CANCELLED
    await executor._observe()
    await asyncio.gather(task, return_exceptions=True)

    assert _statuses(store) == ["preparing", "running"]


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
    await _wait_for_status(store, "running")
    client.statuses[launch.id] = TaskLaunchStatus.EXPIRED
    await executor._observe()
    await asyncio.gather(task, return_exceptions=True)

    assert "succeeded" not in _statuses(store)
    assert "failed" not in _statuses(store)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "usage" / "claude_code" / "2.1.287"


def _usage_executor(
    tmp_path: Path, repo: Path, adapter: FakeAdapter
) -> tuple[LaunchExecutor, OutboxStore]:
    executor, store = _executor(tmp_path, repo, adapter, FakeClient())
    executor._usage = LaunchUsageRecorder(UsageWriteQueue(store))
    return executor, store


def _print_file(path: Path) -> FakeAdapter:
    return FakeAdapter(("-c", f"import sys; sys.stdout.write(open({str(path)!r}).read())"))


def _rows_by_kind(store: OutboxStore, kind: str) -> list[Any]:
    return [row for row in store.list_pending(OutboxTable.MUTATIONS) if row.extra["kind"] == kind]


async def test_claude_run_produces_a_measured_usage_entry(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    executor, store = _usage_executor(tmp_path, repo, _print_file(FIXTURES / "success.json"))
    launch = _launch().model_copy(update={"harness_id": "claude-code"})
    executor.submit(launch)
    await executor._tasks[launch.id]

    reports = _rows_by_kind(store, "task_launch_report")
    assert [row.payload["status"] for row in reports] == ["preparing", "running", "succeeded"]
    # The readable result follows the protocol diagnostics header.
    assert reports[-1].payload["output_excerpt"].splitlines()[-1] == "OK"
    (usage,) = _rows_by_kind(store, "usage.create")
    entry = UsageLedgerEntryCreate.model_validate(usage.payload)
    assert usage.extra["path"] == USAGE_PATH
    assert entry.source_event_id == f"task-launch.{launch.id}"
    assert entry.task_launch_id == launch.id
    assert entry.machine_id == launch.machine_id
    assert entry.provenance.collector == "studio-claude-code"
    assert entry.provenance.harness == "claude-code"
    assert entry.provenance.model == "claude-opus-5-5"
    assert entry.tokens_in.value == 2
    assert entry.tokens_cached.value == 32926
    assert entry.cost.coverage is MeasurementCoverage.MEASURED
    assert entry.duration.coverage is MeasurementCoverage.MEASURED
    assert entry.period_end >= entry.period_start


async def test_corrupted_claude_output_never_fails_the_run(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    executor, store = _usage_executor(tmp_path, repo, _print_file(FIXTURES / "corrupted.json"))
    launch = _launch().model_copy(update={"harness_id": "claude-code"})
    executor.submit(launch)
    await executor._tasks[launch.id]

    reports = _rows_by_kind(store, "task_launch_report")
    assert reports[-1].payload["status"] == "succeeded"
    (usage,) = _rows_by_kind(store, "usage.create")
    entry = UsageLedgerEntryCreate.model_validate(usage.payload)
    assert entry.tokens_in.value is None
    assert entry.tokens_in.coverage is MeasurementCoverage.UNKNOWN
    assert entry.cost.coverage is MeasurementCoverage.UNKNOWN
    assert entry.duration.coverage is MeasurementCoverage.MEASURED


async def test_uncertified_harness_records_duration_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    executor, store = _usage_executor(tmp_path, repo, FakeAdapter(("-c", "print('ok')")))
    launch = _launch().model_copy(update={"harness_id": "codex"})
    executor.submit(launch)
    await executor._tasks[launch.id]

    assert (
        _rows_by_kind(store, "task_launch_report")[-1]
        .payload["output_excerpt"]
        .splitlines()[-1]
        .strip()
        == "ok"
    )
    (usage,) = _rows_by_kind(store, "usage.create")
    entry = UsageLedgerEntryCreate.model_validate(usage.payload)
    assert entry.provenance.collector == "studio-runner"
    assert entry.coverage_by_metric == {
        "tokens_in": MeasurementCoverage.UNKNOWN,
        "tokens_out": MeasurementCoverage.UNKNOWN,
        "tokens_cached": MeasurementCoverage.UNKNOWN,
        "cost": MeasurementCoverage.UNKNOWN,
        "duration": MeasurementCoverage.MEASURED,
    }


async def test_failing_usage_queue_never_fails_the_run(tmp_path: Path) -> None:
    class BrokenQueue(UsageWriteQueue):
        def enqueue_entry(self, entry: Any, *, idempotency_key: UUID) -> bool:
            raise RuntimeError("disk full")

    repo = _repo(tmp_path)
    executor, store = _executor(tmp_path, repo, FakeAdapter(("-c", "print('ok')")), FakeClient())
    executor._usage = LaunchUsageRecorder(BrokenQueue(store))
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]

    assert _statuses(store) == ["preparing", "running", "succeeded"]


async def test_unsupported_safety_refuses_before_preparing_or_executing(tmp_path: Path) -> None:
    marker = tmp_path / "production-executed"
    adapter = FakeAdapter(("-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"))
    adapter.headless_safety_argv = HarnessAdapter.headless_safety_argv.__get__(adapter, FakeAdapter)  # type: ignore[method-assign]
    repo = _repo(tmp_path)
    executor, store = _executor(tmp_path, repo, adapter, FakeClient())
    launch = _launch()
    executor.submit(launch)
    await executor._tasks[launch.id]
    assert not marker.exists()
    rows = store.list_pending(OutboxTable.MUTATIONS)
    assert [row.payload["status"] for row in rows] == ["failed"]
    assert "production_safety_unsupported" in str(rows[0].payload["output_excerpt"])
    assert not (tmp_path / f"project-wt-{launch.task_id.hex[:8]}").exists()
