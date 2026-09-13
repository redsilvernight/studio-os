from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from studio_contracts.events import EventCreate, EventType

from studio_client.api_client import StudioApiClient
from studio_client.errors import StudioApiError
from studio_client.outbox.models import OutboxTable, PendingRow
from studio_client.outbox.store import OutboxStore
from studio_client.retry import RetryPolicy, is_retryable

logger = logging.getLogger(__name__)

_REPLAYABLE_TABLES = (OutboxTable.EVENTS, OutboxTable.MUTATIONS)
"""`pending_markers` has no server target yet — no endpoint consumes a
`recording.marker.created`-shaped row (only the `EventType` member exists,
`rg marker services/` finds no router/tool). Replaying it here would mean
inventing a call. Rows stay queued untouched until whichever future
sub-step adds that endpoint defines what a marker replay actually sends."""


@dataclass
class ReplayOutcome:
    succeeded: int = 0
    dead_lettered: int = 0
    stopped_on_transient_error: bool = False


class OutboxReplayer:
    """Drains `pending_events` and `pending_mutations` in creation order
    (sous-etape 6.4, docs/ROADMAP_STEP6_BREAKDOWN.md). Order is preserved by
    never skipping ahead: the first row that fails with a retryable error
    stops the whole pass — its own `mark_failed` backoff paces the next
    attempt, so a later row is never sent before an earlier one that hasn't
    landed yet. A row that fails with a non-retryable business error is
    dead-lettered instead, and the pass continues past it: it is terminally
    resolved, not stuck (`.claude/rules/offline-sync.md`)."""

    def __init__(
        self, store: OutboxStore, client: StudioApiClient, retry_policy: RetryPolicy
    ) -> None:
        self._store = store
        self._client = client
        self._retry_policy = retry_policy

    async def replay_ready(self, *, limit: int = 100) -> ReplayOutcome:
        ready: list[tuple[datetime, OutboxTable, PendingRow]] = [
            (row.created_at, table, row)
            for table in _REPLAYABLE_TABLES
            for row in self._store.list_pending(table, limit=limit)
        ]
        ready.sort(key=lambda item: item[0])

        outcome = ReplayOutcome()
        for _, table, row in ready:
            try:
                await self._send(table, row)
            except StudioApiError as error:
                if is_retryable(error):
                    self._store.mark_failed(table, row.id, str(error), self._retry_policy)
                    outcome.stopped_on_transient_error = True
                    logger.warning("outbox replay paused on transient error", exc_info=True)
                    break
                self._store.move_to_dead_letter(table, row.id, str(error))
                outcome.dead_lettered += 1
                logger.warning("outbox row dead-lettered", exc_info=True)
            else:
                self._store.mark_succeeded(table, row.id)
                outcome.succeeded += 1
        return outcome

    async def _send(self, table: OutboxTable, row: PendingRow) -> None:
        if table is OutboxTable.EVENTS:
            await self._client.post_event(_event_from_row(row))
        else:
            await self._client.send_mutation(
                str(row.extra["method"]),
                str(row.extra["path"]),
                row.payload,
                idempotency_key=row.id,
            )


def _event_from_row(row: PendingRow) -> EventCreate:
    extra = row.extra
    return EventCreate(
        event_id=UUID(row.id),
        event_type=EventType(str(extra["event_type"])),
        project_id=UUID(str(extra["project_id"])),
        task_id=UUID(str(extra["task_id"])) if extra.get("task_id") else None,
        machine_id=UUID(str(extra["machine_id"])) if extra.get("machine_id") else None,
        actor_type=str(extra["actor_type"]),  # type: ignore[arg-type]
        actor_id=UUID(str(extra["actor_id"])),
        client_timestamp=datetime.fromisoformat(str(extra["client_timestamp"])),
        payload=row.payload,
        schema_version=int(str(extra["schema_version"])),
    )
