from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from studio_contracts.events import EventCreate, EventType

from studio_client.outbox import OutboxStore, transaction
from studio_client.watchers.base import PollingWatcher, SleepFn

ProcessProbe = Callable[[], Awaitable[bool]]


def default_process_probe(process_pattern: str) -> ProcessProbe:
    """No process-listing dependency is part of `packages/studio-client`'s
    allowed dependency set (DEC-0024: studio-contracts/httpx/pydantic-
    settings/keyring only), so this shells out to the OS's own process
    listing tool instead of adding `psutil`."""
    pattern = process_pattern.lower()

    async def _probe() -> bool:
        return await asyncio.to_thread(_probe_sync, pattern)

    return _probe


def _probe_sync(pattern: str) -> bool:
    names = _list_process_names()
    return any(pattern in name.lower() for name in names)


def _list_process_names() -> list[str]:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=True
        )
        return [line.split(",")[0].strip('"') for line in result.stdout.splitlines() if line]
    result = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, check=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class GodotWatcher(PollingWatcher):
    """Detects the Godot editor/runtime starting and stopping on this
    machine and enqueues `godot.started` / `godot.stopped` events (sous-
    etape 6.6, docs/ROADMAP_STEP6_BREAKDOWN.md). The very first poll only
    establishes a baseline (never emits `godot.started` for a process that
    was already running before the watcher started) — only genuine
    transitions observed afterwards are reported."""

    def __init__(
        self,
        *,
        project_id: UUID,
        machine_id: UUID,
        outbox: OutboxStore,
        process_pattern: str = "godot",
        interval_seconds: float = 10.0,
        sleep: SleepFn | None = None,
        probe: ProcessProbe | None = None,
        event_id_factory: Callable[[], UUID] = uuid4,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds, sleep=sleep)
        self._project_id = project_id
        self._machine_id = machine_id
        self._outbox = outbox
        self._probe = probe or default_process_probe(process_pattern)
        self._event_id_factory = event_id_factory
        self._now = now or (lambda: datetime.now(UTC))
        self._sync_key = f"godot_watcher:{process_pattern}"

    async def poll_once(self) -> None:
        running = await self._probe()
        previous = self._outbox.get_sync_state(self._sync_key)
        if previous is None:
            self._save_state(running)
            return

        previously_running = bool(previous.get("running"))
        if running == previously_running:
            return

        event_type = EventType.GODOT_STARTED if running else EventType.GODOT_STOPPED
        event = EventCreate(
            event_id=self._event_id_factory(),
            event_type=event_type,
            project_id=self._project_id,
            machine_id=self._machine_id,
            actor_type="system",
            actor_id=self._machine_id,
            client_timestamp=self._now(),
            payload={},
        )
        with transaction(self._outbox.connection):
            self._outbox.enqueue_event(event)
            self._outbox.set_sync_state(self._sync_key, {"running": running})

    def _save_state(self, running: bool) -> None:
        with transaction(self._outbox.connection):
            self._outbox.set_sync_state(self._sync_key, {"running": running})
