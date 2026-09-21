from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import studio_client.daemon.runtime as runtime_module
from studio_client.config import ClientConfig
from studio_client.daemon.runtime import DaemonRuntime, InstanceLock, server_origin
from studio_client.outbox import (
    OutboxIdentityError,
    OutboxReplayer,
    OutboxStore,
    connect,
    partitioned_outbox_path,
    transaction,
)
from studio_client.retry import RetryPolicy
from studio_contracts.local.identity import IdentityBinding


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


def binding(*, origin: str = "https://studio.example", profile: str = "main", machine=None):
    return IdentityBinding(
        server_origin=origin,
        profile_id=profile,
        machine_id=machine or uuid4(),
    )


def config(machine_id=None) -> ClientConfig:
    return ClientConfig(
        api_base_url="https://studio.example/api/v1",
        profile_id="main",
        machine_id=machine_id or uuid4(),
        heartbeat_interval_seconds=0.01,
        heartbeat_jitter_ratio=0,
    )


def test_server_origin_and_partition_path_are_deterministic(tmp_path: Path) -> None:
    machine_id = uuid4()
    first = binding(machine=machine_id)
    second = binding(profile="other", machine=machine_id)
    assert server_origin("HTTPS://Studio.Example/api/v1/") == "https://studio.example"
    assert partitioned_outbox_path(first, root=tmp_path) == partitioned_outbox_path(
        first, root=tmp_path
    )
    assert partitioned_outbox_path(first, root=tmp_path) != partitioned_outbox_path(
        second, root=tmp_path
    )


def test_instance_lock_refuses_a_second_holder(tmp_path: Path) -> None:
    first = InstanceLock(tmp_path / "daemon.lock")
    second = InstanceLock(tmp_path / "daemon.lock")
    assert first.acquire()
    try:
        assert not second.acquire()
    finally:
        first.release()
    assert second.acquire()
    second.release()


def test_non_empty_unbound_outbox_is_not_adopted(tmp_path: Path) -> None:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    with transaction(store.connection):
        store.enqueue_marker(uuid4(), "recording.marker.created", {})
    with pytest.raises(OutboxIdentityError) as caught:
        store.bind_identity(binding())
    assert caught.value.mismatched == ("binding_missing",)


@pytest.mark.asyncio
async def test_replay_identity_mismatch_never_calls_client(tmp_path: Path) -> None:
    active = binding()
    wrong = active.model_copy(update={"profile_id": "other"})
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    store.bind_identity(active)
    client = AsyncMock()
    replayer = OutboxReplayer(
        store,
        client,
        RetryPolicy(max_attempts=3, backoff_initial=0.01, backoff_max=0.1),
        active_binding=wrong,
    )
    outcome = await replayer.replay_ready()
    assert outcome.identity_mismatch
    client.post_event.assert_not_awaited()
    client.send_mutation.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_assembles_existing_services_and_stops_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeHeartbeat:
        def __init__(self, _client, _config, *, agent_id=None, replayer=None):
            self.replayer = replayer
            self.stop = asyncio.Event()
            self.last_attempt_at = None
            self.last_success_at = None
            self.last_error = None
            self.last_replay = None

        def request_stop(self) -> None:
            self.stop.set()

        async def run(self) -> None:
            started.set()
            await self.stop.wait()

    monkeypatch.setattr(runtime_module, "StudioApiClient", lambda _config: FakeClient())
    monkeypatch.setattr(runtime_module, "HeartbeatDaemon", FakeHeartbeat)
    monkeypatch.setattr(runtime_module, "build_watchers", lambda _config, _store: [])

    runtime = DaemonRuntime(config(), data_root=tmp_path)
    runtime._legacy_outbox_path = tmp_path / "legacy.sqlite3"
    task = asyncio.create_task(runtime.run())
    await asyncio.wait_for(started.wait(), timeout=1)
    assert runtime.health().status.state.value == "running"
    runtime.request_stop()
    await asyncio.wait_for(task, timeout=1)
    assert runtime.health().status.state.value == "stopped"
