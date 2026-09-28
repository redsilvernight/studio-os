"""`studio_handoff` composite contract (L3, additive): close a work
session in one call — task status update (with `expected_version`),
release all claims for the task, log AI work (if `agent_id` provided),
end the session. HTTP canonical (`POST /api/v1/handoff`) plus MCP tool
`studio_handoff`. No new table, no new event type: composes existing
task-claim, AI work, and session services. Idempotent via
`Idempotency-Key` (same key returns the original result)."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from studio_contracts.common import ContractModel, IdempotentCreate
from studio_contracts.tasks import TaskStatus, TaskUpdate


class HandoffRequest(IdempotentCreate):
    """Composite handoff input. `project_id` and `session_id` are required.
    `expected_version` is the task version for optimistic concurrency on
    the status update (like `update_task`). `task_status` is optional:
    when provided, updates the task status (e.g. `completed`, `blocked`).
    `agent_id` + `summary` are optional: when both present, logs an AI
    work entry with the given status (default `completed`) linked to the
    session for traceability. `changed_files`/`tests_run` are passed
    through to the AI work entry. All composed steps are idempotent on
    their own; the `Idempotency-Key` covers the whole composite."""

    project_id: UUID
    session_id: UUID
    expected_version: int
    task_status: TaskUpdate | None = None
    agent_id: UUID | None = None
    summary: str | None = Field(default=None, max_length=2000)
    ai_work_status: str | None = Field(default=None, max_length=32)
    changed_files: list[str] | None = Field(default=None, max_length=100)
    tests_run: list[str] | None = Field(default=None, max_length=100)


class HandoffResult(ContractModel):
    """Compact result: ids + statuses only, never full descriptions.
    Replaying the same `Idempotency-Key` with the same body returns the
    original result — no second status update, no duplicate claim
    releases, no duplicate AI work entry, no second session end."""

    task_id: UUID
    task_status: TaskStatus
    task_version: int
    session_id: UUID
    released_claims: list[UUID]
    ai_work_id: UUID | None = None
