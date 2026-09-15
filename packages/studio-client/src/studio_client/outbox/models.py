from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OutboxTable(StrEnum):
    """The three replayable queues (docs/ROADMAP_STEP6_BREAKDOWN.md sous-etape
    6.3); `dead_letter` is a terminal sink, never a source, so it has no
    entry here."""

    EVENTS = "pending_events"
    MUTATIONS = "pending_mutations"
    MARKERS = "pending_markers"


PRIMARY_KEY_COLUMN: dict[OutboxTable, str] = {
    OutboxTable.EVENTS: "event_id",
    OutboxTable.MUTATIONS: "idempotency_key",
    OutboxTable.MARKERS: "marker_id",
}


@dataclass(frozen=True)
class PendingRow:
    """One row ready (or not yet ready) for replay. `extra` carries every
    column beyond the common bookkeeping ones, keyed by column name — the
    replay logic (sous-etape 6.4) knows the shape per `OutboxTable`, the
    store itself does not."""

    id: str
    attempt_count: int
    next_attempt_at: datetime
    created_at: datetime
    last_error: str | None
    payload: dict[str, object]
    extra: dict[str, object]


@dataclass(frozen=True)
class MultipartUploadState:
    """Local progress of one in-flight multipart upload (sous-etape 6.7,
    `.claude/rules/offline-sync.md` `multipart_uploads` table). Persists the
    presigned per-part URLs handed out by the single `upload/initiate` call
    that started this upload — the server creates a brand-new `upload_id`
    on every call (`services/api/src/studio_api/services/transfers.py`), so
    resuming after a restart replays against these cached URLs rather than
    re-initiating, and only fails if they have since expired (10-30 min,
    `.claude/rules/storage-transfers.md`)."""

    transfer_id: str
    upload_id: str
    file_path: str
    part_size_bytes: int
    part_urls: dict[int, str]
    completed_parts: dict[int, str]
    created_at: datetime
    part_urls_expires_at: datetime | None = None
