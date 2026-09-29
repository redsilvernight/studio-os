"""`studio_sync` (C2, additive, DEC-0157): the single resynchronisation
point — "what changed since my last sync that concerns my work?" — as a
compact bounded answer.

Read-only on business resources; the one write is the per-session `seq`
cursor, advanced by acknowledgement only (at-least-once delivery, replay
without effect) — unlike `prepare_context`, which stays side-effect free
(DEC-0080). A lookup by `agent_id` + `task_id` (no session) is stateless:
no cursor is persisted. Claims come from live state (derived expiry), never
from claim event types alone (DEC-0157 lesson from DEC-0051). Reads are
indexed on `seq` (`list_events_after`, `seq.asc()`); the roadmap branch
reuses the active roadmap's structural `depends_on`."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.coordination import CoordinationSignal
from studio_contracts.project_context import (
    DEFAULT_MAX_CHARS,
    MAX_FILES,
    MAX_MAX_CHARS,
    MAX_PATH_CHARS,
    MIN_MAX_CHARS,
)
from studio_contracts.roadmaps import RoadmapStatus
from studio_contracts.sync import (
    SYNC_DEFAULT_LIMIT,
    SYNC_MAX_LIMIT,
    SYNC_SCAN_CAP,
    SyncItem,
    SyncResult,
)

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import claims as claims_service
from studio_api.services import events as events_service
from studio_api.services import roadmaps as roadmaps_service
from studio_api.services import sessions as sessions_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    ensure_machine_owned,
)

_DECISION_EVENT_TYPES = frozenset(
    {
        "decision.proposed",
        "decision.created",
        "decision.accepted",
        "decision.superseded",
    }
)
_COORDINATION_PREFIX = "coordination."


def _invalid(message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_sync_input", "message": message},
    )


def _session_not_found(message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail={"error_code": "session_not_found", "message": message},
    )


def _signal(
    event_id: uuid.UUID, event_type: str, payload: dict[str, object]
) -> CoordinationSignal | None:
    """Quoted signal from a stored coordination payload; a malformed row is
    dropped rather than surfaced (defensive against pre-validation data)."""
    try:
        return CoordinationSignal.model_validate(
            {
                "event_id": event_id,
                "intent": event_type.removeprefix(_COORDINATION_PREFIX),
                "text": payload.get("text"),
                "refs": payload.get("refs") or {},
                "in_reply_to": payload.get("in_reply_to"),
                "from_session_id": payload.get("from_session_id"),
            }
        )
    except ValidationError:
        return None


async def _related_task_ids(
    session: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    my_task_id: uuid.UUID,
) -> set[uuid.UUID]:
    """Tasks linked to upstream/downstream steps of my task's steps, on the
    project's active roadmap only. Structural `depends_on`, transitive,
    deterministic; empty when no active roadmap or the task is unlinked."""
    summaries = await roadmaps_service.list_roadmaps(
        session, principal, project_id, RoadmapStatus.ACTIVE, 1
    )
    if not summaries:
        return set()
    detail = await roadmaps_service.get_roadmap(session, principal, summaries[0].id)
    steps = [step for phase in detail.phases for step in phase.steps]
    by_key = {step.key: step for step in steps}
    mine = {
        step.key for step in steps if any(link.task_id == my_task_id for link in step.linked_tasks)
    }
    if not mine:
        return set()
    upstream: set[str] = set()
    stack = [dep for key in mine for dep in by_key[key].depends_on if dep in by_key]
    while stack:
        key = stack.pop()
        if key in upstream or key in mine:
            continue
        upstream.add(key)
        stack.extend(dep for dep in by_key[key].depends_on if dep in by_key)
    children: dict[str, list[str]] = {}
    for step in steps:
        for dep in step.depends_on:
            if dep in by_key:
                children.setdefault(dep, []).append(step.key)
    downstream: set[str] = set()
    stack = [child for key in mine for child in children.get(key, [])]
    while stack:
        key = stack.pop()
        if key in downstream or key in mine:
            continue
        downstream.add(key)
        stack.extend(children.get(key, []))
    related = {link.task_id for key in upstream | downstream for link in by_key[key].linked_tasks}
    related.discard(my_task_id)
    return related


async def sync(
    session: AsyncSession,
    principal: Principal,
    *,
    session_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    ack: int | None = None,
    files: list[str] | None = None,
    limit: int = SYNC_DEFAULT_LIMIT,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> SyncResult:
    """Bounded resync for one session (or one agent + task, stateless).

    The cursor starts at `max(stored, ack)` and is persisted monotonically —
    a stale replay changes nothing. `next_cursor` is the highest delivered
    `seq` (unchanged when nothing is new); ack it next call to advance.
    Own-machine events are excluded; items are ids only, `seq` ascending,
    then live overlapping claims; the remainder surfaces as per-`why`
    `overflow` counters, and a truncated scan sets `resync` (see
    `prepare_context` for the full picture — raw history is never dumped).
    """
    if not 1 <= limit <= SYNC_MAX_LIMIT:
        raise _invalid(f"limit must be between 1 and {SYNC_MAX_LIMIT}")
    if not MIN_MAX_CHARS <= max_chars <= MAX_MAX_CHARS:
        raise _invalid(f"max_chars must be between {MIN_MAX_CHARS} and {MAX_MAX_CHARS}")
    clean_files = [(f or "").strip() for f in (files or []) if (f or "").strip()]
    if len(clean_files) > MAX_FILES:
        raise _invalid(f"at most {MAX_FILES} files")
    if any(len(f) > MAX_PATH_CHARS for f in clean_files):
        raise _invalid(f"each file must be at most {MAX_PATH_CHARS} characters")
    if ack is not None and ack < 0:
        raise _invalid("ack must be a non-negative seq")
    if session_id is None and (agent_id is None or task_id is None):
        raise _invalid("session_id or (agent_id and task_id) is required")

    work_session: WorkSessionModel | None = None
    if session_id is not None:
        work_session = await session.get(WorkSessionModel, session_id)
        if work_session is None or work_session.ended_at is not None:
            raise _session_not_found("unknown or ended session")
        task_id = work_session.task_id
    else:
        assert agent_id is not None and task_id is not None  # checked above

    # Project before ownership (DEC-0103 §8, same order as `end_session`):
    # a task of an inaccessible project answers the project 403, never an
    # ownership or actor error that would leak its existence.
    task = await tasks_service.read_task(session, principal, task_id)
    if task is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "not_found", "message": "task not found"},
        )
    project_id = task.project_id
    my_task_id = task.id

    if work_session is not None:
        ensure_machine_owned(principal, work_session.machine_id, "session", "sync")
    else:
        ensure_can_write(principal, "sync")
        agent = await session.get(AgentModel, agent_id)
        if agent is None or agent.machine_id != principal.machine.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "actor_not_owned",
                    "message": "agent_id must be an agent attached to the authenticated machine",
                },
            )

    stored = work_session.sync_cursor_seq if work_session is not None else None
    base = stored if stored is not None else 0
    effective = base if ack is None else max(base, ack)
    if work_session is not None:
        if effective != stored:
            await sessions_service.ack_sync_cursor(session, work_session.id, effective)
        await sessions_service.touch_session(session, work_session.id)

    related = await _related_task_ids(session, principal, project_id, my_task_id)
    scanned = await events_service.list_events_after(
        session, principal, project_id, effective, SYNC_SCAN_CAP
    )
    truncated = len(scanned) == SYNC_SCAN_CAP

    my_machine_id = principal.machine.id
    my_session_str = str(work_session.id) if work_session is not None else None
    matched: list[tuple[str, int, SyncItem]] = []
    for event in scanned:
        is_coordination = event.event_type.startswith(_COORDINATION_PREFIX)
        if (
            not is_coordination
            and event.machine_id is not None
            and event.machine_id == my_machine_id
        ):
            continue
        signal: CoordinationSignal | None = None
        if is_coordination:
            payload = event.payload or {}
            if my_session_str is not None and payload.get("from_session_id") == my_session_str:
                continue
            targets_me = str(payload.get("task_id")) == str(my_task_id)
            target_session = payload.get("session_id")
            if target_session is not None:
                targets_me = my_session_str is not None and str(target_session) == my_session_str
            if not targets_me:
                continue
            why = "coordination"
            signal = _signal(event.id, event.event_type, payload)
            if signal is None:
                continue
        elif event.event_type in _DECISION_EVENT_TYPES and event.task_id == my_task_id:
            why = "decision"
        elif event.task_id is not None and event.task_id == my_task_id:
            why = "own_task"
        elif event.task_id is not None and event.task_id in related:
            why = "roadmap_dependency"
        else:
            continue
        matched.append(
            (
                why,
                event.seq,
                SyncItem(
                    kind="event",
                    why=why,  # type: ignore[arg-type]
                    seq=event.seq,
                    event_type=event.event_type,
                    task_id=event.task_id,
                    coordination=signal,
                ),
            )
        )

    live = await claims_service.active_claims(session, project_id)
    mine_paths = [
        (claim.resource_path, claim.resource_type) for claim in live if claim.task_id == my_task_id
    ]
    for claim in sorted(live, key=lambda c: (c.resource_path, str(c.id))):
        if claim.task_id == my_task_id:
            continue
        overlaps = any(
            claims_service.paths_conflict(claim.resource_path, claim.resource_type, path, kind)
            for path, kind in mine_paths
        ) or any(
            claims_service.paths_conflict(claim.resource_path, claim.resource_type, path, "file")
            for path in clean_files
        )
        if not overlaps:
            continue
        matched.append(
            (
                "claim_overlap",
                0,
                SyncItem(
                    kind="claim",
                    why="claim_overlap",
                    task_id=claim.task_id,
                    claim_id=claim.id,
                    resource_path=claim.resource_path,
                ),
            )
        )

    items: list[SyncItem] = []
    overflow: dict[str, int] = {}
    chars = 0
    next_cursor = effective
    for why, _order, item in matched:
        cost = len(item.model_dump_json())
        if len(items) >= limit or chars + cost > max_chars:
            overflow[why] = overflow.get(why, 0) + 1
            continue
        items.append(item)
        chars += cost
        if item.seq is not None and item.seq > next_cursor:
            next_cursor = item.seq
    return SyncResult(
        next_cursor=next_cursor,
        items=items,
        overflow=overflow,
        resync=truncated,
    )
