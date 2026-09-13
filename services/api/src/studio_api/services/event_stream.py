from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from studio_contracts.events import EventEnvelope

_QUEUE_MAXSIZE = 256

_CLOSED = object()


@dataclass(frozen=True)
class StreamEvent:
    seq: int
    project_id: UUID
    envelope: EventEnvelope


_subscribers: set[asyncio.Queue[object]] = set()


def subscribe() -> asyncio.Queue[object]:
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[object]) -> None:
    _subscribers.discard(queue)


def publish(event: StreamEvent) -> None:
    """In-process fan-out only (DEC-0018) — a single `api` replica, per
    docker/docker-compose.yml. A subscriber too slow to drain its queue is
    disconnected rather than blocking every other subscriber or growing
    memory unbounded; it must reconnect and resume from its last `seq`."""
    for queue in list(_subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            _subscribers.discard(queue)
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(_CLOSED)


async def receive(queue: asyncio.Queue[object]) -> StreamEvent | None:
    """Returns the next event, or `None` once this subscriber has been
    disconnected for falling behind (see `publish`)."""
    item = await queue.get()
    if item is _CLOSED:
        return None
    assert isinstance(item, StreamEvent)
    return item
