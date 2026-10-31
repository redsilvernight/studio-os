"""Whole-response budget for MCP tool answers.

`max_chars` historically bounded only the free text selected by
`prepare_context` / `sync`; identifiers, envelopes and the pretty-printed
JSON the MCP SDK emits (`indent=2`) came on top. The helpers below measure the
text actually sent to the model and trim, deterministically and from the
lowest-priority end, until it fits. Every trimmed unit is counted in
`trimmed_for_budget`, never silently dropped.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pydantic_core

HANDOFF_ACK_MAX_CHARS = 1_000
_TEXT_FLOOR = 80


def rendered_chars(payload: Any) -> int:
    return len(pydantic_core.to_json(payload, fallback=str, indent=2).decode())


def _count(payload: dict[str, Any], section: str) -> None:
    trimmed = payload.setdefault("trimmed_for_budget", {})
    trimmed[section] = trimmed.get(section, 0) + 1


def _fit(payload: dict[str, Any], max_chars: int, steps: list[Callable[[], bool]]) -> bool:
    while rendered_chars(payload) > max_chars:
        if not any(step() for step in steps):
            return False
    return True


def _shorten(holder: dict[str, Any] | None, key: str, flag: str | None = "truncated") -> bool:
    if not holder or not isinstance(holder.get(key), str) or not holder[key]:
        return False
    text: str = holder[key]
    if len(text) <= _TEXT_FLOOR:
        holder.pop(key)
    else:
        holder[key] = text[: len(text) // 2]
    if flag is not None:
        holder[flag] = True
    return True


def trim_sync_block(payload: dict[str, Any], block: dict[str, Any] | None) -> Callable[[], bool]:
    """One step evicting the last sync item: counted in `overflow`, and
    `next_cursor` stays below every evicted event so it is redelivered."""

    def step() -> bool:
        if not block or not block.get("items"):
            return False
        item = block["items"].pop()
        why = item.get("why") or "unknown"
        block.setdefault("overflow", {})
        block["overflow"][why] = block["overflow"].get(why, 0) + 1
        if item.get("seq") is not None:
            block["next_cursor"] = min(block["next_cursor"], item["seq"] - 1)
        _count(payload, "sync_items")
        return True

    return step


def fit_sync(result: dict[str, Any], max_chars: int) -> dict[str, Any]:
    payload = dict(result)
    _fit(payload, max_chars, [trim_sync_block(payload, payload)])
    payload.pop("trimmed_for_budget", None)
    return payload


def _evict_context(payload: dict[str, Any], context: dict[str, Any], section: str) -> bool:
    if section == "claims":
        items = (context.get("active_work") or {}).get("claims")
    else:
        items = context.get(section)
    if not items:
        return False
    items.pop()
    returned = context.setdefault("returned", {})
    if returned.get(section):
        returned[section] -= 1
    omitted = context.setdefault("omitted_for_budget", {})
    omitted[section] = omitted.get(section, 0) + 1
    _count(payload, section)
    return True


def _drop_context_key(payload: dict[str, Any], context: dict[str, Any], key: str) -> bool:
    if context.get(key) is None:
        return False
    context.pop(key)
    context.setdefault("returned", {}).pop(key, None)
    omitted = context.setdefault("omitted_for_budget", {})
    omitted[key] = omitted.get(key, 0) + 1
    _count(payload, key)
    return True


def _evict_list(payload: dict[str, Any], holder: dict[str, Any] | None, key: str) -> bool:
    if not holder or not holder.get(key):
        return False
    holder[key].pop()
    _count(payload, key)
    return True


def fit_start_work(result: dict[str, Any], max_chars: int) -> dict[str, Any]:
    payload = dict(result)
    context: dict[str, Any] = payload.get("prepared_context") or {}

    def ctx(section: str) -> Callable[[], bool]:
        return lambda: _evict_context(payload, context, section)

    steps: list[Callable[[], bool]] = [
        ctx("skills"),
        ctx("rules"),
        ctx("notes"),
        lambda: _drop_context_key(payload, context, "roadmap_overview"),
        ctx("ai_work"),
        ctx("related_tasks"),
        ctx("decisions"),
        lambda: _evict_list(payload, payload, "candidates"),
        ctx("claims"),
        lambda: _drop_context_key(payload, context, "roadmap"),
        trim_sync_block(payload, payload.get("sync")),
        lambda: _shorten(context.get("task"), "description"),
        lambda: _shorten(context.get("project"), "description"),
        lambda: _shorten(payload.get("task"), "description", flag=None),
    ]
    if _fit(payload, max_chars, steps):
        return payload
    return _minimal_start_work(payload)


def _minimal_start_work(payload: dict[str, Any]) -> dict[str, Any]:
    task = payload.get("task") or None
    session = payload.get("session") or None
    minimal: dict[str, Any] = {
        "claimed": payload.get("claimed", False),
        "resumed": payload.get("resumed", False),
        "task": ({key: task.get(key) for key in ("id", "status", "version")} if task else None),
        "session": {"id": session.get("id")} if session else None,
        "prepared_context": None,
        "candidates": [
            {"task_id": c.get("task_id")} for c in (payload.get("candidates") or [])[:3]
        ],
        "sync": None,
        "trimmed_for_budget": {
            **payload.get("trimmed_for_budget", {}),
            "prepared_context": 1,
        },
    }
    return minimal


def fit_roadmap(result: dict[str, Any], max_chars: int) -> dict[str, Any]:
    payload = dict(result)
    active: dict[str, Any] | None = payload.get("active")
    current: dict[str, Any] | None = (active or {}).get("current_step")

    def evict_roadmap() -> bool:
        if not payload.get("roadmaps"):
            return False
        payload["roadmaps"].pop()
        payload["omitted_for_budget"] = payload.get("omitted_for_budget", 0) + 1
        return True

    def shorten_step_text() -> bool:
        if active is None:
            return False
        for step in [current, *(active.get("upcoming_steps") or [])]:
            if step and _shorten(step, "objective"):
                return True
        return False

    steps: list[Callable[[], bool]] = [
        lambda: _evict_list(payload, payload, "pending_proposals"),
        evict_roadmap,
        lambda: _evict_list(payload, active, "upcoming_steps"),
        lambda: _evict_list(payload, current, "acceptance_criteria"),
        shorten_step_text,
        lambda: _evict_list(payload, current, "linked_task_ids"),
        lambda: _shorten(current, "title"),
    ]
    if _fit(payload, max_chars, steps):
        return payload
    return {
        "project_id": payload.get("project_id"),
        "roadmaps": [],
        "active": (
            {key: active.get(key) for key in ("roadmap_id", "status", "current_step_key")}
            if active
            else None
        ),
        "draft_pending": payload.get("draft_pending", 0),
        "pending_proposals": [],
        "omitted_for_budget": payload.get("omitted_for_budget", 0),
        "trimmed_for_budget": {**payload.get("trimmed_for_budget", {}), "active": 1},
    }


def handoff_ack(result: dict[str, Any]) -> dict[str, Any]:
    """Minimal `studio_handoff` acknowledgement: ids, statuses, counters and
    warnings — the full composite answer stays available with `verbose=true`."""
    block: dict[str, Any] = result.get("sync") or {}
    items: list[dict[str, Any]] = block.get("items") or []
    warnings: list[str] = []
    signals = sum(1 for item in items if item.get("coordination") is not None)
    if signals:
        warnings.append(f"coordination_signals_received:{signals}")
    if len(items) > signals:
        warnings.append(f"sync_items_acknowledged:{len(items) - signals}")
    overflow = sum((block.get("overflow") or {}).values())
    if overflow:
        warnings.append(f"sync_overflow:{overflow}")
    if block.get("resync"):
        warnings.append("sync_resync")
    ack: dict[str, Any] = {
        "task_id": result.get("task_id"),
        "task_status": result.get("task_status"),
        "task_version": result.get("task_version"),
        "session_id": result.get("session_id"),
        "released_claims": len(result.get("released_claims") or []),
        "handoff_cursor_seq": result.get("handoff_cursor_seq"),
        "ai_work_id": result.get("ai_work_id"),
        "coordination_event_id": result.get("coordination_event_id"),
    }
    if warnings:
        ack["warnings"] = warnings
    return ack
