"""OpenCode desktop/CLI sessions (`~/.local/share/opencode/opencode.db`).

Certified against the SQLite store written by OpenCode 1.18.x: `session`
(directory, app version, current model) and `message` rows whose `data` JSON
carries, for `role: assistant`, absolute `tokens` (input, output, reasoning,
cache read/write), the provider/model and `time.created`/`time.completed`.
Assistant message rows are updated in place when the response completes, so the
reader emits the delta between the stored and the observed counters — never the
absolute value twice. Studio claims are read from `part` rows whose `data`
carries a `studio_start_work` / `studio_claim_task` tool call.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from studio_client.usage.collectors.base import safe_model, safe_tag
from studio_client.usage.local.base import (
    BilledTokens,
    Emission,
    EmissionSink,
    LocalSession,
    TaskClaim,
    UsageEvent,
    as_state,
    parse_timestamp,
    parse_uuid,
    safe_counter,
)

_WINDOW_OVERLAP_MS = 120_000
"""Assistant rows are updated after their first write; the overlap re-reads the
rows touched since the previous scan without trusting a strict watermark."""


def default_database() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


class OpenCodeLocalReader:
    collector_id = "studio-local-opencode"
    collector_version = "1.0.0"
    harness = "opencode"

    def __init__(self, database: Path | None = None) -> None:
        self.database = database or default_database()

    def sessions(self, since: datetime) -> list[LocalSession]:
        database = self.database
        if not database.is_file():
            return []
        try:
            mtime = datetime.fromtimestamp(database.stat().st_mtime, tz=since.tzinfo)
        except OSError:
            return []
        return [
            LocalSession(
                native_id="opencode-database",
                location=str(database),
                mtime=mtime,
                since=since,
            )
        ]

    def read(
        self, session: LocalSession, state: dict[str, Any], emit: EmissionSink
    ) -> dict[str, Any]:
        current = as_state(state)
        messages_state = as_state(current.get("messages"))
        claims_state = as_state(current.get("claims"))
        watermark = current.get("watermark_ms")
        watermark = watermark if isinstance(watermark, int) else 0
        floor = int(session.since.timestamp() * 1000) if session.since is not None else 0
        since_ms = max(floor, watermark - _WINDOW_OVERLAP_MS)
        try:
            connection = sqlite3.connect(
                f"{Path(session.location).resolve().as_uri()}?mode=ro", uri=True, timeout=5
            )
        except sqlite3.Error:
            return current
        try:
            connection.row_factory = sqlite3.Row
            items, version = self._collect(connection, since_ms, messages_state)
            items.extend(self._claims(connection, since_ms, claims_state))
        except sqlite3.Error:
            return current
        finally:
            connection.close()
        items.sort(key=lambda item: (item[0], 0 if isinstance(item[1], TaskClaim) else 1))
        newest = watermark
        for ts, item, message_id, tokens in items:
            newest = max(newest, int(ts.timestamp() * 1000))
            emit.emit(item)
            if message_id is not None and tokens is not None:
                messages_state[message_id] = {
                    "ts": ts.isoformat(),
                    **tokens.to_state(),
                }
        _prune(messages_state)
        return {
            "messages": messages_state,
            "claims": claims_state,
            "watermark_ms": newest,
            "harness_version": version or current.get("harness_version"),
        }

    def _collect(
        self,
        connection: sqlite3.Connection,
        since_ms: int,
        messages_state: dict[str, Any],
    ) -> tuple[list[tuple[datetime, Emission, str | None, BilledTokens | None]], str | None]:
        query = (
            "SELECT m.id AS id, m.session_id AS session_id, m.time_updated AS time_updated, "
            "m.data AS data, s.directory AS directory, s.version AS version "
            "FROM message m JOIN session s ON s.id = m.session_id "
            "WHERE json_extract(m.data, '$.role') = 'assistant' "
            "AND m.time_updated >= ? ORDER BY m.time_updated"
        )
        rows = connection.execute(query, (since_ms,)).fetchall()
        found: list[tuple[datetime, Emission, str | None, BilledTokens | None]] = []
        version: str | None = None
        for row in rows:
            if isinstance(row["version"], str):
                version = row["version"]
            try:
                data = json.loads(row["data"])
            except (TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            tokens = _assistant_tokens(data)
            if tokens is None:
                continue
            created = data.get("time")
            created = created if isinstance(created, dict) else {}
            ts = parse_timestamp(created.get("completed") or created.get("created"))
            if ts is None:
                ts = parse_timestamp(row["time_updated"])
            if ts is None:
                continue
            message_id = row["id"] if isinstance(row["id"], str) else None
            stored = messages_state.get(message_id) if message_id is not None else None
            previous = BilledTokens.from_state(stored)
            delta = tokens.delta(previous)
            if delta.total() is None or (delta.total() or 0) <= 0:
                continue
            directory = row["directory"] if isinstance(row["directory"], str) else None
            event = UsageEvent(
                ts=ts,
                model=safe_model(data.get("modelID")),
                provider=safe_tag(data.get("providerID")),
                tokens=delta,
                cwd=directory,
            )
            found.append((ts, event, message_id, tokens))
        return found, version

    def _claims(
        self,
        connection: sqlite3.Connection,
        since_ms: int,
        claims_state: dict[str, Any],
    ) -> list[tuple[datetime, Emission, str | None, BilledTokens | None]]:
        rows = connection.execute(
            "SELECT p.id AS id, p.session_id AS session_id, p.time_created AS time_created, "
            "p.data AS data FROM part p "
            "WHERE json_extract(p.data, '$.type') = 'tool' "
            "AND json_extract(p.data, '$.tool') LIKE '%studio%' "
            "AND p.time_created >= ? ORDER BY p.time_created",
            (since_ms,),
        ).fetchall()
        found: list[tuple[datetime, Emission, str | None, BilledTokens | None]] = []
        for row in rows:
            try:
                data = json.loads(row["data"])
            except (TypeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            tool = data.get("tool")
            if not isinstance(tool, str):
                continue
            if "studio_start_work" not in tool and "studio_claim_task" not in tool:
                continue
            state = data.get("state")
            state = state if isinstance(state, dict) else {}
            arguments = state.get("input")
            arguments = arguments if isinstance(arguments, dict) else {}
            project_id = parse_uuid(arguments.get("project_id"))
            task_id = parse_uuid(arguments.get("task_id"))
            if project_id is None or task_id is None:
                continue
            ts = parse_timestamp(row["time_created"])
            if ts is None:
                continue
            session_id = row["session_id"] if isinstance(row["session_id"], str) else None
            fingerprint = f"{project_id}:{task_id}:{ts.isoformat()}"
            if session_id is not None and claims_state.get(session_id) == fingerprint:
                continue
            if session_id is not None:
                claims_state[session_id] = fingerprint
            found.append((ts, TaskClaim(ts=ts, project_id=project_id, task_id=task_id), None, None))
        return found


def _assistant_tokens(data: dict[str, Any]) -> BilledTokens | None:
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    cache = tokens.get("cache")
    cache = cache if isinstance(cache, dict) else {}
    return BilledTokens(
        input=safe_counter(tokens.get("input")),
        output=_sum(safe_counter(tokens.get("output")), safe_counter(tokens.get("reasoning"))),
        cache_read=safe_counter(cache.get("read")),
        cache_write=safe_counter(cache.get("write")),
    )


def _sum(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)


_MAX_STATE_MESSAGES = 20_000


def _prune(messages_state: dict[str, Any]) -> None:
    if len(messages_state) <= _MAX_STATE_MESSAGES:
        return
    ordered = sorted(
        messages_state.items(),
        key=lambda item: str(item[1].get("ts")) if isinstance(item[1], dict) else "",
    )
    for key, _ in ordered[: len(messages_state) - _MAX_STATE_MESSAGES]:
        messages_state.pop(key, None)
