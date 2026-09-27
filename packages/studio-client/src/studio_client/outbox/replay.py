from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from studio_contracts.events import EventCreate, EventType
from studio_contracts.local.identity import IdentityBinding

from studio_client.api_client import StudioApiClient
from studio_client.errors import ForbiddenError, StudioApiError
from studio_client.outbox.models import OutboxTable, PendingRow
from studio_client.outbox.store import (
    PROJECT_ACCESS_DENIED,
    OutboxIdentityError,
    OutboxStore,
    transaction,
)
from studio_client.retry import RetryPolicy, is_retryable

logger = logging.getLogger(__name__)

_REPLAYABLE_TABLES = (OutboxTable.EVENTS, OutboxTable.MUTATIONS)
"""`pending_markers` has no server target yet — no endpoint consumes a
`recording.marker.created`-shaped row (only the `EventType` member exists,
`rg marker services/` finds no router/tool). Replaying it here would mean
inventing a call. Rows stay queued untouched until whichever future
sub-step adds that endpoint defines what a marker replay actually sends."""


_PROJECT_PATH_RE = re.compile(r"/projects/([0-9a-fA-F-]{36})(?:/|$|\?)")


@dataclass
class ReplayOutcome:
    succeeded: int = 0
    dead_lettered: int = 0
    stopped_on_transient_error: bool = False
    identity_mismatch: bool = False
    project_access_denied: list[str] = field(default_factory=list)
    """Projects whose queued work was dead-lettered by a 403 from project
    isolation during this pass (deduplicated, `unknown` if not derivable)."""


def is_project_access_denied(error: StudioApiError) -> bool:
    """403 `forbidden` on `resource: project`: the account has no access to
    the project (or it does not exist). Final: replaying can never succeed."""
    return isinstance(error, ForbiddenError) and error.details.get("resource") == "project"


def _row_project_id(table: OutboxTable, row: PendingRow) -> str | None:
    candidate = row.extra.get("project_id") or row.payload.get("project_id")
    if candidate:
        return str(candidate)
    if table is OutboxTable.MUTATIONS:
        match = _PROJECT_PATH_RE.search(str(row.extra.get("path", "")))
        if match is not None:
            return match.group(1)
    return None


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
        self,
        store: OutboxStore,
        client: StudioApiClient,
        retry_policy: RetryPolicy,
        *,
        active_binding: IdentityBinding | None = None,
    ) -> None:
        self._store = store
        self._client = client
        self._retry_policy = retry_policy
        self._active_binding = active_binding

    async def replay_ready(self, *, limit: int = 100) -> ReplayOutcome:
        if self._active_binding is not None:
            try:
                self._store.assert_identity(self._active_binding)
            except OutboxIdentityError:
                logger.error("outbox replay refused: identity mismatch")
                return ReplayOutcome(identity_mismatch=True)
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
                    with transaction(self._store.connection):
                        self._store.mark_failed(table, row.id, str(error), self._retry_policy)
                    outcome.stopped_on_transient_error = True
                    logger.warning("outbox replay paused on transient error", exc_info=True)
                    break
                reason = str(error)
                denied_project: str | None = None
                if is_project_access_denied(error):
                    denied_project = _row_project_id(table, row) or "unknown"
                    reason = f"{PROJECT_ACCESS_DENIED} project={denied_project}: {error}"
                    if denied_project not in outcome.project_access_denied:
                        outcome.project_access_denied.append(denied_project)
                with transaction(self._store.connection):
                    self._store.move_to_dead_letter(table, row.id, reason)
                outcome.dead_lettered += 1
                if denied_project is not None:
                    logger.warning(
                        "outbox row %s dead-lettered: this account has no access to project %s "
                        "(403 forbidden); the row is kept in dead_letter for inspection",
                        row.id,
                        denied_project,
                    )
                else:
                    logger.warning("outbox row dead-lettered", exc_info=True)
            else:
                with transaction(self._store.connection):
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
