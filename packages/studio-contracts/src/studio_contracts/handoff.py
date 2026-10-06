"""`studio_handoff` composite contract (L3, additive): close a work
session in one call — task status update (with `expected_version`),
release all claims for the task, log AI work (if `agent_id` provided),
end the session — plus (C4) a last bounded sync, the task handoff cursor
and an optional `coordination.handoff` signal. HTTP canonical (`POST /api/v1/handoff`) plus MCP tool
`studio_handoff`. No new table, no new event type: composes existing
task-claim, AI work, and session services. Idempotent via
`Idempotency-Key` (same key returns the original result)."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from studio_contracts.ai_work import AIWorkStatus
from studio_contracts.common import ContractModel, IdempotentCreate
from studio_contracts.coordination import COORDINATION_TEXT_MAX, CoordinationRefs
from studio_contracts.sync import SyncResult
from studio_contracts.tasks import TaskStatus, TaskUpdate


class HandoffCoordination(ContractModel):
    """Optional `coordination.handoff` signal (C4, additive)
    emitted on the handed-off task, delivered to its next session through
    `studio_sync`. The event id is derived from the session, so a replay
    never emits a second signal. `text` is quoted data for the recipient."""

    text: str = Field(min_length=1, max_length=COORDINATION_TEXT_MAX)
    refs: CoordinationRefs = Field(default_factory=CoordinationRefs)


class HandoffRequest(IdempotentCreate):
    """Composite handoff input. `project_id` and `session_id` are required.
    `expected_version` is the task version for optimistic concurrency on
    the status update (like `update_task`); required only when `task_status`
    is provided. `task_status` is optional:
    when provided, updates the task status (e.g. `completed`, `blocked`).
    `agent_id` + `summary` are optional: when both present, logs an AI
    work entry with the given status (default `completed`) linked to the
    session for traceability. `changed_files`/`tests_run` are passed
    through to the AI work entry. All composed steps are idempotent on
    their own; the `Idempotency-Key` covers the whole composite."""

    project_id: UUID
    session_id: UUID
    expected_version: int | None = None
    task_status: TaskUpdate | None = None
    agent_id: UUID | None = None
    summary: str | None = Field(default=None, max_length=2000)
    ai_work_status: AIWorkStatus | None = None
    changed_files: list[str] | None = Field(default=None, max_length=100)
    tests_run: list[str] | None = Field(default=None, max_length=100)
    coordination: HandoffCoordination | None = None


class HandoffResult(ContractModel):
    """Compact result: ids + statuses only, never full descriptions.
    Replaying the same `Idempotency-Key` with the same body returns the
    original result — no second status update, no duplicate claim
    releases, no duplicate AI work entry, no second session end. C4 adds:
    `sync` (last bounded `studio_sync` answer, acknowledged), the task's new
    `handoff_cursor_seq` that the next session inherits, and the emitted
    `coordination_event_id` when a `coordination` signal was requested."""

    task_id: UUID
    task_status: TaskStatus
    task_version: int
    session_id: UUID
    released_claims: list[UUID]
    ai_work_id: UUID | None = None
    sync: SyncResult | None = None
    handoff_cursor_seq: int | None = None
    coordination_event_id: UUID | None = None
