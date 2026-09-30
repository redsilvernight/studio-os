from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from studio_contracts.auth import MachineCapabilities

from studio_client.capabilities import build_capabilities, registered_project_ids
from studio_client.config import ClientConfig
from studio_client.daemon.heartbeat import HeartbeatDaemon
from studio_client.harness.base import (
    AdapterPlan,
    Detection,
    DetectionState,
    HarnessAdapter,
    HarnessContext,
)
from studio_client.harness.registry import HarnessRegistry


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
    registry = HarnessRegistry(
        [StubAdapter(Detection(DetectionState.CONFIGURED, version="1.0"))]
    )
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
    registry = HarnessRegistry(
        [StubAdapter(Detection(DetectionState.NOT_INSTALLED))]
    )
    caps = build_capabilities(config, registry=registry)
    assert caps.project_ids == []
    assert caps.accepts_launches is False
    (harness,) = caps.harnesses
    assert harness.detected is False and harness.configured is False


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
            registry=HarnessRegistry(
                [StubAdapter(Detection(DetectionState.CONFIGURED))]
            ),
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
