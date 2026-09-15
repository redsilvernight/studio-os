from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from studio_contracts.events import ActorType, EventCreate, EventType

from studio_client.outbox.store import OutboxStore, transaction
from studio_client.recording.errors import RecordingError
from studio_client.recording.marker import (
    Marker,
    normalize_label,
    parse_timestamp,
    to_iso,
)
from studio_client.recording.marketing import (
    DEFAULT_POST_ROLL_SECONDS,
    DEFAULT_PRE_ROLL_SECONDS,
    MarketingCandidate,
)

RECORDING_STATE_KEY = "recording:active"


class EventSink(Protocol):
    """The one write boundary of this package. `StudioApiClient` satisfies it
    structurally through its existing `post_event` (DEC-0024) — this protocol
    only names the dependency so tests can substitute a plain collector and
    so a future outbox-backed sink slots in without touching the provider."""

    async def post_event(self, event: EventCreate) -> object: ...


@dataclass(frozen=True)
class Recording:
    """One recording of a working session. `recording_id` is generated
    client-side and stable; a finished recording carries `finished_at`."""

    recording_id: UUID
    project_id: UUID
    started_at: datetime
    task_id: UUID | None = None
    session_id: UUID | None = None
    finished_at: datetime | None = None

    def state(self) -> dict[str, object]:
        state: dict[str, object] = {
            "recording_id": str(self.recording_id),
            "project_id": str(self.project_id),
            "started_at": to_iso(self.started_at),
        }
        if self.task_id is not None:
            state["task_id"] = str(self.task_id)
        if self.session_id is not None:
            state["session_id"] = str(self.session_id)
        return state

    @classmethod
    def from_state(cls, state: dict[str, object]) -> Recording:
        started_at = state.get("started_at")
        if not isinstance(started_at, str):
            raise RecordingError(
                RecordingError.NO_ACTIVE_RECORDING, "stored recording has no started_at"
            )
        task_id = state.get("task_id")
        session_id = state.get("session_id")
        return cls(
            recording_id=UUID(str(state["recording_id"])),
            project_id=UUID(str(state["project_id"])),
            started_at=datetime.fromisoformat(started_at),
            task_id=UUID(str(task_id)) if task_id else None,
            session_id=UUID(str(session_id)) if session_id else None,
        )


class ActiveRecordingStore(Protocol):
    """Where the current recording survives across processes. `studio mark`
    runs as its own CLI invocation, so the recording started by the daemon
    must be readable from local state, not only from memory."""

    def load(self) -> Recording | None: ...
    def save(self, recording: Recording) -> None: ...
    def clear(self) -> None: ...


class NullRecordingStore:
    """In-memory-less default: no recording is ever active. Used when no
    local outbox exists yet and by tests that only exercise the
    explicit-`--project` path."""

    def load(self) -> Recording | None:
        return None

    def save(self, recording: Recording) -> None:
        del recording

    def clear(self) -> None:
        return


class OutboxRecordingStore:
    """Persists the active recording in the outbox's local `sync_state`
    (SQLite). Purely client-side: it never reaches the server and is not the
    offline queue — it only answers "which recording is live on this
    machine?" for a later `studio mark`."""

    def __init__(self, store: OutboxStore) -> None:
        self._store = store

    def load(self) -> Recording | None:
        state = self._store.get_sync_state(RECORDING_STATE_KEY)
        return Recording.from_state(state) if state else None

    def save(self, recording: Recording) -> None:
        with transaction(self._store.connection):
            self._store.set_sync_state(RECORDING_STATE_KEY, recording.state())

    def clear(self) -> None:
        with transaction(self._store.connection):
            self._store.connection.execute(
                "DELETE FROM sync_state WHERE key = ?", (RECORDING_STATE_KEY,)
            )


class RecordingProvider:
    """Local recording/marker pipeline (etape 9.2, Bloc B).

    Detects nothing by itself: start/finish are explicit (the daemon's Godot
    watcher or a human triggers them), `HUMAN/02` leaving automatic capture
    start as a future integration. Every produced marker/candidate raises a
    typed `RecordingError` rather than guessing, and emits exactly one
    compact event through `sink` — an `event_id` is generated per emission,
    which is what makes a future outbox replay idempotent.
    """

    def __init__(
        self,
        sink: EventSink,
        *,
        actor_id: UUID,
        machine_id: UUID | None = None,
        store: ActiveRecordingStore | None = None,
        actor_type: ActorType = "user",
        now: Callable[[], datetime] | None = None,
        event_id_factory: Callable[[], UUID] = uuid4,
        recording_id_factory: Callable[[], UUID] = uuid4,
        marker_id_factory: Callable[[], UUID] = uuid4,
        candidate_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._sink = sink
        self._actor_id = actor_id
        self._machine_id = machine_id
        self._store = store or NullRecordingStore()
        self._actor_type = actor_type
        self._now = now or (lambda: datetime.now(UTC))
        self._event_id_factory = event_id_factory
        self._recording_id_factory = recording_id_factory
        self._marker_id_factory = marker_id_factory
        self._candidate_id_factory = candidate_id_factory

    def active_recording(self) -> Recording | None:
        return self._store.load()

    async def start_recording(
        self,
        project_id: UUID,
        *,
        task_id: UUID | None = None,
        session_id: UUID | None = None,
    ) -> Recording:
        if self._store.load() is not None:
            raise RecordingError(
                RecordingError.RECORDING_ALREADY_ACTIVE,
                "a recording is already active on this machine",
            )
        started_at = self._now()
        recording = Recording(
            recording_id=self._recording_id_factory(),
            project_id=project_id,
            started_at=started_at,
            task_id=task_id,
            session_id=session_id,
        )
        await self._emit(
            EventType.RECORDING_STARTED,
            project_id=project_id,
            task_id=task_id,
            payload={
                "recording_id": str(recording.recording_id),
                "started_at": to_iso(started_at),
                **({"session_id": str(session_id)} if session_id is not None else {}),
            },
        )
        self._store.save(recording)
        return recording

    async def finish_recording(self) -> Recording:
        recording = self._store.load()
        if recording is None:
            raise RecordingError(
                RecordingError.NO_ACTIVE_RECORDING, "no recording is active on this machine"
            )
        finished_at = self._now()
        duration = max((finished_at - recording.started_at).total_seconds(), 0.0)
        await self._emit(
            EventType.RECORDING_FINISHED,
            project_id=recording.project_id,
            task_id=recording.task_id,
            payload={
                "recording_id": str(recording.recording_id),
                "started_at": to_iso(recording.started_at),
                "finished_at": to_iso(finished_at),
                "duration_seconds": round(duration, 3),
            },
        )
        self._store.clear()
        return replace(recording, finished_at=finished_at)

    async def mark(
        self,
        label: str,
        *,
        project_id: UUID | None = None,
        task_id: UUID | None = None,
        session_id: UUID | None = None,
        at: str | None = None,
    ) -> Marker:
        """Create a marker and emit `recording.marker.created`.

        Association precedence: an explicit argument always wins, otherwise
        the active recording supplies project/task/session. With no explicit
        `--project` and no active recording there is nowhere to attach the
        marker, so it raises `NO_ACTIVE_RECORDING` instead of inventing one.
        """
        recording = self._store.load()
        resolved_project = project_id or (recording.project_id if recording else None)
        if resolved_project is None:
            raise RecordingError(
                RecordingError.NO_ACTIVE_RECORDING,
                "no --project given and no active recording to attach the marker to",
            )
        resolved_task = (
            task_id if task_id is not None else (recording.task_id if recording else None)
        )
        resolved_session = (
            session_id if session_id is not None else (recording.session_id if recording else None)
        )
        now = self._now()
        timestamp = (
            now
            if at is None
            else parse_timestamp(
                at,
                now=now,
                relative_base=recording.started_at if recording else None,
            )
        )
        marker = Marker(
            marker_id=self._marker_id_factory(),
            label=normalize_label(label),
            project_id=resolved_project,
            timestamp=timestamp,
            task_id=resolved_task,
            session_id=resolved_session,
            recording_id=recording.recording_id if recording else None,
            offset_seconds=(timestamp - recording.started_at).total_seconds()
            if recording
            else None,
        )
        await self._emit(
            EventType.RECORDING_MARKER_CREATED,
            project_id=resolved_project,
            task_id=resolved_task,
            payload=marker.event_payload(),
        )
        return marker

    async def create_marketing_candidate(
        self,
        marker: Marker,
        *,
        pre_roll_seconds: float = DEFAULT_PRE_ROLL_SECONDS,
        post_roll_seconds: float = DEFAULT_POST_ROLL_SECONDS,
    ) -> MarketingCandidate:
        """Turn a marker into a proposed clip range and emit
        `marketing.candidate.created` — the `MarketingCandidate` worker step
        (`HUMAN/03`)."""
        candidate = MarketingCandidate.from_marker(
            marker,
            candidate_id=self._candidate_id_factory(),
            pre_roll_seconds=pre_roll_seconds,
            post_roll_seconds=post_roll_seconds,
        )
        await self._emit(
            EventType.MARKETING_CANDIDATE_CREATED,
            project_id=candidate.project_id,
            task_id=candidate.task_id,
            payload=candidate.event_payload(),
        )
        return candidate

    async def _emit(
        self,
        event_type: EventType,
        *,
        project_id: UUID,
        task_id: UUID | None,
        payload: dict[str, object],
    ) -> None:
        event = EventCreate(
            event_id=self._event_id_factory(),
            event_type=event_type,
            project_id=project_id,
            task_id=task_id,
            machine_id=self._machine_id,
            actor_type=self._actor_type,
            actor_id=self._actor_id,
            client_timestamp=self._now(),
            payload=payload,
        )
        await self._sink.post_event(event)
