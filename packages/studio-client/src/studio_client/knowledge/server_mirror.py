from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from studio_contracts.vault import (
    VaultActorType,
    VaultNote,
    VaultNoteLink,
    VaultNoteStatus,
    VaultNoteSummary,
    VaultNoteType,
    VaultScope,
    VaultTreePage,
)

from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.memory import (
    MemoryNoteHit,
    MemoryProposal,
    MemoryReadResult,
    MemorySearchResult,
    make_excerpt,
)
from studio_client.knowledge.scope import ScopePolicy

MIRROR_SCHEMA_VERSION = 1
MIRROR_FILENAME = "server-vault-mirror.sqlite3"
DEFAULT_STALE_AFTER_SECONDS = 3600.0
DEFAULT_TREE_LIMIT = 200

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS notes (
        id TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        project_id TEXT,
        slug TEXT NOT NULL,
        readable_id TEXT,
        note_type TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        links_json TEXT NOT NULL,
        anchors_json TEXT NOT NULL,
        version INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        author_type TEXT NOT NULL,
        author_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mirror_notes_slug ON notes (slug)",
    "CREATE INDEX IF NOT EXISTS idx_mirror_notes_scope ON notes (scope, status)",
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)


def mirror_relative_paths(scope: VaultScope, project_id: UUID | None, slug: str) -> tuple[str, ...]:
    """Vault-relative paths a server note maps to for `ScopePolicy`.

    Studio notes are readable through `global/` or `conventions/` (DEC-0042);
    project notes through `projects/<project_id>/`. The policy stays closed
    by default: an empty policy exposes nothing.
    """
    if scope is VaultScope.STUDIO:
        return (f"global/{slug}", f"conventions/{slug}")
    if project_id is None:
        return ()
    return (f"projects/{project_id}/{slug}",)


def is_note_in_scope(policy: ScopePolicy, summary: VaultNoteSummary) -> bool:
    paths = mirror_relative_paths(summary.scope, summary.project_id, summary.slug)
    return any(policy.is_exposed(path) for path in paths)


def _scope_is_closed(policy: ScopePolicy) -> bool:
    return all(prefix == "" for prefix in policy.allowed_prefixes)


@dataclass(frozen=True)
class MirrorSyncReport:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    fetched: int = 0
    total: int = 0
    last_synced_at: datetime | None = None


@dataclass(frozen=True)
class MirrorFreshness:
    last_synced_at: datetime | None
    last_attempt_at: datetime | None
    last_error: str | None
    stale: bool
    reason: str


@dataclass(frozen=True)
class _LocalState:
    version: int
    content_hash: str
    status: str


class ServerVaultMirror:
    """Local read-only cache of the server vault notes the server lets us read.

    SQLite file in the daemon cache directory, same style as the other client
    stores. `sync` walks the paginated tree, refetches only notes whose
    `version`/`content_hash`/`status` changed, deletes local rows missing from
    the authorized tree, and records `last_synced_at`. Offline reads
    (`get`/`list_notes`/`search`) never touch the network.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        self._db_path = db_path
        self._stale_after_seconds = stale_after_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self, connection: sqlite3.Connection) -> None:
        for statement in _SCHEMA:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO NOTHING",
            (str(MIRROR_SCHEMA_VERSION),),
        )

    def _get_meta(self, connection: sqlite3.Connection, key: str) -> str | None:
        row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _set_meta(self, connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _record_success(self, connection: sqlite3.Connection, now: datetime) -> None:
        self._set_meta(connection, "last_synced_at", now.isoformat())
        self._set_meta(connection, "last_attempt_at", now.isoformat())
        self._set_meta(connection, "last_sync_error", "")

    def _record_failure(self, error: str, now: datetime) -> None:
        connection = self._connect()
        try:
            self._init_schema(connection)
            self._set_meta(connection, "last_attempt_at", now.isoformat())
            self._set_meta(connection, "last_sync_error", error[:500])
            connection.commit()
        finally:
            connection.close()

    def drop(self) -> bool:
        removed = False
        for candidate in self._db_path.parent.glob(f"{self._db_path.name}*"):
            if candidate.is_file():
                candidate.unlink()
                removed = True
        return removed

    def count(self) -> int:
        if not self._db_path.is_file():
            return 0
        connection = self._connect()
        try:
            row = connection.execute("SELECT COUNT(*) AS total FROM notes").fetchone()
        except sqlite3.DatabaseError:
            return 0
        finally:
            connection.close()
        return 0 if row is None else int(row["total"])

    def purge_out_of_scope(self, scope: ScopePolicy) -> int:
        if not self._db_path.is_file():
            return 0
        connection = self._connect()
        try:
            self._init_schema(connection)
            rows = connection.execute("SELECT id, scope, project_id, slug FROM notes").fetchall()
            removed = 0
            for row in rows:
                paths = mirror_relative_paths(
                    VaultScope(str(row["scope"])),
                    UUID(str(row["project_id"])) if row["project_id"] else None,
                    str(row["slug"]),
                )
                if not any(scope.is_exposed(path) for path in paths):
                    connection.execute("DELETE FROM notes WHERE id = ?", (str(row["id"]),))
                    removed += 1
            connection.commit()
            return removed
        finally:
            connection.close()

    async def sync(
        self,
        client: httpx.AsyncClient,
        scope: ScopePolicy,
        *,
        include_archived: bool = True,
        tree_limit: int = DEFAULT_TREE_LIMIT,
    ) -> MirrorSyncReport:
        now = self._clock()
        if _scope_is_closed(scope):
            removed = self.purge_out_of_scope(scope)
            connection = self._connect()
            try:
                self._init_schema(connection)
                self._record_success(connection, now)
                connection.commit()
            finally:
                connection.close()
            return MirrorSyncReport(removed=removed, last_synced_at=now)
        try:
            tree = await self._fetch_tree(
                client, include_archived=include_archived, limit=tree_limit
            )
        except Exception as exc:
            self._record_failure(str(exc), self._clock())
            raise
        visible = [item for item in tree if is_note_in_scope(scope, item)]
        local = self._load_local_state()
        visible_by_id = {str(item.id): item for item in visible}
        to_delete = sorted(set(local) - set(visible_by_id))
        to_fetch: list[VaultNoteSummary] = []
        for item in visible:
            known = local.get(str(item.id))
            if known is None:
                to_fetch.append(item)
            elif (
                known.version != item.version
                or known.content_hash != item.content_hash
                or known.status != item.status.value
            ):
                to_fetch.append(item)
        try:
            fetched = await self._fetch_notes(client, to_fetch)
        except Exception as exc:
            self._record_failure(str(exc), self._clock())
            raise
        return self._store_sync_result(
            visible_by_id=visible_by_id,
            to_delete=to_delete,
            requested={str(item.id) for item in to_fetch},
            fetched=fetched,
            local=local,
            now=now,
        )

    async def _fetch_tree(
        self, client: httpx.AsyncClient, *, include_archived: bool, limit: int
    ) -> list[VaultNoteSummary]:
        items: list[VaultNoteSummary] = []
        cursor: str | None = None
        while True:
            params: dict[str, str] = {
                "include_archived": "true" if include_archived else "false",
                "limit": str(limit),
            }
            if cursor is not None:
                params["cursor"] = cursor
            response = await client.get("/api/v1/vault/tree", params=params)
            response.raise_for_status()
            page = VaultTreePage.model_validate(response.json())
            items.extend(page.items)
            if page.next_cursor is None:
                return items
            cursor = page.next_cursor

    async def _fetch_notes(
        self, client: httpx.AsyncClient, wanted: Sequence[VaultNoteSummary]
    ) -> list[VaultNote]:
        fetched: list[VaultNote] = []
        for summary in wanted:
            response = await client.get(f"/api/v1/vault/notes/{summary.id}")
            if response.status_code in (403, 404):
                continue
            response.raise_for_status()
            fetched.append(VaultNote.model_validate(response.json()))
        return fetched

    def _load_local_state(self) -> dict[str, _LocalState]:
        if not self._db_path.is_file():
            return {}
        connection = self._connect()
        try:
            try:
                rows = connection.execute(
                    "SELECT id, version, content_hash, status FROM notes"
                ).fetchall()
            except sqlite3.DatabaseError:
                return {}
            return {
                str(row["id"]): _LocalState(
                    version=int(row["version"]),
                    content_hash=str(row["content_hash"]),
                    status=str(row["status"]),
                )
                for row in rows
            }
        finally:
            connection.close()

    def _store_sync_result(
        self,
        *,
        visible_by_id: dict[str, VaultNoteSummary],
        to_delete: Sequence[str],
        requested: set[str],
        fetched: Sequence[VaultNote],
        local: dict[str, _LocalState],
        now: datetime,
    ) -> MirrorSyncReport:
        fetched_by_id = {str(note.id): note for note in fetched}
        # Listed but no longer readable when fetched (deleted or rights revoked).
        missing_fetch = requested - set(fetched_by_id)
        effectively_visible = {key for key in visible_by_id if key not in missing_fetch}
        added = sum(1 for key in fetched_by_id if key not in local)
        updated = len(fetched_by_id) - added
        connection = self._connect()
        try:
            self._init_schema(connection)
            for note_id in to_delete:
                connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            for note_id in missing_fetch:
                connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            for note in fetched:
                _upsert_note(connection, note)
            self._record_success(connection, now)
            connection.commit()
        finally:
            connection.close()
        removed = len(to_delete) + len(missing_fetch)
        unchanged = len(effectively_visible) - len(fetched_by_id)
        return MirrorSyncReport(
            added=added,
            updated=updated,
            removed=removed,
            unchanged=unchanged,
            fetched=len(fetched_by_id),
            total=len(effectively_visible),
            last_synced_at=now,
        )

    def get(self, note_id: UUID) -> VaultNote | None:
        if not self._db_path.is_file():
            return None
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM notes WHERE id = ?", (str(note_id),)).fetchone()
        finally:
            connection.close()
        return None if row is None else _note_from_row(row)

    def find_by_slug(self, slug: str) -> list[VaultNoteSummary]:
        if not self._db_path.is_file():
            return []
        connection = self._connect()
        try:
            rows = connection.execute("SELECT * FROM notes WHERE slug = ?", (slug,)).fetchall()
        except sqlite3.DatabaseError:
            return []
        finally:
            connection.close()
        return [_summary_from_row(row) for row in rows]

    def list_notes(
        self,
        *,
        scope: VaultScope | None = None,
        project_id: UUID | None = None,
        status: VaultNoteStatus | None = None,
        limit: int = 200,
    ) -> list[VaultNoteSummary]:
        if not self._db_path.is_file():
            return []
        clauses: list[str] = []
        params: list[str] = []
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope.value)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(str(project_id))
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        connection = self._connect()
        try:
            rows = connection.execute(
                f"SELECT * FROM notes {where} ORDER BY slug LIMIT ?",
                (*params, limit),
            ).fetchall()
        except sqlite3.DatabaseError:
            return []
        finally:
            connection.close()
        return [_summary_from_row(row) for row in rows]

    def search(self, query: str, *, limit: int = 20) -> list[VaultNoteSummary]:
        needle = query.strip().lower()
        if not needle or not self._db_path.is_file():
            return []
        if limit <= 0:
            raise ValueError("limit must be positive")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM notes WHERE lower(title) LIKE ? OR lower(summary) LIKE ? "
                "OR lower(body) LIKE ? OR lower(slug) LIKE ? ORDER BY slug LIMIT ?",
                (f"%{needle}%", f"%{needle}%", f"%{needle}%", f"%{needle}%", limit),
            ).fetchall()
        except sqlite3.DatabaseError:
            return []
        finally:
            connection.close()
        return [_summary_from_row(row) for row in rows]

    def freshness(self, *, now: datetime | None = None) -> MirrorFreshness:
        moment = now or self._clock()
        if not self._db_path.is_file():
            return MirrorFreshness(None, None, None, True, "never_synced")
        connection = self._connect()
        try:
            synced_raw = self._get_meta(connection, "last_synced_at")
            attempt_raw = self._get_meta(connection, "last_attempt_at")
            error_raw = self._get_meta(connection, "last_sync_error")
        except sqlite3.DatabaseError:
            return MirrorFreshness(None, None, "index_unreadable", True, "unreadable")
        finally:
            connection.close()
        last_synced = _parse_dt(synced_raw)
        last_attempt = _parse_dt(attempt_raw)
        last_error = error_raw if error_raw else None
        if last_error:
            return MirrorFreshness(last_synced, last_attempt, last_error, True, "last_sync_failed")
        if last_synced is None:
            return MirrorFreshness(None, last_attempt, None, True, "never_synced")
        age = (moment - last_synced).total_seconds()
        if age > self._stale_after_seconds:
            return MirrorFreshness(last_synced, last_attempt, None, True, "older_than_threshold")
        return MirrorFreshness(last_synced, last_attempt, None, False, "fresh")


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _upsert_note(connection: sqlite3.Connection, note: VaultNote) -> None:
    connection.execute(
        "INSERT INTO notes (id, scope, project_id, slug, readable_id, note_type, title, "
        "summary, body, status, tags_json, links_json, anchors_json, version, content_hash, "
        "author_type, author_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET scope = excluded.scope, project_id = excluded.project_id, "
        "slug = excluded.slug, readable_id = excluded.readable_id, note_type = excluded.note_type, "
        "title = excluded.title, summary = excluded.summary, body = excluded.body, "
        "status = excluded.status, tags_json = excluded.tags_json, "
        "links_json = excluded.links_json, "
        "anchors_json = excluded.anchors_json, version = excluded.version, "
        "content_hash = excluded.content_hash, author_type = excluded.author_type, "
        "author_id = excluded.author_id, created_at = excluded.created_at, "
        "updated_at = excluded.updated_at",
        (
            str(note.id),
            note.scope.value,
            str(note.project_id) if note.project_id is not None else None,
            note.slug,
            note.readable_id,
            note.note_type.value,
            note.title,
            note.summary,
            note.body,
            note.status.value,
            json.dumps(list(note.tags)),
            json.dumps(
                [
                    {"target_note_id": str(link.target_note_id), "kind": link.kind.value}
                    for link in note.links
                ]
            ),
            json.dumps(list(note.anchors)),
            note.version,
            note.content_hash,
            note.author_type.value,
            str(note.author_id),
            note.created_at.isoformat(),
            note.updated_at.isoformat(),
        ),
    )


def _summary_from_row(row: sqlite3.Row) -> VaultNoteSummary:
    return VaultNoteSummary(
        id=UUID(str(row["id"])),
        scope=VaultScope(str(row["scope"])),
        project_id=UUID(str(row["project_id"])) if row["project_id"] else None,
        slug=str(row["slug"]),
        readable_id=str(row["readable_id"]) if row["readable_id"] else None,
        note_type=VaultNoteType(str(row["note_type"])),
        title=str(row["title"]),
        summary=str(row["summary"]),
        status=VaultNoteStatus(str(row["status"])),
        tags=list(json.loads(str(row["tags_json"]))),
        links=[VaultNoteLink.model_validate(entry) for entry in json.loads(str(row["links_json"]))],
        anchors=list(json.loads(str(row["anchors_json"]))),
        content_hash=str(row["content_hash"]),
        author_type=VaultActorType(str(row["author_type"])),
        author_id=UUID(str(row["author_id"])),
        version=int(row["version"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _note_from_row(row: sqlite3.Row) -> VaultNote:
    summary = _summary_from_row(row)
    return VaultNote(**summary.model_dump(mode="python"), body=str(row["body"]))


class ServerMirrorMemoryProvider:
    """`MemoryProvider`-shaped read adapter over the server mirror.

    Offline only: `search`/`read` hit the SQLite cache, writes raise
    `WRITE_UNSUPPORTED` like the other read-only adapters.
    """

    def __init__(
        self,
        mirror: ServerVaultMirror,
        scope: ScopePolicy | None = None,
        *,
        excerpt_chars: int = 500,
    ) -> None:
        if excerpt_chars <= 0:
            raise ValueError("excerpt_chars must be positive")
        self._mirror = mirror
        self._scope = scope or ScopePolicy()
        self._excerpt_chars = excerpt_chars

    def search(self, query: str, *, max_results: int = 20) -> MemorySearchResult:
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        needle = query.strip()
        if not needle:
            return MemorySearchResult(matches=[])
        hits: list[MemoryNoteHit] = []
        for summary in self._mirror.search(needle, limit=max_results):
            if not is_note_in_scope(self._scope, summary):
                continue
            note = self._mirror.get(summary.id)
            body = note.body if note is not None else summary.summary
            excerpt, truncated = make_excerpt(body, needle, self._excerpt_chars)
            hits.append(
                MemoryNoteHit(
                    path=summary.slug, title=summary.title, excerpt=excerpt, truncated=truncated
                )
            )
            if len(hits) >= max_results:
                break
        freshness = self._mirror.freshness()
        reason = None if not freshness.stale else f"mirror_{freshness.reason}"
        return MemorySearchResult(matches=hits, reason=reason)

    def read(self, path: str, *, max_chars: int = 4000) -> MemoryReadResult:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        scope, project_id, slug = _parse_path(path)
        candidates = [
            item
            for item in self._mirror.find_by_slug(slug)
            if (scope is None or item.scope is scope)
            and (project_id is None or str(item.project_id) == project_id)
        ]
        if not candidates:
            raise KnowledgeError(KnowledgeError.NOT_FOUND, f"note not mirrored: {path!r}")
        in_scope = [item for item in candidates if is_note_in_scope(self._scope, item)]
        if not in_scope:
            raise KnowledgeError(KnowledgeError.OUT_OF_SCOPE, "note outside the mirrored scope")
        # Bare slug matching several notes: the project note wins over the studio one.
        summary = min(in_scope, key=lambda item: item.scope is not VaultScope.PROJECT)
        note = self._mirror.get(summary.id)
        if note is None:
            raise KnowledgeError(KnowledgeError.NOT_FOUND, f"note not mirrored: {path!r}")
        content, truncated = make_excerpt(note.body, "", max_chars)
        return MemoryReadResult(
            path=summary.slug, title=summary.title, content=content, truncated=truncated
        )

    def propose(self, proposal: MemoryProposal) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "the server mirror is read-only; writes go through the vault API",
        )

    def write_if_authorized(self, proposal: MemoryProposal) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "the server mirror is read-only; writes go through the vault API",
        )

    def append_task_log(self, entry: dict[str, object]) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "the server mirror is read-only; writes go through the vault API",
        )

    def create_decision_note(self, note: dict[str, object]) -> object:
        raise KnowledgeError(
            KnowledgeError.WRITE_UNSUPPORTED,
            "the server mirror is read-only; writes go through the vault API",
        )


def _parse_path(path: str) -> tuple[VaultScope | None, str | None, str]:
    """`global/<slug>`, `conventions/<slug>`, `projects/<id>/<slug>` or a bare slug."""
    cleaned = path.strip().replace("\\", "/").strip("/")
    for prefix in ("global/", "conventions/"):
        if cleaned.startswith(prefix):
            return VaultScope.STUDIO, None, cleaned[len(prefix) :]
    if cleaned.startswith("projects/"):
        parts = cleaned.split("/")
        if len(parts) >= 3:
            return VaultScope.PROJECT, parts[1], "/".join(parts[2:])
    return None, None, cleaned
