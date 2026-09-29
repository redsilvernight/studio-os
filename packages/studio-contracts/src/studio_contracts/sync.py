"""`studio_sync` resynchronisation contract (C2, additive, DEC-0157): the
single pull point answering "what changed since my last sync that concerns
my work?", as a compact bounded answer.

HTTP canonical (`GET /api/v1/sync`, DEC-0046) plus the MCP tool
`studio_sync` (same contract, DEC-0046/DEC-0048: no version in the payload).
Read-only on business resources; the one write is the per-session `seq`
cursor, advanced by acknowledgement only (at-least-once delivery, replay
without effect) — unlike `prepare_context`, which stays side-effect free
(DEC-0080). A new session of a task inherits that task's handoff cursor.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from studio_contracts.common import ContractModel
from studio_contracts.coordination import CoordinationSignal

SYNC_DEFAULT_LIMIT = 50
SYNC_MAX_LIMIT = 200
SYNC_SCAN_CAP = 500

SyncWhy = Literal[
    "own_task",
    "decision",
    "claim_overlap",
    "roadmap_dependency",
    "coordination",
]

SyncItemKind = Literal["event", "claim"]


class SyncItem(ContractModel):
    """One compact sync element, ids only — never a task description nor
    any long text. `seq`/`event_type` are set on `event` items;
    `claim_id`/`resource_path` on `claim` items (live claim state, no `seq`).
    `why` names the deterministic filter branch that surfaced it."""

    kind: SyncItemKind
    why: SyncWhy
    seq: int | None = None
    event_type: str | None = None
    task_id: UUID | None = None
    claim_id: UUID | None = None
    resource_path: str | None = None
    coordination: CoordinationSignal | None = None


class SyncResult(ContractModel):
    """Bounded sync answer. `next_cursor` is the highest delivered `seq`
    (unchanged when nothing new); ack it on the next call to advance.
    `overflow` counts matched-but-unreturned items per `why` category;
    `resync` (scan truncated) refers to `prepare_context` for the full
    picture — raw history is never dumped. An empty answer serializes to
    well under 300 characters."""

    next_cursor: int
    items: list[SyncItem] = []
    overflow: dict[str, int] = {}
    resync: bool = False
