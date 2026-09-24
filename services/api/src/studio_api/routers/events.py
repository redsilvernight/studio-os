from __future__ import annotations

import time
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from studio_contracts.events import EventCreate, EventEnvelope

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_409_EVENT_IDENTITY,
)
from studio_api.services import event_stream
from studio_api.services import events as events_service

REVALIDATE_SECONDS = 20.0
"""Membership revalidation period of an open stream. Checked on every item,
at worst one keep-alive late: bounded by 20 + 10 s (DEC-0100 §9: ≤ 30 s)."""

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


@router.post(
    "",
    response_model=EventEnvelope,
    description=(
        "Publish an event to a project. Requires a writer role. "
        "`event_id` is a caller-generated UUID and the replay key: "
        "resending the same `event_id` returns the stored event, never a "
        "duplicate (this endpoint does not use `Idempotency-Key`). "
        "Identity is validated against the authenticated machine: omit "
        "`machine_id` (it is derived automatically) or send the machine's "
        "own id; `actor_type=user` requires the machine owner's user id "
        "as `actor_id`; `actor_type=agent` requires an agent attached to "
        "the caller's own machine (register one with `POST /agents` "
        "first); `actor_type=system` requires the machine's own id. "
        "Working without an agent identity is fully supported — use "
        "`user` or `system`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_EVENT_IDENTITY},
)
async def post_event(
    event_in: EventCreate, principal: CurrentPrincipal, session: DbSession
) -> EventEnvelope:
    event_in = await events_service.resolve_event_identity(session, principal, event_in)
    event = await events_service.create_event(session, event_in)
    return EventEnvelope.model_validate(event)


@router.get(
    "",
    response_model=list[EventEnvelope],
    description=(
        "Read recent events, optionally filtered by project, task and "
        "`since` timestamp, restricted to the caller's accessible "
        "projects (a `project` the caller cannot access answers `403 "
        "forbidden`). This is "
        "the polling and catch-up channel: after a disconnect, poll with "
        "`since` to retrieve missed history, then optionally resume live "
        "delivery on `GET /events/stream`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def get_events(
    session: DbSession,
    principal: CurrentPrincipal,
    project: UUID | None = Query(default=None),
    task: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[EventEnvelope]:
    events = await events_service.list_events(
        session,
        principal,
        project_id=project,
        task_id=task,
        since=since,
        limit=limit,
    )
    return [EventEnvelope.model_validate(e) for e in events]


@router.get(
    "/stream",
    description=(
        "Live event push for one project as Server-Sent Events "
        "(`text/event-stream`; each SSE `id:` is the event's `seq`, a "
        "strictly increasing integer). `project` is required — there is "
        "no global cross-project stream. Resuming after a cutover loses "
        "nothing: pass the last seen `seq` as `since_seq`, or rely on the "
        "standard SSE `Last-Event-ID` auto-reconnect header "
        "(`Last-Event-ID` wins when both are present). With no cursor, "
        "only events created from connection time are delivered — use "
        "`GET /events?since=` first to backfill history, then open the "
        "stream for live updates. Same authentication as the rest of the API. "
        "An inaccessible `project` answers `403 forbidden` before the stream "
        "opens; an idle stream receives an SSE comment keep-alive, and the "
        "stream closes once the caller loses access to the project."
    ),
    responses={
        200: {
            "description": (
                "A `text/event-stream` response. Each frame carries one "
                "event envelope as JSON in `data:` with its `seq` in "
                "`id:`. The connection stays open; reconnect with the "
                "last `seq` to resume without loss or duplicates."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        'id: 42\ndata: {"event_id": "...", "event_type": "task.updated", ...}\n\n'
                    ),
                }
            },
        },
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
    },
)
async def stream_events(
    session: DbSession,
    principal: CurrentPrincipal,
    project: UUID = Query(
        ..., description="Project to subscribe to (UUID). No global stream exists."
    ),
    since_seq: int | None = Query(
        default=None,
        description=(
            "Explicit resume cursor: last `seq` already seen. Ignored when "
            "`Last-Event-ID` is present."
        ),
    ),
    last_event_id: str | None = Header(
        default=None,
        alias="Last-Event-ID",
        description=(
            "Standard SSE auto-reconnect cursor (integer `seq`). Takes precedence over `since_seq`."
        ),
    ),
) -> StreamingResponse:
    parsed_last_event_id = _parse_last_event_id(last_event_id)
    cursor = parsed_last_event_id if parsed_last_event_id is not None else since_seq
    # Before the response starts: an inaccessible project is a plain 403,
    # never an opened-then-closed stream (DEC-0100 §9).
    events_service.authorize_stream(principal, project)
    machine_id = principal.machine.id
    user_id = principal.user.id

    async def generate() -> AsyncIterator[bytes]:
        queue = event_stream.subscribe()
        try:
            last_seq = cursor
            if cursor is not None:
                backlog = await events_service.list_events_after(
                    session, principal, project_id=project, after_seq=cursor
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
            # client stays subscribed (revalidation uses its own short session).
            await session.close()
            checked_at = time.monotonic()
            while True:
                event = await event_stream.receive(queue, event_stream.KEEPALIVE_SECONDS)
                if event is None:
                    return
                if isinstance(event, event_stream.AccessRevoked):
                    if event.user_id == user_id and event.project_id == project:
                        return
                    continue
                if time.monotonic() - checked_at >= REVALIDATE_SECONDS:
                    if not await events_service.stream_access_still_valid(machine_id, project):
                        return
                    checked_at = time.monotonic()
                if not isinstance(event, event_stream.StreamEvent):  # KEEPALIVE
                    yield b": keep-alive\n\n"
                    continue
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
