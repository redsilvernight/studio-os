"""Etape 9.2 local recording pipeline: markers, marketing candidates and
event emission. Every test is offline and synthetic — a fake sink or an
`httpx.MockTransport`, and a real SQLite outbox under `tmp_path` for the
cross-invocation recording state. No capture, no vault, no Postgres/MinIO."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.outbox import OutboxStore, connect
from studio_client.recording import (
    NullRecordingStore,
    OutboxRecordingStore,
    Recording,
    RecordingError,
    RecordingProvider,
)
from studio_client.tokens import MemoryTokenStore
from studio_contracts.events import EventCreate, EventType

NOW = datetime(2026, 9, 15, 20, 0, 0, tzinfo=UTC)
MACHINE = UUID("11111111-1111-1111-1111-111111111111")
PROJECT = UUID("22222222-2222-2222-2222-222222222222")
TASK = UUID("33333333-3333-3333-3333-333333333333")
SESSION = UUID("44444444-4444-4444-4444-444444444444")


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class RecordingSink:
    """Minimal `EventSink`: keeps every event instead of posting it."""

    def __init__(self) -> None:
        self.events: list[EventCreate] = []

    async def post_event(self, event: EventCreate) -> object:
        self.events.append(event)
        return event


def _provider(
    sink: RecordingSink,
    *,
    store: OutboxRecordingStore | NullRecordingStore | None = None,
    clock: Clock | None = None,
) -> RecordingProvider:
    return RecordingProvider(
        sink,
        actor_id=MACHINE,
        machine_id=MACHINE,
        store=store,
        now=clock or Clock(),
    )


def _outbox(tmp_path: Path) -> OutboxRecordingStore:
    return OutboxRecordingStore(OutboxStore(connect(tmp_path / "outbox.sqlite3")))


async def test_start_recording_emits_started_and_persists(tmp_path: Path) -> None:
    sink = RecordingSink()
    store = _outbox(tmp_path)
    provider = _provider(sink, store=store)

    recording = await provider.start_recording(PROJECT, task_id=TASK, session_id=SESSION)

    (event,) = sink.events
    assert event.event_type is EventType.RECORDING_STARTED
    assert event.project_id == PROJECT
    assert event.task_id == TASK
    assert event.machine_id == MACHINE
    assert event.actor_type == "user"
    assert event.payload == {
        "recording_id": str(recording.recording_id),
        "started_at": NOW.isoformat(),
        "session_id": str(SESSION),
    }
    assert store.load() == recording


async def test_start_recording_twice_is_refused(tmp_path: Path) -> None:
    provider = _provider(RecordingSink(), store=_outbox(tmp_path))
    await provider.start_recording(PROJECT)
    try:
        await provider.start_recording(PROJECT)
    except RecordingError as exc:
        assert exc.reason == RecordingError.RECORDING_ALREADY_ACTIVE
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("second start_recording should have raised")


async def test_finish_recording_emits_duration_and_clears_state(tmp_path: Path) -> None:
    sink = RecordingSink()
    store = _outbox(tmp_path)
    clock = Clock()
    provider = _provider(sink, store=store, clock=clock)

    recording = await provider.start_recording(PROJECT, task_id=TASK)
    clock.advance(75)
    finished = await provider.finish_recording()

    assert sink.events[-1].event_type is EventType.RECORDING_FINISHED
    assert sink.events[-1].payload == {
        "recording_id": str(recording.recording_id),
        "started_at": NOW.isoformat(),
        "finished_at": (NOW + timedelta(seconds=75)).isoformat(),
        "duration_seconds": 75.0,
    }
    assert finished.finished_at == NOW + timedelta(seconds=75)
    assert store.load() is None


async def test_finish_recording_without_active_is_refused(tmp_path: Path) -> None:
    provider = _provider(RecordingSink(), store=_outbox(tmp_path))
    try:
        await provider.finish_recording()
    except RecordingError as exc:
        assert exc.reason == RecordingError.NO_ACTIVE_RECORDING
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("finish_recording should have raised")


async def test_mark_without_project_or_recording_is_refused() -> None:
    provider = _provider(RecordingSink())
    try:
        await provider.mark("orphan")
    except RecordingError as exc:
        assert exc.reason == RecordingError.NO_ACTIVE_RECORDING
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("mark should have raised")


async def test_mark_with_explicit_project_emits_compact_payload() -> None:
    sink = RecordingSink()
    provider = _provider(sink)

    marker = await provider.mark("first successful gameplay", project_id=PROJECT)

    (event,) = sink.events
    assert event.event_type is EventType.RECORDING_MARKER_CREATED
    assert event.project_id == PROJECT
    assert event.task_id is None
    assert event.payload == {
        "marker_id": str(marker.marker_id),
        "label": "first successful gameplay",
        "recorded_at": NOW.isoformat(),
    }
    assert marker.offset_seconds is None
    assert marker.recording_id is None


async def test_mark_uses_active_recording_association(tmp_path: Path) -> None:
    sink = RecordingSink()
    clock = Clock()
    provider = _provider(sink, store=_outbox(tmp_path), clock=clock)
    recording = await provider.start_recording(PROJECT, task_id=TASK, session_id=SESSION)

    clock.advance(42)
    marker = await provider.mark("boss down")

    assert marker.project_id == PROJECT
    assert marker.task_id == TASK
    assert marker.session_id == SESSION
    assert marker.recording_id == recording.recording_id
    assert marker.offset_seconds == 42.0
    assert sink.events[-1].payload == {
        "marker_id": str(marker.marker_id),
        "label": "boss down",
        "recorded_at": (NOW + timedelta(seconds=42)).isoformat(),
        "offset_seconds": 42.0,
        "session_id": str(SESSION),
        "recording_id": str(recording.recording_id),
    }


async def test_mark_explicit_arguments_win_over_active_recording(tmp_path: Path) -> None:
    provider = _provider(RecordingSink(), store=_outbox(tmp_path))
    await provider.start_recording(PROJECT, task_id=TASK)

    other_task = uuid4()
    marker = await provider.mark("override", task_id=other_task, project_id=PROJECT)

    assert marker.task_id == other_task


async def test_mark_relative_at_is_measured_from_recording_start(tmp_path: Path) -> None:
    sink = RecordingSink()
    clock = Clock()
    provider = _provider(sink, store=_outbox(tmp_path), clock=clock)
    await provider.start_recording(PROJECT)
    clock.advance(10)

    marker = await provider.mark("intro", at="+90")

    assert marker.timestamp == NOW + timedelta(seconds=90)
    assert marker.offset_seconds == 90.0


async def test_mark_relative_at_without_recording_is_measured_from_now() -> None:
    provider = _provider(RecordingSink())
    marker = await provider.mark("late", project_id=PROJECT, at="-30s")
    assert marker.timestamp == NOW - timedelta(seconds=30)


async def test_mark_absolute_iso_timestamp() -> None:
    provider = _provider(RecordingSink())
    marker = await provider.mark("fixed", project_id=PROJECT, at="2026-09-15T20:05:00Z")
    assert marker.timestamp == NOW + timedelta(minutes=5)


async def test_mark_rejects_blank_label() -> None:
    provider = _provider(RecordingSink())
    try:
        await provider.mark("   ", project_id=PROJECT)
    except RecordingError as exc:
        assert exc.reason == RecordingError.INVALID_LABEL
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("blank label should have raised")


async def test_mark_rejects_unparsable_at() -> None:
    provider = _provider(RecordingSink())
    try:
        await provider.mark("bad", project_id=PROJECT, at="not-a-time")
    except RecordingError as exc:
        assert exc.reason == RecordingError.INVALID_TIMESTAMP
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("bad --at should have raised")


async def test_create_marketing_candidate_around_marker() -> None:
    sink = RecordingSink()
    provider = _provider(sink)
    marker = await provider.mark("clutch", project_id=PROJECT, at="+90")

    candidate = await provider.create_marketing_candidate(
        marker, pre_roll_seconds=5, post_roll_seconds=25
    )

    assert candidate.marker_id == marker.marker_id
    assert candidate.start == marker.timestamp - timedelta(seconds=5)
    assert candidate.end == marker.timestamp + timedelta(seconds=25)
    assert candidate.duration_seconds == 30.0
    assert sink.events[-1].event_type is EventType.MARKETING_CANDIDATE_CREATED
    assert sink.events[-1].payload == {
        "candidate_id": str(candidate.candidate_id),
        "marker_id": str(marker.marker_id),
        "label": "clutch",
        "start": (NOW + timedelta(seconds=85)).isoformat(),
        "end": (NOW + timedelta(seconds=115)).isoformat(),
        "duration_seconds": 30.0,
    }


async def test_create_marketing_candidate_rejects_empty_range() -> None:
    provider = _provider(RecordingSink())
    marker = await provider.mark("zero", project_id=PROJECT)
    try:
        await provider.create_marketing_candidate(marker, pre_roll_seconds=0, post_roll_seconds=0)
    except RecordingError as exc:
        assert exc.reason == RecordingError.INVALID_RANGE
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("empty range should have raised")


async def test_each_emission_gets_its_own_event_id() -> None:
    sink = RecordingSink()
    provider = _provider(sink)
    await provider.mark("one", project_id=PROJECT)
    await provider.mark("two", project_id=PROJECT)
    assert sink.events[0].event_id != sink.events[1].event_id


def _envelope_response(request: httpx.Request) -> httpx.Response:
    body: dict[str, Any] = json.loads(request.content)
    body["server_timestamp"] = NOW.isoformat()
    return httpx.Response(201, json=body)


async def test_events_are_posted_through_studio_api_client() -> None:
    """The provider's sink is a real `StudioApiClient`; only the transport is
    mocked, so the emitted payload is asserted on the wire (`POST /events`)."""
    seen: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return _envelope_response(request)

    token_store = MemoryTokenStore()
    token_store.set_token("http://test", "test-token")
    config = ClientConfig(api_base_url="http://test", backoff_initial=0.001, backoff_max=0.002)
    async with StudioApiClient(
        config, token_store, transport=httpx.MockTransport(handler)
    ) as client:
        provider = RecordingProvider(client, actor_id=MACHINE, machine_id=MACHINE, now=Clock())
        marker = await provider.mark("first successful gameplay", project_id=PROJECT)
        await provider.create_marketing_candidate(marker)

    assert [path for path, _ in seen] == ["/api/v1/events", "/api/v1/events"]
    first_body = seen[0][1]
    assert first_body["event_type"] == "recording.marker.created"
    assert first_body["project_id"] == str(PROJECT)
    assert first_body["actor_id"] == str(MACHINE)
    assert first_body["payload"] == {
        "marker_id": str(marker.marker_id),
        "label": "first successful gameplay",
        "recorded_at": NOW.isoformat(),
    }
    assert seen[1][1]["event_type"] == "marketing.candidate.created"


async def test_recording_state_round_trips_through_sqlite(tmp_path: Path) -> None:
    store = _outbox(tmp_path)
    recording = Recording(recording_id=uuid4(), project_id=PROJECT, started_at=NOW, task_id=TASK)
    store.save(recording)
    assert store.load() == recording

    store.clear()
    assert store.load() is None
