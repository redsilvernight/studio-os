"""P3 x P4 gate: a runtime `server_origin` change (A -> B -> A) never crosses outboxes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.daemon.runtime import DaemonRuntime
from studio_client.errors import TransportError
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
from studio_client.tokens import MemoryTokenStore, MissingMachineToken
from studio_contracts.events import EventCreate, EventType
from studio_contracts.local.identity import IdentityBinding

MACHINE = uuid4()
ORIGIN_A = "https://a.example"
ORIGIN_B = "https://b.example"
POLICY = RetryPolicy(max_attempts=2, backoff_initial=0.01, backoff_max=0.02)


def binding(origin: str) -> IdentityBinding:
    return IdentityBinding(server_origin=origin, profile_id="main", machine_id=MACHINE)


def client_config(origin: str) -> ClientConfig:
    return ClientConfig(
        api_base_url=f"{origin}/api/v1",
        profile_id="main",
        machine_id=MACHINE,
        heartbeat_interval_seconds=0.01,
        heartbeat_jitter_ratio=0,
    )


def runtime(origin: str, root: Path) -> DaemonRuntime:
    instance = DaemonRuntime(client_config(origin), data_root=root)
    instance._legacy_outbox_path = root / "absent.sqlite3"  # noqa: SLF001
    return instance


def event() -> EventCreate:
    return EventCreate(
        event_id=uuid4(),
        event_type=EventType.TASK_CREATED,
        project_id=uuid4(),
        actor_type="agent",
        actor_id=uuid4(),
        client_timestamp=datetime.now(UTC),
        payload={"title": "queued under A"},
    )


def queue_under(origin: str, root: Path) -> tuple[Path, UUID]:
    """What a running daemon bound to `origin` leaves behind in its own partition."""
    owner = runtime(origin, root)
    store = OutboxStore(connect(owner.outbox_path))
    store.bind_identity(owner.binding)
    queued = event()
    with transaction(store.connection):
        store.enqueue_event(queued)
    store.connection.close()
    return owner.outbox_path, queued.event_id


def test_each_origin_gets_its_own_partition(tmp_path: Path) -> None:
    path_a = runtime(ORIGIN_A, tmp_path).outbox_path
    path_b = runtime(ORIGIN_B, tmp_path).outbox_path
    assert path_a != path_b
    assert path_a == partitioned_outbox_path(binding(ORIGIN_A), root=tmp_path / "outbox")


async def test_a_to_b_never_replays_a_events_on_b_and_b_to_a_restores_them(
    tmp_path: Path,
) -> None:
    path_a, queued_id = queue_under(ORIGIN_A, tmp_path)

    b_store = OutboxStore(connect(runtime(ORIGIN_B, tmp_path).outbox_path))
    b_store.bind_identity(binding(ORIGIN_B))
    client_b = AsyncMock()
    outcome_b = await OutboxReplayer(
        b_store, client_b, POLICY, active_binding=binding(ORIGIN_B)
    ).replay_ready()
    assert not outcome_b.identity_mismatch
    client_b.post_event.assert_not_awaited()
    assert b_store.pending_count() == 0

    a_store = OutboxStore(connect(path_a))
    assert a_store.pending_count() == 1
    client_a = AsyncMock()
    client_a.post_event.return_value = None
    await OutboxReplayer(a_store, client_a, POLICY, active_binding=binding(ORIGIN_A)).replay_ready()
    sent = [call.args[0].event_id for call in client_a.post_event.await_args_list]
    assert sent == [queued_id]
    client_b.post_event.assert_not_awaited()


async def test_forcing_a_partition_under_the_other_identity_fails_closed(tmp_path: Path) -> None:
    path_a, _ = queue_under(ORIGIN_A, tmp_path)
    forced = OutboxStore(connect(path_a))

    with pytest.raises(OutboxIdentityError):
        forced.bind_identity(binding(ORIGIN_B))

    client = AsyncMock()
    outcome = await OutboxReplayer(
        forced, client, POLICY, active_binding=binding(ORIGIN_B)
    ).replay_ready()
    assert outcome.identity_mismatch
    client.post_event.assert_not_awaited()
    client.send_mutation.assert_not_awaited()
    assert forced.list_pending(OutboxTable.EVENTS, ready_only=False)


async def test_a_machine_credential_for_a_is_never_presented_to_b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STUDIO_CLIENT_MACHINE_TOKEN", raising=False)
    tokens = MemoryTokenStore()
    tokens.set_token(ORIGIN_A, "secret-for-a")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    async with StudioApiClient(
        client_config(ORIGIN_B), token_store=tokens, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(MissingMachineToken):
            await client.list_projects()
    assert seen == []


async def test_an_environment_token_bound_to_a_is_never_presented_to_b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUDIO_CLIENT_MACHINE_TOKEN", "env-token-of-a")
    monkeypatch.setenv("STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN", ORIGIN_A)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    async with StudioApiClient(
        client_config(ORIGIN_B),
        token_store=MemoryTokenStore(),
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(MissingMachineToken):
            await client.list_projects()
    assert seen == []


async def test_an_offline_server_keeps_the_partition_pending_and_never_leaks_to_b(
    tmp_path: Path,
) -> None:
    path_a, queued_id = queue_under(ORIGIN_A, tmp_path)
    store = OutboxStore(connect(path_a))
    offline = AsyncMock()
    offline.post_event.side_effect = TransportError("server unreachable")
    await OutboxReplayer(store, offline, POLICY, active_binding=binding(ORIGIN_A)).replay_ready()
    assert store.pending_count() == 1

    other = AsyncMock()
    b_store = OutboxStore(connect(runtime(ORIGIN_B, tmp_path).outbox_path))
    b_store.bind_identity(binding(ORIGIN_B))
    await OutboxReplayer(b_store, other, POLICY, active_binding=binding(ORIGIN_B)).replay_ready()
    other.post_event.assert_not_awaited()

    await asyncio.sleep(POLICY.backoff_max * 2)
    back = AsyncMock()
    back.post_event.return_value = None
    reconnected = OutboxStore(connect(path_a))
    await OutboxReplayer(reconnected, back, POLICY, active_binding=binding(ORIGIN_A)).replay_ready()
    assert [call.args[0].event_id for call in back.post_event.await_args_list] == [queued_id]


async def test_running_b_leaves_the_old_origin_outbox_untouched(tmp_path: Path) -> None:
    path_a, _ = queue_under(ORIGIN_A, tmp_path)
    before = path_a.read_bytes()
    owner = runtime(ORIGIN_B, tmp_path)
    store = OutboxStore(connect(owner.outbox_path))
    store.bind_identity(owner.binding)
    store.connection.close()
    assert owner.outbox_path != path_a
    assert path_a.read_bytes() == before


async def test_a_daemon_already_active_for_the_profile_refuses_a_second_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import studio_client.daemon.runtime as runtime_module
    from studio_client.daemon import AlreadyRunningError

    class Idle:
        async def __aenter__(self) -> Idle:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Waiting:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.stop = asyncio.Event()
            self.last_attempt_at = None
            self.last_success_at = None
            self.last_error = None
            self.last_replay = None

        def request_stop(self) -> None:
            self.stop.set()

        async def run(self) -> None:
            await self.stop.wait()

    monkeypatch.setattr(runtime_module, "StudioApiClient", lambda _config: Idle())
    monkeypatch.setattr(runtime_module, "HeartbeatDaemon", Waiting)
    first = runtime(ORIGIN_A, tmp_path)
    task = asyncio.create_task(first.run())
    await asyncio.sleep(0.1)
    with pytest.raises(AlreadyRunningError):
        await runtime(ORIGIN_A, tmp_path).run()
    other_origin = runtime(ORIGIN_B, tmp_path)
    assert other_origin.outbox_path != first.outbox_path
    first.request_stop()
    await asyncio.wait_for(task, timeout=5)
