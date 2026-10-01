"""End-to-end acceptance test for AIB R5 — "Dashboard → machine → session →
handoff" on two simulated machines, with a fake harness, network cut,
cancellation, local refusal and idempotent replay (roadmap §9; audit §13).

Two fully independent runtimes — machine A ("the dashboard") and machine B
("the target") — share nothing locally: each has its own user, machine,
credential, `ClientConfig`, `StudioApiClient` and outbox SQLite file. The real
Postgres backend behind `app_transport` is the only thing they both touch,
exactly like two developers' machines that never talk to each other directly.

A requests a typed `TaskLaunch` on B (the R2 contract). B pulls it (R3), applies
its own local policy, prepares the task worktree, runs a fake harness in the
`studio_start_work` → work → `studio_handoff` consigne, and reports
`accepted` → `preparing` → `running` → terminal through the offline outbox. The
network is cut around the whole reporting chain, so the outbox alone carries it
and a reconnect replays it in order; a replay attempt while offline must stop
transiently and keep every row.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.services import launch_grants as grants_service
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.services.authz import load_principal
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.daemon.launch_executor import LaunchExecutor, ResolvedLaunch
from studio_client.daemon.launch_policy import LaunchPolicy
from studio_client.daemon.launch_prepare import LaunchPreparer
from studio_client.daemon.launch_puller import LaunchPuller
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.daemon.launch_runner import LaunchRunner
from studio_client.harness.base import HarnessAdapter, HarnessContext
from studio_client.outbox import OutboxReplayer, OutboxStore, OutboxTable, connect
from studio_client.retry import RetryPolicy
from studio_client.tokens import MemoryTokenStore
from studio_contracts.auth import HarnessReport, MachineCapabilities
from studio_contracts.task_launch import (
    TaskLaunch,
    TaskLaunchCreate,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)

HARNESS = "claude-code"
_RETRY = RetryPolicy(max_attempts=1, backoff_initial=0.001, backoff_max=0.002)


def _offline_transport() -> httpx.MockTransport:
    """A real connection failure, not a mock of the client."""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated offline network", request=request)

    return httpx.MockTransport(_handler)


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
    """A watched project repository with the `dev` base branch
    `studio-git-flow` prepares task worktrees from."""
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.email", "studio@example.test")
    _git(repo, "config", "user.name", "Studio Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


class FakeHarness(HarnessAdapter):
    """A local harness double: runs a Python script and records the consigne
    it was handed, so a test can assert the `studio_start_work` / `studio_handoff`
    loop instruction actually travelled to the harness."""

    adapter_id = "fake"
    harness_id = HARNESS
    display_name = "Fake harness"

    def __init__(self, script: str) -> None:
        self._script = script
        self.prompts: list[str] = []

    def resolve_executable(self, ctx: HarnessContext) -> Path:
        return Path(sys.executable)

    def headless_argv(self, prompt: str) -> tuple[str, ...]:
        self.prompts.append(prompt)
        return ("-c", self._script)

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


def _client_config(machine_id: UUID) -> ClientConfig:
    return ClientConfig(
        api_base_url="http://test",
        max_attempts=1,
        backoff_initial=0.001,
        backoff_max=0.002,
        machine_id=machine_id,
    )


def _tokens(token: str) -> MemoryTokenStore:
    store = MemoryTokenStore()
    store.set_token("http://test", token)
    return store


def _client(token: str, machine_id: UUID, transport: Any) -> StudioApiClient:
    return StudioApiClient(_client_config(machine_id), _tokens(token), transport=transport)


async def _fleet(db_session: AsyncSession) -> SimpleNamespace:
    """Two independent developer machines plus the shared project, task and the
    explicit launch grant (AIB-J) that lets A request on B."""
    user_a = await provisioning_service.create_user(
        db_session, "Machine A dev", f"{uuid.uuid4()}@example.test", "developer"
    )
    machine_a, token_a = await provisioning_service.create_machine(
        db_session, user_a.id, "machine-a"
    )
    agent_a = AgentModel(
        machine_id=machine_a.id, display_name="machine-a", agent_kind="claude_code"
    )
    db_session.add(agent_a)
    await db_session.flush()
    await db_session.refresh(agent_a)

    user_b = await provisioning_service.create_user(
        db_session, "Machine B dev", f"{uuid.uuid4()}@example.test", "developer"
    )
    machine_b, token_b = await provisioning_service.create_machine(
        db_session, user_b.id, "machine-b"
    )
    agent_b = AgentModel(
        machine_id=machine_b.id, display_name="machine-b", agent_kind="claude_code"
    )
    db_session.add(agent_b)
    await db_session.flush()
    await db_session.refresh(agent_b)

    project = await projects_service.create_project(
        db_session,
        f"launch-{uuid.uuid4().hex[:8]}",
        "Remote Launch Project",
        None,
        creator=user_a,
    )
    await projects_service.grant_member(
        db_session, project.id, user_b.id, granted_by_user_id=user_a.id
    )
    principal_b = await load_principal(db_session, machine_b)
    await grants_service.grant(db_session, principal_b, machine_b, user_a.id, project.id, None)

    task = TaskModel(project_id=project.id, title="Remote demo task")
    db_session.add(task)
    await db_session.flush()
    await db_session.refresh(task)

    return SimpleNamespace(
        user_a=user_a,
        machine_a=machine_a,
        token_a=token_a,
        agent_a=agent_a,
        user_b=user_b,
        machine_b=machine_b,
        token_b=token_b,
        agent_b=agent_b,
        project=project,
        task=task,
    )


async def _report_capabilities(api_b: StudioApiClient, machine_b: UUID, project_id: UUID) -> None:
    await api_b.send_heartbeat(
        machine_b,
        None,
        MachineCapabilities(
            harnesses=[
                HarnessReport(harness_id=HARNESS, version="1.0.0", detected=True, configured=True)
            ],
            project_ids=[project_id],
            accepts_launches=True,
            running_launches=0,
            max_launches=2,
        ),
    )


async def _request_launch(
    api_a: StudioApiClient,
    project_id: UUID,
    task_id: UUID,
    machine_id: UUID,
    idempotency_key: str,
) -> TaskLaunch:
    payload = TaskLaunchCreate(
        task_id=task_id, machine_id=machine_id, harness_id=HARNESS
    ).model_dump(mode="json")
    response = await api_a.send_mutation(
        "POST",
        f"/api/v1/projects/{project_id}/task-launches",
        payload,
        idempotency_key=idempotency_key,
    )
    return TaskLaunch.model_validate(response.json())


async def _cancel_launch(
    api_a: StudioApiClient, launch_id: UUID, expected_version: int
) -> TaskLaunch:
    response = await api_a.send_mutation(
        "POST",
        f"/api/v1/task-launches/{launch_id}/cancel",
        {"expected_version": expected_version},
        idempotency_key=str(uuid.uuid4()),
    )
    return TaskLaunch.model_validate(response.json())


def _policy(project_id: UUID, **overrides: Any) -> LaunchPolicy:
    base: dict[str, Any] = {
        "opt_in": True,
        "project_ids": frozenset({project_id}),
        "allowed_harnesses": frozenset({HARNESS}),
        "detected_harnesses": frozenset({HARNESS}),
        "max_concurrent": 1,
    }
    base.update(overrides)
    return LaunchPolicy(**base)


def _launch_mutations(store: OutboxStore) -> list[dict[str, Any]]:
    return [row.payload for row in store.list_pending(OutboxTable.MUTATIONS, ready_only=False)]


def _statuses(store: OutboxStore) -> list[str]:
    return [str(payload["status"]) for payload in _launch_mutations(store)]


def _resolver(repo: Path, harness: FakeHarness, task_title: str) -> Any:
    async def resolve(launch: TaskLaunch) -> ResolvedLaunch | None:
        ctx = HarnessContext(
            workspace_root=repo,
            mcp_url="http://127.0.0.1/mcp",
            env=dict(os.environ),
            probe_cwd=repo,
        )
        return ResolvedLaunch(repo_root=repo, task_title=task_title, adapter=harness, ctx=ctx)

    return resolve


async def _wait_for_report(store: OutboxStore, status: str, *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if status in _statuses(store):
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"no {status!r} report was enqueued within {timeout}s")


async def test_two_machine_launch_full_cycle_with_network_cut_and_idempotent_replay(
    tmp_path: Path,
    app_transport: ASGITransport,
    db_session: AsyncSession,
) -> None:
    fleet = await _fleet(db_session)
    repo = _repo(tmp_path)
    outbox_path = tmp_path / "machine-b-outbox.sqlite3"

    try:
        store = OutboxStore(connect(outbox_path))

        async with _client(fleet.token_b, fleet.machine_b.id, app_transport) as api_b:
            await _report_capabilities(api_b, fleet.machine_b.id, fleet.project.id)

            async with _client(fleet.token_a, fleet.machine_a.id, app_transport) as api_a:
                launch_key = str(uuid.uuid4())
                launch = await _request_launch(
                    api_a,
                    fleet.project.id,
                    fleet.task.id,
                    fleet.machine_b.id,
                    launch_key,
                )
                assert launch.status is TaskLaunchStatus.REQUESTED
                assert launch.version == 1
                assert launch.requested_by_user_id == fleet.user_a.id

                # Machine B pulls and accepts, reporting through its outbox.
                reporter = LaunchReporter(store)
                puller = LaunchPuller(
                    api_b, fleet.machine_b.id, lambda: _policy(fleet.project.id), reporter
                )
                accepted = await puller.poll()
                assert [item.id for item in accepted] == [launch.id]
                assert _statuses(store) == ["accepted"]

                # Network cut: replaying the accepted report fails transiently;
                # nothing is lost, nothing is dead-lettered.
                offline = _client(fleet.token_b, fleet.machine_b.id, _offline_transport())
                cut = await OutboxReplayer(store, offline, _RETRY).replay_ready()
                assert cut.succeeded == 0
                assert cut.stopped_on_transient_error is True
                assert cut.dead_lettered == 0
                assert _statuses(store) == ["accepted"]

                # The harness runs offline in the prepared worktree.
                harness = FakeHarness("print('studio launch ok')")
                executor = LaunchExecutor(
                    client=offline,
                    reporter=reporter,
                    preparer=LaunchPreparer(),
                    runner=LaunchRunner(),
                    resolve=_resolver(repo, harness, fleet.task.title),
                    timeout_seconds=30,
                )
                executor.submit(launch)
                await executor._tasks[launch.id]
                await executor.aclose()
                await offline.aclose()

                assert _statuses(store) == [
                    "accepted",
                    "preparing",
                    "running",
                    "succeeded",
                ], [
                    (p["status"], p.get("reason_code"), p.get("output_excerpt"))
                    for p in _launch_mutations(store)
                ]
                assert harness.prompts, "the harness was never handed a consigne"
                consigne = harness.prompts[0]
                assert "studio_start_work" in consigne
                assert "studio_handoff" in consigne
                assert str(fleet.project.id) in consigne
                assert str(fleet.task.id) in consigne

                # Reconnect: the whole report chain replays in order.
                drained = await OutboxReplayer(store, api_b, _RETRY).replay_ready()
                assert drained.succeeded == 4
                assert drained.dead_lettered == 0
                assert store.list_pending(OutboxTable.MUTATIONS, ready_only=False) == []

                final = await api_a.get_task_launch(launch.id)
                assert final.status is TaskLaunchStatus.SUCCEEDED
                assert final.version == 5
                assert "studio launch ok" in (final.output_excerpt or "")

                # Idempotent replay: the same launch request returns the original,
                # and a second replay pass has nothing left to send.
                again = await _request_launch(
                    api_a,
                    fleet.project.id,
                    fleet.task.id,
                    fleet.machine_b.id,
                    launch_key,
                )
                assert again.id == launch.id
                second_drain = await OutboxReplayer(store, api_b, _RETRY).replay_ready()
                assert second_drain.succeeded == 0
                assert second_drain.dead_lettered == 0
                launches = (
                    (
                        await db_session.execute(
                            select(TaskLaunchModel).where(
                                TaskLaunchModel.project_id == fleet.project.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert [row.id for row in launches] == [launch.id]
    finally:
        store.connection.close()


async def test_locally_refused_launch_is_reported_rejected(
    tmp_path: Path,
    app_transport: ASGITransport,
    db_session: AsyncSession,
) -> None:
    fleet = await _fleet(db_session)
    outbox_path = tmp_path / "machine-b-outbox.sqlite3"
    store = OutboxStore(connect(outbox_path))
    try:
        async with _client(fleet.token_b, fleet.machine_b.id, app_transport) as api_b:
            await _report_capabilities(api_b, fleet.machine_b.id, fleet.project.id)
            async with _client(fleet.token_a, fleet.machine_a.id, app_transport) as api_a:
                launch = await _request_launch(
                    api_a,
                    fleet.project.id,
                    fleet.task.id,
                    fleet.machine_b.id,
                    str(uuid.uuid4()),
                )
                reporter = LaunchReporter(store)
                puller = LaunchPuller(
                    api_b,
                    fleet.machine_b.id,
                    lambda: _policy(fleet.project.id, opt_in=False),
                    reporter,
                )
                accepted = await puller.poll()
                assert accepted == []
                [report] = _launch_mutations(store)
                assert report["status"] == "rejected"
                assert report["reason_code"] == TaskLaunchReasonCode.NOT_OPTED_IN.value
                assert report["expected_version"] == 1

                await OutboxReplayer(store, api_b, _RETRY).replay_ready()
                refused = await api_a.get_task_launch(launch.id)
                assert refused.status is TaskLaunchStatus.REJECTED
                assert refused.reason_code is TaskLaunchReasonCode.NOT_OPTED_IN
    finally:
        store.connection.close()


async def test_requester_cancel_stops_a_running_machine_without_terminal_report(
    tmp_path: Path,
    app_transport: ASGITransport,
    db_session: AsyncSession,
) -> None:
    fleet = await _fleet(db_session)
    repo = _repo(tmp_path)
    outbox_path = tmp_path / "machine-b-outbox.sqlite3"
    store = OutboxStore(connect(outbox_path))
    try:
        async with _client(fleet.token_b, fleet.machine_b.id, app_transport) as api_b:
            await _report_capabilities(api_b, fleet.machine_b.id, fleet.project.id)
            async with _client(fleet.token_a, fleet.machine_a.id, app_transport) as api_a:
                launch = await _request_launch(
                    api_a,
                    fleet.project.id,
                    fleet.task.id,
                    fleet.machine_b.id,
                    str(uuid.uuid4()),
                )
                reporter = LaunchReporter(store)
                puller = LaunchPuller(
                    api_b, fleet.machine_b.id, lambda: _policy(fleet.project.id), reporter
                )
                [accepted] = await puller.poll()
                await OutboxReplayer(store, api_b, _RETRY).replay_ready()

                harness = FakeHarness("import time; time.sleep(30)")
                executor = LaunchExecutor(
                    client=api_b,
                    reporter=reporter,
                    preparer=LaunchPreparer(),
                    runner=LaunchRunner(),
                    resolve=_resolver(repo, harness, fleet.task.title),
                    timeout_seconds=30,
                )
                executor.submit(accepted)
                await _wait_for_report(store, "running")
                await OutboxReplayer(store, api_b, _RETRY).replay_ready()

                running = await api_a.get_task_launch(launch.id)
                assert running.status is TaskLaunchStatus.RUNNING
                cancelled = await _cancel_launch(api_a, launch.id, running.version)
                assert cancelled.status is TaskLaunchStatus.CANCELLED

                await executor._observe()
                await asyncio.gather(executor._tasks[accepted.id], return_exceptions=True)
                await executor.aclose()

                assert "succeeded" not in _statuses(store)
                assert "failed" not in _statuses(store)
                final = await api_a.get_task_launch(launch.id)
                assert final.status is TaskLaunchStatus.CANCELLED
    finally:
        store.connection.close()
