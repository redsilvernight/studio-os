from __future__ import annotations

import asyncio
import contextlib
import logging

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from studio_api.db.models.event import EventModel
from studio_api.db.session import get_session_factory
from studio_api.services import event_stream
from studio_api.services.events import publish_event

logger = logging.getLogger(__name__)

_CATCH_UP_BATCH = 500
_HEALTH_CHECK_TIMEOUT_SECONDS = 5.0


def listener_dsn(database_url: str) -> str:
    """The SQLAlchemy URL (`postgresql+asyncpg://…`) as a plain libpq DSN."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


class EventListener:
    """Cross-process realtime fan-out (DEC-0156): holds a dedicated LISTEN
    connection on `event_stream.NOTIFY_CHANNEL`, reads each notified `seq`
    back from the database and publishes it into this process's hub. Events
    this process already published itself are skipped by `seq`.

    On reconnection it first catches up on every `seq` above the last one
    seen, then resumes listening; the per-subscriber `seq` catch-up of the
    SSE endpoint (DEC-0018) stays the final safety net."""

    def __init__(
        self,
        database_url: str,
        *,
        reconnect_delay_seconds: float = 1.0,
        health_check_seconds: float = 30.0,
    ) -> None:
        self._dsn = listener_dsn(database_url)
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self._health_check_seconds = health_check_seconds
        self._last_seq: int | None = None
        self.server_pid: int | None = None
        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()

    async def run(self) -> None:
        """Listen until cancelled, reconnecting after any failure."""
        while True:
            try:
                await self._listen_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("event listener disconnected, reconnecting", exc_info=True)
            finally:
                self.server_pid = None
                self.connected.clear()
                self.disconnected.set()
            await asyncio.sleep(self.reconnect_delay_seconds)

    async def _listen_once(self) -> None:
        notified: asyncio.Queue[int] = asyncio.Queue()
        lost = asyncio.Event()

        def on_notify(_conn: object, _pid: int, _channel: str, payload: str) -> None:
            try:
                notified.put_nowait(int(payload))
            except ValueError:
                logger.warning("ignoring malformed event notification %r", payload)

        conn = await asyncpg.connect(self._dsn)
        try:
            conn.add_termination_listener(lambda _conn: lost.set())
            # LISTEN before catching up: an event committed in between is
            # both read by the catch-up and notified, never missed.
            await conn.add_listener(event_stream.NOTIFY_CHANNEL, on_notify)
            await self._catch_up()
            self.server_pid = conn.get_server_pid()
            self.disconnected.clear()
            self.connected.set()
            while True:
                seqs = await self._next_seqs(conn, notified, lost)
                await self._publish(seqs)
        finally:
            with contextlib.suppress(Exception):
                await conn.close(timeout=_HEALTH_CHECK_TIMEOUT_SECONDS)

    async def _next_seqs(
        self, conn: asyncpg.Connection, notified: asyncio.Queue[int], lost: asyncio.Event
    ) -> list[int]:
        """Waits for at least one notification and drains what else is
        queued. With no notification for `health_check_seconds`, probes the
        connection so a silently dead socket is noticed."""
        while True:
            get = asyncio.ensure_future(notified.get())
            lost_wait = asyncio.ensure_future(lost.wait())
            try:
                done, _ = await asyncio.wait(
                    {get, lost_wait},
                    timeout=self._health_check_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                # Also on cancellation (API shutdown): no orphaned waiter.
                for task in (get, lost_wait):
                    task.cancel()
                await asyncio.gather(get, lost_wait, return_exceptions=True)
            if get in done:
                seqs = [get.result()]
                while not notified.empty():
                    seqs.append(notified.get_nowait())
                return seqs
            if lost_wait in done:
                raise ConnectionError("event listener connection lost")
            await asyncio.wait_for(conn.execute("SELECT 1"), _HEALTH_CHECK_TIMEOUT_SECONDS)

    async def _catch_up(self) -> None:
        async with get_session_factory()() as session:
            if self._last_seq is None:
                # First connection: only what happens from now on is live.
                self._last_seq = (await session.scalar(select(func.max(EventModel.seq)))) or 0
                return
            while True:
                rows = (
                    await session.scalars(
                        select(EventModel)
                        .where(EventModel.seq > self._last_seq)
                        .order_by(EventModel.seq.asc())
                        .limit(_CATCH_UP_BATCH)
                    )
                ).all()
                for row in rows:
                    publish_event(row)
                    self._last_seq = row.seq
                if len(rows) < _CATCH_UP_BATCH:
                    return

    async def _publish(self, seqs: list[int]) -> None:
        self._last_seq = max([*seqs, self._last_seq or 0])
        wanted = sorted({seq for seq in seqs if not event_stream.already_published(seq)})
        if not wanted:
            return
        async with get_session_factory()() as session:
            rows = (
                await session.scalars(
                    select(EventModel).where(EventModel.seq.in_(wanted)).order_by(EventModel.seq)
                )
            ).all()
        for row in rows:
            publish_event(row)
