"""Wave 1b: a successful heartbeat must yield a valid, reportable health."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.daemon.heartbeat import HeartbeatDaemon
from studio_client.daemon.runtime import DaemonRuntime


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


class OkClient:
    async def send_heartbeat(self, machine_id: Any, agent_id: Any) -> None:
        return None


def test_health_after_a_successful_heartbeat_is_valid(tmp_path: Path) -> None:
    config = ClientConfig(api_base_url="https://a.example", profile_id="main", machine_id=uuid4())
    heartbeat = HeartbeatDaemon(OkClient(), config)  # type: ignore[arg-type]

    async def one_beat() -> None:
        task = asyncio.create_task(heartbeat.run())
        while heartbeat.last_success_at is None:
            await asyncio.sleep(0)
        heartbeat.request_stop()
        await task

    asyncio.run(one_beat())
    assert heartbeat.last_attempt_at is not None
    assert heartbeat.last_success_at is not None
    assert heartbeat.last_success_at <= heartbeat.last_attempt_at

    health = DaemonRuntime._heartbeat_health(heartbeat)
    assert health.last_success_at == heartbeat.last_success_at
    assert health.error is None
