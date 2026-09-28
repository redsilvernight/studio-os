"""`studio_start_work` composite contract (L2, additive): start or resume
work on a task in one call — idempotent claim, session resume-or-create,
bounded project context — or, without a task, project context plus the
current roadmap step's unclaimed candidate tasks, claiming nothing (AIB-G).

HTTP canonical (`POST /api/v1/start-work`, DEC-0046) plus the MCP tool
`studio_start_work`. No new table, no new event type: this composes the
existing task-claim, session and `prepare_context` services in one call — not
a single database transaction (the composed services own their own commits),
so a mid-call failure converges on retry. `prepare_context` itself gains no
side effect (DEC-0080).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from studio_contracts.common import ContractModel, IdempotentCreate
from studio_contracts.project_context import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_CHARS,
    MAX_FILES,
    OBJECTIVE_MAX_CHARS,
    PreparedContext,
    Why,
)
from studio_contracts.sessions import WorkSession
from studio_contracts.tasks import Task, TaskStatus


class StartWorkRequest(IdempotentCreate):
    """Composite start-work input. `project_id` and `agent_id` are required:
    the agent must belong to the caller's own machine (`409 actor_not_owned`
    otherwise — same rule as `POST /ai-work`). `task_id` selects
    the mode: with it, claim (idempotent for the same machine) + resume or
    create the agent's open session on the task + scoped context; without
    it, context + candidates only, never a claim nor a session (AIB-G).
    `objective` defaults server-side (`reprendre la tâche <titre>` /
    `vue projet`) when omitted. `files` follows the `prepare_context`
    bounds (at most 20 cleaned paths); `limit`/`max_chars` are passed
    through to `prepare_context` unchanged."""

    project_id: UUID
    agent_id: UUID
    task_id: UUID | None = None
    objective: str | None = Field(default=None, max_length=OBJECTIVE_MAX_CHARS)
    agent_stable_key: str | None = None
    files: list[str] | None = Field(default=None, max_length=MAX_FILES)
    limit: int = DEFAULT_LIMIT
    max_chars: int = DEFAULT_MAX_CHARS


class StartWorkCandidate(ContractModel):
    """One unclaimed task a fresh start could pick up (no-task path only):
    compact by construction — id, title, status, plus the `why` relation that
    surfaced it (`active_roadmap` for the current step, `project_scope` for
    another unclaimed project task), never the description."""

    task_id: UUID
    title: str
    status: TaskStatus
    why: Why


class StartWorkResult(ContractModel):
    """One call, one replayable result — not a single database transaction:
    the composed services commit their own steps, so a partial failure
    converges on the next call. `task`/`session`
    are set only on the with-task path; `claimed` tells whether the task is
    now claimed by the caller's machine; `resumed` tells whether the
    session was resumed (`True`) or created (`False`) — meaningless without
    a task. `prepared_context` is present on every successful response
    (bounded); `candidates` only on the no-task path. Replaying the same `Idempotency-Key` with the
    same body returns the original result — never a second claim nor a
    second session; a different body is `409
    idempotency_key_payload_mismatch`."""

    task: Task | None = None
    session: WorkSession | None = None
    claimed: bool = False
    resumed: bool = False
    prepared_context: PreparedContext | None = None
    candidates: list[StartWorkCandidate] = []
