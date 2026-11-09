from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from studio_client.config import ClientConfig
from studio_client.context.library import LibraryContextItem
from studio_client.daemon import skills_bridge
from studio_client.daemon.library_events import CURSOR_FILE_NAME, LibraryEventWatcher
from studio_client.tokens import MemoryTokenStore
from studio_contracts.events import EventEnvelope, EventType
from studio_contracts.local.skills import SkillSyncStatusState

ORIGIN = "https://studio.example"
PROJECT = uuid4()
T0 = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)


def _event(event_type: EventType, at: datetime) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid4(),
        event_type=event_type,
        project_id=PROJECT,
        actor_type="user",
        actor_id=uuid4(),
        client_timestamp=at,
        server_timestamp=at,
    )


class FakeClient:
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []
        self.offline = False

    async def list_events(
        self,
        *,
        project_id: UUID | None = None,
        since: datetime | None = None,
        limit: int = 100,
        **_: Any,
    ) -> list[EventEnvelope]:
        if self.offline:
            raise ConnectionError("network down")
        rows = [e for e in self.events if since is None or e.server_timestamp >= since]
        return sorted(rows, key=lambda e: e.server_timestamp, reverse=True)[:limit]


def _watcher(
    client: FakeClient, tmp_path: Path, calls: list[int], *, fail: list[bool] | None = None
) -> LibraryEventWatcher:
    def on_change() -> None:
        calls.append(1)
        if fail and fail[0]:
            raise RuntimeError("fetch failed")

    return LibraryEventWatcher(
        client,  # type: ignore[arg-type]
        project_ids=lambda: [PROJECT],
        cursor_path=tmp_path / CURSOR_FILE_NAME,
        on_library_change=on_change,
    )


async def test_activation_triggers_once_and_is_not_replayed(tmp_path: Path) -> None:
    client, calls = FakeClient(), []
    client.events = [_event(EventType.TASK_CREATED, T0)]
    watcher = _watcher(client, tmp_path, calls)
    await watcher.poll_once()
    assert calls == []

    client.events.append(_event(EventType.LIBRARY_VERSION_ACTIVATED, T0 + timedelta(seconds=5)))
    await watcher.poll_once()
    assert calls == [1]

    await watcher.poll_once()
    assert calls == [1]


async def test_unrelated_events_do_not_trigger(tmp_path: Path) -> None:
    client, calls = FakeClient(), []
    watcher = _watcher(client, tmp_path, calls)
    await watcher.poll_once()
    client.events.append(_event(EventType.TASK_CREATED, T0))
    await watcher.poll_once()
    assert calls == []


async def test_network_cut_resumes_without_losing_the_event(tmp_path: Path) -> None:
    client, calls = FakeClient(), []
    watcher = _watcher(client, tmp_path, calls)
    await watcher.poll_once()
    client.events.append(_event(EventType.LIBRARY_VERSION_ACTIVATED, T0))

    client.offline = True
    with pytest.raises(ConnectionError):
        await watcher.poll_once()
    assert calls == []

    client.offline = False
    await watcher.poll_once()
    assert calls == [1]


async def test_failed_handler_keeps_the_cursor_so_the_event_is_retried(tmp_path: Path) -> None:
    client, calls, fail = FakeClient(), [], [True]
    watcher = _watcher(client, tmp_path, calls, fail=fail)
    await watcher.poll_once()
    client.events.append(_event(EventType.LIBRARY_RESOURCE_DEPRECATED, T0))

    with pytest.raises(RuntimeError):
        await watcher.poll_once()
    fail[0] = False
    await watcher.poll_once()
    assert calls == [1, 1]
    await watcher.poll_once()
    assert calls == [1, 1]


async def test_cursor_survives_a_restart(tmp_path: Path) -> None:
    client, calls = FakeClient(), []
    await _watcher(client, tmp_path, calls).poll_once()
    client.events.append(_event(EventType.LIBRARY_VERSION_ACTIVATED, T0))
    await _watcher(client, tmp_path, calls).poll_once()
    assert calls == [1]


def _projection(text: str) -> LibraryContextItem:
    return LibraryContextItem(
        library_kind="skill",
        stable_key="standard",
        version=1,
        version_origin="active",
        scope="studio",
        title="skill standard",
        text=text,
        content_schema="studio.library.skill/v1",
    )


def test_mark_update_pending_writes_no_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, data_root = tmp_path / "home", tmp_path / "data"
    home.mkdir()
    token_store = MemoryTokenStore()
    token_store.set_token(ORIGIN, "tok")
    config = ClientConfig(api_base_url=f"{ORIGIN}/api/v1", profile_id="main", machine_id=uuid4())

    async def fake(_config: ClientConfig, _token_store: MemoryTokenStore) -> Any:
        return [_projection("Version one")]

    monkeypatch.setattr(skills_bridge, "_fetch", fake)

    assert skills_bridge.mark_update_pending(config, token_store, home, data_root) is True

    status = skills_bridge._load_status(data_root)
    assert status is not None
    assert status.state is SkillSyncStatusState.UPDATE_PENDING
    assert status.added
    assert list(home.rglob("SKILL.md")) == []
