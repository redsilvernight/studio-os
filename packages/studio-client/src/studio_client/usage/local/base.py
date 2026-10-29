"""Agnostic local usage collection (P03 extension, DEC-0197 lineage).

A harness that ran outside a Mission Control launch never reaches
`LaunchUsageRecorder`: the desktop apps of Claude Code, Codex and OpenCode keep
their own session stores instead. A local reader parses those stores, read-only,
and turns them into ordered `UsageEvent`/`TaskClaim` emissions. Attribution is
harness-agnostic: a task is claimed by the `studio_start_work` /
`studio_claim_task` call the agent recorded in its own transcript, whatever the
tool that recorded it.

Nothing here copies conversation content or credentials: only counters,
timestamps, the model id and the working directory of the session.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

MAX_APPEND_BYTES = 8 * 1024 * 1024
"""Bound on the bytes one scan reads from a single transcript: a 70 MiB
transcript is absorbed over several scans instead of stalling the daemon."""

RECENT_IDS = 200
"""Bound on the per-session ring of already-counted message ids."""


@dataclass(frozen=True)
class BilledTokens:
    """Token counters as the harness reports them, before ledger normalisation.

    `input` excludes cached and cache-write tokens, so the total of one response
    is `input + cache_write + cache_read + output` whatever the harness's own
    convention (`included_in_input` is folded back by each reader)."""

    input: int | None = None
    output: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None

    def total(self) -> int | None:
        parts = [self.input, self.output, self.cache_read, self.cache_write]
        if all(part is None for part in parts):
            return None
        return sum(part or 0 for part in parts)

    def delta(self, previous: BilledTokens) -> BilledTokens:
        def diff(new: int | None, old: int | None) -> int | None:
            if new is None:
                return None
            return new - (old or 0)

        return BilledTokens(
            input=diff(self.input, previous.input),
            output=diff(self.output, previous.output),
            cache_read=diff(self.cache_read, previous.cache_read),
            cache_write=diff(self.cache_write, previous.cache_write),
        )

    def to_state(self) -> dict[str, int | None]:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
        }

    @classmethod
    def from_state(cls, value: object) -> BilledTokens:
        if not isinstance(value, dict):
            return cls()
        return cls(
            input=_as_int(value.get("input")),
            output=_as_int(value.get("output")),
            cache_read=_as_int(value.get("cache_read")),
            cache_write=_as_int(value.get("cache_write")),
        )


@dataclass(frozen=True)
class UsageEvent:
    """One measured slice of a local session, in the harness's order."""

    ts: datetime
    model: str | None
    provider: str | None
    tokens: BilledTokens
    cwd: str | None = None


@dataclass(frozen=True)
class TaskClaim:
    """A task the session declared it was working on, at `ts`."""

    ts: datetime
    project_id: UUID
    task_id: UUID


Emission = UsageEvent | TaskClaim


class EmissionSink(Protocol):
    def emit(self, item: Emission) -> None: ...


@dataclass(frozen=True)
class LocalSession:
    """One discoverable session store entry (a transcript file, a database)."""

    native_id: str
    location: str
    mtime: datetime
    since: datetime | None = None


class LocalUsageReader(Protocol):
    """Read-only, incremental reader of one harness's local session store."""

    collector_id: str
    collector_version: str
    harness: str

    def sessions(self, since: datetime) -> list[LocalSession]: ...

    def read(
        self, session: LocalSession, state: dict[str, Any], emit: EmissionSink
    ) -> dict[str, Any]: ...


def read_appended_lines(path: Path, offset: int) -> tuple[int, list[str]]:
    """Complete lines appended since `offset`; a trailing partial line is left
    for the next scan, and a single scan never absorbs more than
    `MAX_APPEND_BYTES`."""
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(MAX_APPEND_BYTES)
    except OSError:
        return offset, []
    end = data.rfind(b"\n")
    if end < 0:
        return offset, []
    consumed = data[: end + 1]
    lines = [line.decode("utf-8", "replace") for line in consumed.splitlines() if line.strip()]
    return offset + len(consumed), lines


def parse_timestamp(value: object) -> datetime | None:
    """Aware UTC timestamp from an ISO string or an epoch in seconds/millis."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 100_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


CLAIM_TOOL_NAMES = ("studio_start_work", "studio_claim_task")

_UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_TASK_ID_RE = re.compile(rf"task_id\"?\s*:\s*[\"']?({_UUID_PATTERN})")
_PROJECT_ID_RE = re.compile(rf"project_id\"?\s*:\s*[\"']?({_UUID_PATTERN})")


def mentions_claim_tool(text: str) -> bool:
    return any(name in text for name in CLAIM_TOOL_NAMES)


def claim_from_arguments(ts: datetime, arguments: object) -> TaskClaim | None:
    """A Studio task claim from a tool call's arguments (dict or JSON string)."""
    if isinstance(arguments, str):
        try:
            decoded: object = json.loads(arguments)
        except ValueError:
            return claim_from_text(ts, arguments)
        if isinstance(decoded, dict):
            return claim_from_arguments(ts, decoded)
        return None
    if isinstance(arguments, dict):
        project_id = parse_uuid(arguments.get("project_id"))
        task_id = parse_uuid(arguments.get("task_id"))
        if project_id is not None and task_id is not None:
            return TaskClaim(ts=ts, project_id=project_id, task_id=task_id)
    return None


def claim_from_text(ts: datetime, text: str) -> TaskClaim | None:
    """A Studio task claim from free-form code (Codex `exec` source) where the
    call arguments are an unquoted-key object literal."""
    if not mentions_claim_tool(text):
        return None
    task = _TASK_ID_RE.search(text)
    project = _PROJECT_ID_RE.search(text)
    if task is None or project is None:
        return None
    task_id = parse_uuid(task.group(1))
    project_id = parse_uuid(project.group(1))
    if task_id is None or project_id is None:
        return None
    return TaskClaim(ts=ts, project_id=project_id, task_id=task_id)


def load_json_line(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def remember(recent: list[str], item: str | None, limit: int = RECENT_IDS) -> bool:
    """Add `item` to the bounded ring; False when it was already counted."""
    if not item:
        return True
    if item in recent:
        return False
    recent.append(item)
    overflow = len(recent) - limit
    if overflow > 0:
        del recent[:overflow]
    return True


def as_state(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def safe_counter(value: object) -> int | None:
    return _as_int(value)
