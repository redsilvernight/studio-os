from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from studio_client.capabilities import build_capabilities, registered_project_ids
from studio_client.config import ClientConfig
from studio_client.daemon.heartbeat import HeartbeatDaemon
from studio_client.daemon.launch_policy import build_launch_policy
from studio_client.harness.base import (
    AdapterPlan,
    Detection,
    DetectionState,
    HarnessAdapter,
    HarnessContext,
)
from studio_client.harness.registry import HarnessRegistry
from studio_contracts.auth import MachineCapabilities
from studio_contracts.task_launch import TaskLaunch, TaskLaunchReasonCode, TaskLaunchStatus


def _config(**overrides: Any) -> ClientConfig:
    base: dict[str, Any] = {
        "api_base_url": "https://a.example",
        "profile_id": "main",
        "machine_id": uuid4(),
    }
    base.update(overrides)
    return ClientConfig(**base)


class StubAdapter(HarnessAdapter):
    adapter_id = "stub"
    harness_id = "stub-harness"
    display_name = "Stub"

    def __init__(self, detection: Detection) -> None:
        self._detection = detection

    def detect(self, ctx: HarnessContext) -> Detection:
        return self._detection

    def plan(self, ctx: HarnessContext, *, renew: bool = False) -> AdapterPlan:
        return AdapterPlan()

    def read_user_entry(self, ctx: HarnessContext) -> dict[str, object] | None:
        return None

    def write_user_entry(self, ctx: HarnessContext, entry: dict[str, object]) -> None:
        raise NotImplementedError

    def remove_user_entry(self, ctx: HarnessContext) -> None:
        raise NotImplementedError

    def build_entry(self, mcp_url: str, token: str) -> dict[str, object]:
        raise NotImplementedError


def test_registered_project_ids_collects_git_and_godot_without_paths() -> None:
    git_project = uuid4()
    godot_project = uuid4()
    config = _config(
        git_watches=[{"repo_path": "/tmp/repo", "project_id": git_project}],
        godot_watch_project_id=godot_project,
    )
    ids = registered_project_ids(config)
    assert sorted(ids) == sorted([git_project, godot_project])
    assert all(isinstance(item, type(git_project)) for item in ids)


def test_build_capabilities_reports_ids_and_opt_in() -> None:
    project = uuid4()
    config = _config(
        git_watches=[{"repo_path": "/tmp/repo", "project_id": project}],
        launch_opt_in=True,
        max_concurrent_launches=3,
    )
    registry = HarnessRegistry([StubAdapter(Detection(DetectionState.CONFIGURED, version="1.0"))])
    caps = build_capabilities(config, registry=registry, running_launches=2)
    assert caps.project_ids == [project]
    assert caps.accepts_launches is True
    assert (caps.running_launches, caps.max_launches) == (2, 3)
    (harness,) = caps.harnesses
    assert harness.harness_id == "stub-harness"
    assert harness.detected is True and harness.configured is True
    assert harness.version == "1.0"
    assert MachineCapabilities.model_validate(caps.model_dump(mode="json")) == caps


def test_build_capabilities_defaults_to_closed() -> None:
    config = _config()
    registry = HarnessRegistry([StubAdapter(Detection(DetectionState.NOT_INSTALLED))])
    caps = build_capabilities(config, registry=registry)
    assert caps.project_ids == []
    assert caps.accepts_launches is False
    (harness,) = caps.harnesses
    assert harness.detected is False and harness.configured is False


def test_workspace_projects_are_reported_and_honoured() -> None:
    git_project, workspace_project = uuid4(), uuid4()
    config = _config(
        git_watches=[{"repo_path": "/tmp/repo", "project_id": git_project}],
        launch_opt_in=True,
        launch_allowed_harnesses=("stub-harness",),
    )
    registry = HarnessRegistry([StubAdapter(Detection(DetectionState.CONFIGURED))])

    caps = build_capabilities(
        config, registry=registry, extra_project_ids=[workspace_project, git_project]
    )
    assert caps.project_ids == sorted([git_project, workspace_project])

    now = datetime.now(UTC)
    launch = TaskLaunch(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        version=1,
        project_id=workspace_project,
        task_id=uuid4(),
        machine_id=uuid4(),
        requested_by_user_id=uuid4(),
        harness_id="stub-harness",
        status=TaskLaunchStatus.REQUESTED,
        expires_at=now + timedelta(minutes=15),
    )
    policy = build_launch_policy(config, registry=registry, extra_project_ids=[workspace_project])
    assert policy.evaluate(launch, active=0) == TaskLaunchReasonCode.NONE
    without = build_launch_policy(config, registry=registry)
    assert without.evaluate(launch, active=0) == TaskLaunchReasonCode.PROJECT_NOT_REGISTERED


def test_daemon_sends_provider_capabilities(tmp_path: Path) -> None:
    config = _config()
    seen: dict[str, Any] = {}

    class RecordingClient:
        async def send_heartbeat(
            self, machine_id: Any, agent_id: Any, capabilities: Any = None
        ) -> None:
            seen["capabilities"] = capabilities

    daemon = HeartbeatDaemon(
        RecordingClient(),  # type: ignore[arg-type]
        config,
        capabilities_provider=lambda: build_capabilities(
            config,
            registry=HarnessRegistry([StubAdapter(Detection(DetectionState.CONFIGURED))]),
        ),
    )

    async def one_beat() -> None:
        task = asyncio.create_task(daemon.run())
        async with asyncio.timeout(10):
            while not seen:
                await asyncio.sleep(0)
        daemon.request_stop()
        await task

    asyncio.run(one_beat())
    assert seen["capabilities"] is not None
    assert seen["capabilities"].harnesses[0].harness_id == "stub-harness"


def test_bootstrap_statuses_report_counts_only_for_repos_with_manifest(tmp_path: Path) -> None:
    from studio_client.bootstrap import make_manifest, write_manifest
    from studio_client.capabilities import bootstrap_statuses

    with_manifest = tmp_path / "with"
    without = tmp_path / "without"
    with_manifest.mkdir()
    without.mkdir()
    write_manifest(with_manifest, make_manifest("p", "P", ["claude-code"]))
    project_a, project_b = uuid4(), uuid4()
    config = _config(
        git_watches=[
            {"repo_path": str(with_manifest), "project_id": str(project_a)},
            {"repo_path": str(without), "project_id": str(project_b)},
        ]
    )
    (status,) = bootstrap_statuses(config)
    assert status.project_id == project_a
    assert status.summary.up_to_date == 0
    assert status.summary.absent > 0
    dumped = status.model_dump_json()
    assert str(tmp_path) not in dumped and "with" not in dumped.replace(str(project_a), "")
