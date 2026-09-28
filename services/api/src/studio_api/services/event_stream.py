from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from uuid import UUID

from studio_contracts.events import EventEnvelope

_QUEUE_MAXSIZE = 256

NOTIFY_CHANNEL = "studio_events"
"""PostgreSQL channel carrying the `seq` of each committed event (DEC-0156)."""

_CLOSED = object()

KEEPALIVE_SECONDS = 10.0
"""Idle interval after which `receive` returns `KEEPALIVE` (DEC-0103 §9)."""


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
    """Internal, never persisted signal (DEC-0103 §9): `user_id` lost its
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

_RECENT_SEQS_MAX = 4096
"""How many published `seq` are remembered to drop the second copy of an
event: this process publishes its own events right after commit, and the
cross-process listener (DEC-0156) receives the same `seq` again."""

_recent_seqs: deque[int] = deque()
_recent_seq_set: set[int] = set()


def already_published(seq: int) -> bool:
    return seq in _recent_seq_set


def _remember(seq: int) -> None:
    _recent_seqs.append(seq)
    _recent_seq_set.add(seq)
    if len(_recent_seqs) > _RECENT_SEQS_MAX:
        _recent_seq_set.discard(_recent_seqs.popleft())


def subscribe() -> asyncio.Queue[object]:
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[object]) -> None:
    _subscribers.discard(queue)


def publish(event: StreamSignal) -> None:
    """In-process fan-out (DEC-0018); events committed by other processes
    reach it through `event_listener` (DEC-0156). A `StreamEvent` whose
    `seq` was already published is dropped. A subscriber too slow to drain
    its queue is disconnected rather than blocking every other subscriber or
    growing memory unbounded; it must reconnect and resume from its last
    `seq`."""
    if isinstance(event, StreamEvent):
        if already_published(event.seq):
            return
        _remember(event.seq)
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
