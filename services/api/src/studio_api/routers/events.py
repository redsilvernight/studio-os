from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from studio_contracts.events import EventCreate, EventEnvelope

from studio_api.deps import CurrentMachine, DbSession
from studio_api.services import event_stream
from studio_api.services import events as events_service

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def _parse_last_event_id(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Last-Event-ID must be an integer seq cursor"
        ) from exc


def _format_sse(event: event_stream.StreamEvent) -> bytes:
    data = event.envelope.model_dump_json()
    return f"id: {event.seq}\ndata: {data}\n\n".encode()


@router.post("", response_model=EventEnvelope)
async def post_event(
    event_in: EventCreate, machine: CurrentMachine, session: DbSession
) -> EventEnvelope:
    event = await events_service.create_event(session, event_in)
    return EventEnvelope.model_validate(event)


@router.get("", response_model=list[EventEnvelope])
async def get_events(
    session: DbSession,
    machine: CurrentMachine,
    project: UUID | None = Query(default=None),
    task: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[EventEnvelope]:
    events = await events_service.list_events(
        session,
        project_id=str(project) if project else None,
        task_id=str(task) if task else None,
        since=since,
        limit=limit,
    )
    return [EventEnvelope.model_validate(e) for e in events]


@router.get("/stream")
async def stream_events(
    session: DbSession,
    machine: CurrentMachine,
    project: UUID = Query(...),
    since_seq: int | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Realtime push (DEC-0018): Server-Sent Events, resumable via `seq`.
    Cursor precedence: `Last-Event-ID` (standard SSE auto-reconnect) over
    `since_seq` (explicit resume for a non-browser client); with neither,
    only events created from this point on are delivered — `GET /events` is
    the explicit backlog/catch-up channel."""
    parsed_last_event_id = _parse_last_event_id(last_event_id)
    cursor = parsed_last_event_id if parsed_last_event_id is not None else since_seq

    async def generate() -> AsyncIterator[bytes]:
        queue = event_stream.subscribe()
        try:
            last_seq = cursor
            if cursor is not None:
                backlog = await events_service.list_events_after(
                    session, project_id=str(project), after_seq=cursor
                )
                for row in backlog:
                    last_seq = row.seq
                    yield _format_sse(
                        event_stream.StreamEvent(
                            seq=row.seq,
                            project_id=row.project_id,
                            envelope=EventEnvelope.model_validate(row),
                        )
                    )
            # Done with the DB for this connection's lifetime — release the
            # pooled connection now rather than pinning it for as long as the
            # client stays subscribed (this loop has no further DB access).
            await session.close()
            while True:
                event = await event_stream.receive(queue)
                if event is None:
                    return
                if event.project_id != project:
                    continue
                if last_seq is not None and event.seq <= last_seq:
                    continue
                last_seq = event.seq
                yield _format_sse(event)
        finally:
            event_stream.unsubscribe(queue)

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
