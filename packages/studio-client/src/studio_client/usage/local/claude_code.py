"""Claude Code desktop/CLI transcripts (`~/.claude/projects/*/*.jsonl`).

Certified against the transcript written by Claude Code 2.1.x: one JSON object
per line, `type: assistant` entries carrying `message.usage` (input, output and
the disjoint cache creation/read counters), `message.model`, `timestamp`,
`cwd`, `version` and the session's `sessionId`. The same assistant message can
be written several times with a fresh line `uuid`; only the last form of a
`message.id` is counted once.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from studio_client.usage.collectors.base import safe_model, safe_tag
from studio_client.usage.local.base import (
    BilledTokens,
    EmissionSink,
    LocalSession,
    UsageEvent,
    as_state,
    claim_from_arguments,
    load_json_line,
    parse_timestamp,
    read_appended_lines,
    remember,
    safe_counter,
)


class ClaudeCodeLocalReader:
    collector_id = "studio-local-claude-code"
    collector_version = "1.0.0"
    harness = "claude-code"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".claude" / "projects"

    def sessions(self, since: datetime) -> list[LocalSession]:
        root = self.root
        if not root.is_dir():
            return []
        found: list[LocalSession] = []
        for path in root.glob("*/*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=since.tzinfo)
            except OSError:
                continue
            if mtime < since:
                continue
            found.append(
                LocalSession(native_id=path.stem, location=str(path), mtime=mtime, since=since)
            )
        return found

    def read(
        self, session: LocalSession, state: dict[str, Any], emit: EmissionSink
    ) -> dict[str, Any]:
        offset = state.get("offset")
        offset = offset if isinstance(offset, int) else 0
        recent = [value for value in as_state(state).get("recent", []) if isinstance(value, str)]
        harness_version = state.get("harness_version")
        new_offset, lines = read_appended_lines(Path(session.location), offset)
        for line in lines:
            doc = load_json_line(line)
            if doc is None or doc.get("type") != "assistant":
                continue
            version = safe_tag(doc.get("version"))
            if version is not None:
                harness_version = version
            ts = parse_timestamp(doc.get("timestamp"))
            if ts is None:
                continue
            message = doc.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name")
                    if not isinstance(name, str) or "studio_" not in name:
                        continue
                    claim = claim_from_arguments(ts, block.get("input"))
                    if claim is not None:
                        emit.emit(claim)
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            message_id = message.get("id")
            message_id = message_id if isinstance(message_id, str) else None
            if not remember(recent, message_id):
                continue
            tokens = BilledTokens(
                input=safe_counter(usage.get("input_tokens")),
                output=safe_counter(usage.get("output_tokens")),
                cache_read=safe_counter(usage.get("cache_read_input_tokens")),
                cache_write=safe_counter(usage.get("cache_creation_input_tokens")),
            )
            if tokens.total() is None:
                continue
            cwd = doc.get("cwd")
            emit.emit(
                UsageEvent(
                    ts=ts,
                    model=safe_model(message.get("model")),
                    provider=None,
                    tokens=tokens,
                    cwd=cwd if isinstance(cwd, str) else None,
                )
            )
        return {
            "offset": new_offset,
            "recent": recent,
            "harness_version": harness_version,
        }
