from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from studio_contracts.events import EventEnvelope

_QUEUE_MAXSIZE = 256

_CLOSED = object()

KEEPALIVE_SECONDS = 10.0
"""Idle interval after which `receive` returns `KEEPALIVE` (DEC-0100 §9)."""


class _Keepalive:
    pass


KEEPALIVE = _Keepalive()


@dataclass(frozen=True)
class StreamEvent:
    seq: int
    project_id: UUID
    envelope: EventEnvelope


@dataclass(frozen=True)
class AccessRevoked:
    """Internal, never persisted signal (DEC-0100 §9): `user_id` lost its
    membership of `project_id`; every stream of that pair closes."""

    user_id: UUID
    project_id: UUID


@dataclass(frozen=True)
class UserRevalidation:
    """Internal, never persisted signal (DEC-0110, A3): the state or sessions
    of `user_id` changed; each of its streams revalidates its principal now
    instead of waiting for the periodic check."""

    user_id: UUID


StreamSignal = StreamEvent | AccessRevoked | UserRevalidation


_subscribers: set[asyncio.Queue[object]] = set()


def subscribe() -> asyncio.Queue[object]:
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[object]) -> None:
    _subscribers.discard(queue)


def publish(event: StreamSignal) -> None:
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


def revoke_access(user_id: UUID, project_id: UUID) -> None:
    """Called when a membership is removed, after its commit."""
    publish(AccessRevoked(user_id=user_id, project_id=project_id))


def revalidate_user(user_id: UUID) -> None:
    """Called after a User is disabled or its sessions revoked, after the
    commit."""
    publish(UserRevalidation(user_id=user_id))


async def receive(
    queue: asyncio.Queue[object], timeout: float | None = None
) -> StreamSignal | _Keepalive | None:
    """Returns the next item, `KEEPALIVE` when nothing arrived within
    `timeout` seconds, or `None` once this subscriber has been disconnected
    for falling behind (see `publish`)."""
    try:
        item = await asyncio.wait_for(queue.get(), timeout)
    except TimeoutError:
        return KEEPALIVE
    if item is _CLOSED:
        return None
    assert isinstance(item, StreamEvent | AccessRevoked | UserRevalidation)
    return item
