from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from studio_contracts.events import EventCreate
from studio_contracts.local.daemon_control import ReplayVerdict, decide_outbox_replay
from studio_contracts.local.identity import IdentityBinding, partition_key

from studio_client.config import default_config_path
from studio_client.outbox.models import (
    PRIMARY_KEY_COLUMN,
    MultipartUploadState,
    OutboxTable,
    PendingRow,
)
from studio_client.retry import RetryPolicy

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_id TEXT,
    machine_id TEXT,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    client_timestamp TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_mutations (
    idempotency_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_markers (
    marker_id TEXT PRIMARY KEY,
    marker_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dead_letter (
    id TEXT PRIMARY KEY,
    source_table TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    error TEXT NOT NULL,
    failed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS multipart_uploads (
    transfer_id TEXT PRIMARY KEY,
    upload_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    part_size_bytes INTEGER NOT NULL,
    part_urls_json TEXT NOT NULL,
    completed_parts_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def default_outbox_path() -> Path:
    """Sibling of `config.default_config_path()` — same per-OS base
    directory, so a fresh install gets both without extra setup."""
    return default_config_path().with_name("outbox.sqlite3")


def partitioned_outbox_path(binding: IdentityBinding, *, root: Path | None = None) -> Path:
    base = root or default_config_path().with_name("outbox")
    return base / f"{partition_key(binding)}.sqlite3"


class OutboxIdentityError(RuntimeError):
    def __init__(self, mismatched: list[str]) -> None:
        super().__init__("outbox identity mismatch")
        self.mismatched = tuple(mismatched)


def _migrate(conn: sqlite3.Connection) -> None:
    """`CREATE TABLE IF NOT EXISTS` in `_SCHEMA` never touches a table that
    already exists from an older version of this client (DEC-0037) — a
    column added since then needs an explicit, idempotent `ALTER TABLE`
    here, checked against the real schema rather than a version counter, so
    reopening an old `outbox.sqlite3` (the exact scenario a resumed
    multipart upload depends on) picks it up transparently."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(multipart_uploads)")}
    if "part_urls_expires_at" not in columns:
        conn.execute("ALTER TABLE multipart_uploads ADD COLUMN part_urls_expires_at TEXT")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Groups every statement run inside the block into one SQLite
    transaction — commits on success, rolls back on any exception. Use
    this to enqueue an outbox row in the same transaction as the local
    write it represents (`.claude/rules/offline-sync.md`): the store's
    own `enqueue_*` methods never commit on their own."""
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


class OutboxStore:
    """SQLite-backed offline queue (sous-etape 6.3,
    docs/ROADMAP_STEP6_BREAKDOWN.md). Every `enqueue_*` is a plain
    `conn.execute()` with no commit of its own — the caller decides the
    transaction boundary (bare, or via `transaction()`), so an enqueue can
    share one transaction with the local write it represents."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def identity_binding(self) -> IdentityBinding | None:
        value = self.get_sync_state("daemon.identity_binding")
        return IdentityBinding.model_validate(value) if value is not None else None

    def bind_identity(self, active: IdentityBinding) -> None:
        existing = self.identity_binding()
        if existing is not None:
            decision = decide_outbox_replay(existing, active)
            if decision.verdict is not ReplayVerdict.ALLOW:
                raise OutboxIdentityError(decision.mismatched)
            return
        if self.has_queued_work():
            raise OutboxIdentityError(["binding_missing"])
        with transaction(self._conn):
            self.set_sync_state("daemon.identity_binding", active.model_dump(mode="json"))

    def assert_identity(self, active: IdentityBinding) -> None:
        existing = self.identity_binding()
        if existing is None:
            raise OutboxIdentityError(["binding_missing"])
        decision = decide_outbox_replay(existing, active)
        if decision.verdict is not ReplayVerdict.ALLOW:
            raise OutboxIdentityError(decision.mismatched)

    def has_queued_work(self) -> bool:
        tables = [*(table.value for table in OutboxTable), "dead_letter", "multipart_uploads"]
        return any(
            self._conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
            for table in tables
        )

    def pending_count(self) -> int:
        return sum(
            int(self._conn.execute(f"SELECT COUNT(*) FROM {table.value}").fetchone()[0])
            for table in OutboxTable
        )

    def oldest_pending_at(self) -> datetime | None:
        values = [
            row[0]
            for table in OutboxTable
            if (row := self._conn.execute(
                f"SELECT MIN(created_at) FROM {table.value}"
            ).fetchone()) is not None
            and row[0] is not None
        ]
        return datetime.fromisoformat(min(values)) if values else None

    def enqueue_event(self, event: EventCreate) -> bool:
        """Returns True if a new row was inserted, False if
        `event.event_id` was already queued — that id, generated by the
        caller, is the dedup key (never generated by this store)."""
        now = _utcnow_iso()
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO pending_events "
            "(event_id, event_type, project_id, task_id, machine_id, actor_type, "
            "actor_id, client_timestamp, payload_json, schema_version, "
            "next_attempt_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(event.event_id),
                event.event_type.value,
                str(event.project_id),
                str(event.task_id) if event.task_id else None,
                str(event.machine_id) if event.machine_id else None,
                event.actor_type,
                str(event.actor_id),
                event.client_timestamp.isoformat(),
                json.dumps(event.payload),
                event.schema_version,
                now,
                now,
            ),
        )
        return cursor.rowcount > 0

    def enqueue_mutation(
        self, idempotency_key: str, kind: str, method: str, path: str, payload: dict[str, object]
    ) -> bool:
        """`idempotency_key` must be generated by the caller, stable across
        retries — never by `StudioApiClient` (DEC-0024)."""
        now = _utcnow_iso()
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO pending_mutations "
            "(idempotency_key, kind, method, path, payload_json, next_attempt_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (idempotency_key, kind, method, path, json.dumps(payload), now, now),
        )
        return cursor.rowcount > 0

    def enqueue_marker(
        self, marker_id: UUID | str, marker_type: str, payload: dict[str, object]
    ) -> bool:
        now = _utcnow_iso()
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO pending_markers "
            "(marker_id, marker_type, payload_json, next_attempt_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(marker_id), marker_type, json.dumps(payload), now, now),
        )
        return cursor.rowcount > 0

    def list_pending(
        self, table: OutboxTable, *, ready_only: bool = True, limit: int = 100
    ) -> list[PendingRow]:
        query = f"SELECT * FROM {table.value}"
        params: tuple[object, ...] = ()
        if ready_only:
            query += " WHERE next_attempt_at <= ?"
            params = (_utcnow_iso(),)
        query += " ORDER BY created_at ASC LIMIT ?"
        rows = self._conn.execute(query, (*params, limit)).fetchall()
        return [self._to_pending_row(table, row) for row in rows]

    def mark_succeeded(self, table: OutboxTable, row_id: str) -> None:
        pk = PRIMARY_KEY_COLUMN[table]
        self._conn.execute(f"DELETE FROM {table.value} WHERE {pk} = ?", (row_id,))

    def mark_failed(
        self, table: OutboxTable, row_id: str, error: str, retry_policy: RetryPolicy
    ) -> None:
        """Bumps `attempt_count` and reschedules `next_attempt_at` using
        `retry_policy`'s bounded exponential delay. Never gives up on
        attempt count alone — the offline invariant is that the client
        keeps retrying while the network is down; only an explicit
        `move_to_dead_letter()` call (a definitive, non-transient error)
        stops the retries."""
        pk = PRIMARY_KEY_COLUMN[table]
        row = self._conn.execute(
            f"SELECT attempt_count FROM {table.value} WHERE {pk} = ?", (row_id,)
        ).fetchone()
        if row is None:
            return
        attempt = row["attempt_count"] + 1
        delay = retry_policy.delay_for(attempt)
        next_attempt_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
        self._conn.execute(
            f"UPDATE {table.value} SET attempt_count = ?, next_attempt_at = ?, "
            f"last_error = ? WHERE {pk} = ?",
            (attempt, next_attempt_at, error, row_id),
        )

    def move_to_dead_letter(self, table: OutboxTable, row_id: str, error: str) -> None:
        """A definitive (non-transient) failure: recorded in `dead_letter`
        for inspection rather than dropped silently, then removed from the
        replayable queue."""
        pk = PRIMARY_KEY_COLUMN[table]
        row = self._conn.execute(
            f"SELECT * FROM {table.value} WHERE {pk} = ?", (row_id,)
        ).fetchone()
        if row is None:
            return
        payload = json.dumps({key: row[key] for key in row.keys()})
        self._conn.execute(
            "INSERT INTO dead_letter (id, source_table, payload_json, error, failed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (row_id, table.value, payload, error, _utcnow_iso()),
        )
        self._conn.execute(f"DELETE FROM {table.value} WHERE {pk} = ?", (row_id,))

    def get_sync_state(self, key: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT value_json FROM sync_state WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row["value_json"]) if row else None

    def set_sync_state(self, key: str, value: dict[str, object]) -> None:
        self._conn.execute(
            "INSERT INTO sync_state (key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value), _utcnow_iso()),
        )

    def save_multipart_upload(
        self,
        transfer_id: str,
        upload_id: str,
        file_path: str,
        part_size_bytes: int,
        part_urls: dict[int, str],
        part_urls_expires_at: datetime | None = None,
    ) -> None:
        """Records the presigned part URLs from a fresh `upload/initiate`
        call. `INSERT OR REPLACE` deliberately: calling this again for a
        `transfer_id` that already has state (a caller re-initiating rather
        than resuming) restarts progress from zero rather than mixing part
        URLs from two different `upload_id`s. `part_urls_expires_at` absent
        (older server or a value never provided) means "unknown expiry" —
        `TransferClient` treats that as "refresh before every resume"
        (DEC-0037), the safe default."""
        self._conn.execute(
            "INSERT OR REPLACE INTO multipart_uploads "
            "(transfer_id, upload_id, file_path, part_size_bytes, part_urls_json, "
            "completed_parts_json, created_at, part_urls_expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                transfer_id,
                upload_id,
                file_path,
                part_size_bytes,
                json.dumps(part_urls),
                json.dumps({}),
                _utcnow_iso(),
                part_urls_expires_at.isoformat() if part_urls_expires_at else None,
            ),
        )

    def update_part_urls(
        self,
        transfer_id: str,
        part_urls: dict[int, str],
        part_urls_expires_at: datetime,
        uploaded_parts: dict[int, str],
    ) -> None:
        """Merges a `refresh-parts` response into existing state (DEC-0037):
        `part_urls` for the still-missing parts are added (never removing an
        already-cached URL for a part refresh didn't ask about), and
        `uploaded_parts` — storage's own authoritative record — is merged
        into `completed_parts` so a part whose PUT succeeded but whose local
        write was lost (crash between the PUT and `record_completed_part`)
        is adopted rather than re-uploaded."""
        state = self.get_multipart_upload(transfer_id)
        if state is None:
            return
        merged_urls = {**state.part_urls, **part_urls}
        merged_completed = {**state.completed_parts, **uploaded_parts}
        self._conn.execute(
            "UPDATE multipart_uploads SET part_urls_json = ?, completed_parts_json = ?, "
            "part_urls_expires_at = ? WHERE transfer_id = ?",
            (
                json.dumps(merged_urls),
                json.dumps(merged_completed),
                part_urls_expires_at.isoformat(),
                transfer_id,
            ),
        )

    def get_multipart_upload(self, transfer_id: str) -> MultipartUploadState | None:
        row = self._conn.execute(
            "SELECT * FROM multipart_uploads WHERE transfer_id = ?", (transfer_id,)
        ).fetchone()
        if row is None:
            return None
        expires_at = row["part_urls_expires_at"]
        return MultipartUploadState(
            transfer_id=row["transfer_id"],
            upload_id=row["upload_id"],
            file_path=row["file_path"],
            part_size_bytes=row["part_size_bytes"],
            part_urls={int(k): v for k, v in json.loads(row["part_urls_json"]).items()},
            completed_parts={int(k): v for k, v in json.loads(row["completed_parts_json"]).items()},
            created_at=datetime.fromisoformat(row["created_at"]),
            part_urls_expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
        )

    def record_completed_part(self, transfer_id: str, part_number: int, etag: str) -> None:
        state = self.get_multipart_upload(transfer_id)
        if state is None:
            return
        completed = dict(state.completed_parts)
        completed[part_number] = etag
        self._conn.execute(
            "UPDATE multipart_uploads SET completed_parts_json = ? WHERE transfer_id = ?",
            (json.dumps(completed), transfer_id),
        )

    def delete_multipart_upload(self, transfer_id: str) -> None:
        self._conn.execute("DELETE FROM multipart_uploads WHERE transfer_id = ?", (transfer_id,))

    def _to_pending_row(self, table: OutboxTable, row: sqlite3.Row) -> PendingRow:
        pk = PRIMARY_KEY_COLUMN[table]
        reserved = {
            pk,
            "attempt_count",
            "next_attempt_at",
            "created_at",
            "last_error",
            "payload_json",
        }
        extra = {key: row[key] for key in row.keys() if key not in reserved}
        return PendingRow(
            id=row[pk],
            attempt_count=row["attempt_count"],
            next_attempt_at=datetime.fromisoformat(row["next_attempt_at"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_error=row["last_error"],
            payload=json.loads(row["payload_json"]),
            extra=extra,
        )
