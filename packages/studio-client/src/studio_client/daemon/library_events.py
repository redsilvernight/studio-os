from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from studio_contracts.events import EventEnvelope, EventType

from studio_client.api_client import StudioApiClient
from studio_client.watchers.base import PollingWatcher, SleepFn

DEFAULT_LIBRARY_EVENT_POLL_SECONDS = 30.0
CURSOR_FILE_NAME = "library-events-cursor.json"
EVENTS_PAGE_LIMIT = 500
LIBRARY_TRIGGER_TYPES = frozenset(
    {EventType.LIBRARY_VERSION_ACTIVATED, EventType.LIBRARY_RESOURCE_DEPRECATED}
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class LibraryEventWatcher(PollingWatcher):
    """Polls `GET /events` for each followed project and calls `on_library_change`
    once per poll when a library activation or deprecation was published.

    The per-project cursor (last `server_timestamp` plus the event ids already
    seen at that instant, since `since` is inclusive) only advances after the
    callback succeeded, so a network cut replays the same events on the next
    poll instead of losing them."""

    def __init__(
        self,
        client: StudioApiClient,
        *,
        project_ids: Callable[[], Sequence[UUID]],
        cursor_path: Path,
        on_library_change: Callable[[], object],
        interval_seconds: float = DEFAULT_LIBRARY_EVENT_POLL_SECONDS,
        sleep: SleepFn | None = None,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds, sleep=sleep)
        self._client = client
        self._project_ids = project_ids
        self._cursor_path = cursor_path
        self._on_library_change = on_library_change

    async def poll_once(self) -> None:
        cursors = self._load_cursors()
        updated = dict(cursors)
        triggered = False
        for project_id in self._project_ids():
            key = str(project_id)
            cursor = cursors.get(key)
            if cursor is None:
                latest = await self._client.list_events(project_id=project_id, limit=1)
                updated[key] = _advance(None, latest)
                continue
            since, seen = cursor
            events = await self._client.list_events(
                project_id=project_id, since=since, limit=EVENTS_PAGE_LIMIT
            )
            fresh = [event for event in events if event.event_id not in seen]
            if not fresh:
                continue
            triggered = triggered or any(
                event.event_type in LIBRARY_TRIGGER_TYPES for event in fresh
            )
            updated[key] = _advance(cursor, events)
        if triggered:
            await asyncio.to_thread(self._on_library_change)
        if updated != cursors:
            self._save_cursors(updated)

    def _load_cursors(self) -> dict[str, tuple[datetime, frozenset[UUID]]]:
        try:
            raw = json.loads(self._cursor_path.read_text(encoding="utf-8"))
            return {
                key: (
                    datetime.fromisoformat(value["since"]),
                    frozenset(UUID(item) for item in value["seen"]),
                )
                for key, value in raw.items()
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {}

    def _save_cursors(self, cursors: dict[str, tuple[datetime, frozenset[UUID]]]) -> None:
        payload = {
            key: {"since": since.isoformat(), "seen": sorted(str(item) for item in seen)}
            for key, (since, seen) in cursors.items()
        }
        self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._cursor_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self._cursor_path)


def _advance(
    cursor: tuple[datetime, frozenset[UUID]] | None, events: Sequence[EventEnvelope]
) -> tuple[datetime, frozenset[UUID]]:
    if not events:
        return cursor if cursor is not None else (_EPOCH, frozenset())
    newest = max(event.server_timestamp for event in events)
    return newest, frozenset(event.event_id for event in events if event.server_timestamp == newest)
