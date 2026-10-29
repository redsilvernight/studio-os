"""Codex desktop/CLI rollouts (`~/.codex/sessions/AAAA/MM/JJ/*.jsonl`).

Certified against the rollout format written by Codex 0.16x: `session_meta`
(cwd, session id, cli version, provider), `turn_context` (current model and
cwd), `token_usage_record` (per-response `usage` with `response_id`,
`input_tokens` already including the cached and cache-write subsets) and
`response_item`/`custom_tool_call` where a Studio MCP call is executed through
the code-mode `exec` tool (unquoted-key object literal).
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
    claim_from_text,
    load_json_line,
    parse_timestamp,
    read_appended_lines,
    remember,
    safe_counter,
)


class CodexLocalReader:
    collector_id = "studio-local-codex"
    collector_version = "1.0.0"
    harness = "codex"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".codex" / "sessions"

    def sessions(self, since: datetime) -> list[LocalSession]:
        root = self.root
        if not root.is_dir():
            return []
        found: list[LocalSession] = []
        for path in root.glob("**/*.jsonl"):
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
        current = as_state(state)
        offset = current.get("offset")
        offset = offset if isinstance(offset, int) else 0
        recent = [value for value in current.get("recent", []) if isinstance(value, str)]
        model = safe_model(current.get("model"))
        provider = safe_tag(current.get("provider"))
        harness_version = safe_tag(current.get("harness_version"))
        cwd = current.get("cwd") if isinstance(current.get("cwd"), str) else None
        new_offset, lines = read_appended_lines(Path(session.location), offset)
        for line in lines:
            doc = load_json_line(line)
            if doc is None:
                continue
            kind = doc.get("type")
            payload = doc.get("payload")
            if not isinstance(payload, dict):
                continue
            if kind == "session_meta":
                harness_version = safe_tag(payload.get("cli_version")) or harness_version
                provider = safe_tag(payload.get("model_provider")) or provider
                if isinstance(payload.get("cwd"), str):
                    cwd = payload["cwd"]
                continue
            if kind == "turn_context":
                model = safe_model(payload.get("model")) or model
                if isinstance(payload.get("cwd"), str):
                    cwd = payload["cwd"]
                continue
            if kind == "response_item":
                self._read_tool_call(doc, payload, emit)
                continue
            if kind != "token_usage_record":
                continue
            usage = payload.get("usage")
            if not isinstance(usage, dict):
                continue
            ts = parse_timestamp(doc.get("timestamp"))
            if ts is None:
                continue
            response_id = payload.get("response_id")
            response_id = response_id if isinstance(response_id, str) else None
            if not remember(recent, response_id):
                continue
            input_total = safe_counter(usage.get("input_tokens"))
            cache_read = safe_counter(usage.get("cached_input_tokens"))
            cache_write = safe_counter(usage.get("cache_write_input_tokens"))
            normal = None
            if input_total is not None:
                normal = max(0, input_total - (cache_read or 0) - (cache_write or 0))
            tokens = BilledTokens(
                input=normal,
                output=safe_counter(usage.get("output_tokens")),
                cache_read=cache_read,
                cache_write=cache_write,
            )
            if tokens.total() is None:
                continue
            emit.emit(UsageEvent(ts=ts, model=model, provider=provider, tokens=tokens, cwd=cwd))
        return {
            "offset": new_offset,
            "recent": recent,
            "model": model,
            "provider": provider,
            "harness_version": harness_version,
            "cwd": cwd,
        }

    def _read_tool_call(
        self, doc: dict[str, Any], payload: dict[str, Any], emit: EmissionSink
    ) -> None:
        if payload.get("type") not in {"custom_tool_call", "function_call"}:
            return
        ts = parse_timestamp(doc.get("timestamp"))
        if ts is None:
            return
        arguments = payload.get("input")
        if arguments is None:
            arguments = payload.get("arguments")
        claim = claim_from_arguments(ts, arguments)
        if claim is None:
            if isinstance(arguments, str):
                claim = claim_from_text(ts, arguments)
            if claim is None:
                return
        emit.emit(claim)
