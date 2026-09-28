from __future__ import annotations

import uuid
from datetime import UTC, datetime

from studio_api.services import event_stream
from studio_api.services.event_listener import listener_dsn
from studio_contracts.events import EventEnvelope


def _stream_event(seq: int) -> event_stream.StreamEvent:
    project_id = uuid.uuid4()
    envelope = EventEnvelope.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "task.created",
            "project_id": str(project_id),
            "actor_type": "user",
            "actor_id": str(uuid.uuid4()),
            "client_timestamp": datetime.now(UTC).isoformat(),
            "server_timestamp": datetime.now(UTC).isoformat(),
            "payload": {},
        }
    )
    return event_stream.StreamEvent(seq=seq, project_id=project_id, envelope=envelope)


def test_publishing_the_same_seq_twice_delivers_it_once() -> None:
    """The API publishes its own events after commit and receives their
    NOTIFY too (DEC-0156): the second copy must not reach subscribers."""
    seq = 10**15 + uuid.uuid4().int % 10**9
    queue = event_stream.subscribe()
    try:
        event_stream.publish(_stream_event(seq))
        event_stream.publish(_stream_event(seq))
        assert queue.qsize() == 1
        assert event_stream.already_published(seq)
    finally:
        event_stream.unsubscribe(queue)


def test_listener_dsn_drops_the_sqlalchemy_driver() -> None:
    assert (
        listener_dsn("postgresql+asyncpg://studio:s3cret@db:5432/studio")
        == "postgresql://studio:s3cret@db:5432/studio"
    )
