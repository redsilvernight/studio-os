from __future__ import annotations

import asyncio
import threading
import time
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
    OutboxTable,
    connect,
    partitioned_outbox_path,
    transaction,
)
from studio_client.retry import RetryPolicy
from studio_contracts.local.common import ComponentState, LocalErrorCode
from studio_contracts.local.identity import IdentityBinding

HANG_GUARD_SECONDS = 30


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


async def wait_until_started(started: asyncio.Event, run_task: asyncio.Task[None]) -> None:
    started_waiter = asyncio.create_task(started.wait())
    try:
        done, _ = await asyncio.wait(
            {started_waiter, run_task},
            timeout=HANG_GUARD_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        started_waiter.cancel()
    if started_waiter in done:
        return
    if run_task in done:
        run_task.result()
        pytest.fail("DaemonRuntime.run() returned before its services started")
    run_task.cancel()
    pytest.fail(f"DaemonRuntime services did not start within {HANG_GUARD_SECONDS}s")


async def wait_until_stopped(run_task: asyncio.Task[None]) -> None:
    done, _ = await asyncio.wait({run_task}, timeout=HANG_GUARD_SECONDS)
    if run_task not in done:
        run_task.cancel()
        pytest.fail(f"DaemonRuntime did not stop within {HANG_GUARD_SECONDS}s")
    run_task.result()


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
        def __init__(
            self,
            _client,
            _config,
            *,
            agent_id=None,
            replayer=None,
            capabilities_provider=None,
            launch_puller=None,
            launch_executor=None,
        ):
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
    monkeypatch.setattr(runtime_module, "build_godot_watchers", lambda _config, _store: [])

    runtime = DaemonRuntime(config(), data_root=tmp_path)
    runtime._legacy_outbox_path = tmp_path / "legacy.sqlite3"
    task = asyncio.create_task(runtime.run())
    await wait_until_started(started, task)
    assert runtime.health().status.state.value == "running"
    runtime.request_stop()
    await wait_until_stopped(task)
    assert runtime.health().status.state.value == "stopped"


def test_health_is_readable_from_a_thread_other_than_the_runtime_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeHeartbeat:
        def __init__(
            self,
            _client,
            _config,
            *,
            agent_id=None,
            replayer=None,
            capabilities_provider=None,
            launch_puller=None,
            launch_executor=None,
        ):
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
    monkeypatch.setattr(runtime_module, "build_godot_watchers", lambda _config, _store: [])

    runtime = DaemonRuntime(config(), data_root=tmp_path)
    runtime._legacy_outbox_path = tmp_path / "legacy.sqlite3"
    loop_thread = threading.Thread(target=lambda: asyncio.run(runtime.run()), daemon=True)
    loop_thread.start()
    deadline = time.monotonic() + 5
    while runtime.health().status.state.value != "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        health = runtime.health()
        assert health.status.state.value == "running"
        assert health.status.outbox is not None
        assert health.status.outbox.pending_count == 0
    finally:
        runtime.request_stop()
        loop_thread.join(timeout=5)
    assert not loop_thread.is_alive()


@pytest.mark.asyncio
async def test_health_reports_project_isolation_dead_letters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeHeartbeat:
        def __init__(
            self,
            _client,
            _config,
            *,
            agent_id=None,
            replayer=None,
            capabilities_provider=None,
            launch_puller=None,
            launch_executor=None,
        ):
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
    monkeypatch.setattr(runtime_module, "build_godot_watchers", lambda _config, _store: [])

    runtime = DaemonRuntime(config(), data_root=tmp_path)
    runtime._legacy_outbox_path = tmp_path / "legacy.sqlite3"
    task = asyncio.create_task(runtime.run())
    try:
        await wait_until_started(started, task)
        assert runtime.health().outbox_replay.error is None

        project_id = str(uuid4())
        writer = OutboxStore(connect(runtime.outbox_path))
        try:
            with transaction(writer.connection):
                writer.enqueue_marker(marker_id := uuid4(), "recording.marker.created", {})
                writer.move_to_dead_letter(
                    OutboxTable.MARKERS,
                    str(marker_id),
                    f"project_access_denied project={project_id}: 403 forbidden",
                )
                writer.enqueue_marker(other_id := uuid4(), "recording.marker.created", {})
                writer.move_to_dead_letter(OutboxTable.MARKERS, str(other_id), "422 invalid")
        finally:
            writer.connection.close()

        replay = runtime.health().outbox_replay
        assert replay.state is ComponentState.PERMISSION_DENIED
        assert replay.error is not None
        assert replay.error.code is LocalErrorCode.PERMISSION_DENIED
        assert replay.error.retryable is False
        assert replay.error.details == {"dead_letters": 1, "project_ids": project_id}
    finally:
        runtime.request_stop()
        await wait_until_stopped(task)
