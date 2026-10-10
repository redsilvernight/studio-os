"""Mission Control read model (DEC-0196, P02-read-model).

A bounded, read-only projection of a project's executions built at read time
from existing sources only — TaskLaunch, WorkSession, AIWorkLog, resource
claims, machines and proposed decisions. Nothing here is persisted: no new
session entity, no parallel state. The server applies the truth table below
and returns a verdict plus the reason codes that produced it; clients display
the verdict and never re-derive it.

One `MissionRun` per TaskLaunch, plus one per WorkSession that no launch
references (manual sessions). Process end (launch status) and protocol
closure (session ended with a handoff entry) are reported separately
(DEC-0201): `exit_code == 0` alone never yields `done`.

Truth table, evaluated top to bottom, first match wins (verdict: reason):

1. launch `cancelled` -> cancelled: launch_cancelled
2. launch `failed`/`rejected`/`expired` -> failed: launch_failed/_rejected/_expired
3. AIWork `review_requested` on the session (on the task when no session)
   -> waiting_human: review_requested
4. proposed decision linked to the task -> waiting_human: decision_proposed
5. protocol `handed_off` -> done: handed_off
6. launch `succeeded`, no session -> needs_attention: process_exited_without_session
7. launch `succeeded`, session ended without handoff
   -> needs_attention: session_ended_without_handoff
8. launch `succeeded`, session open -> needs_attention: process_exited_session_open
9. session `expired`, or machine `offline` while launch/session open
   -> stale: session_expired / machine_offline
10. no launch, session ended without handoff
    -> needs_attention: session_ended_without_handoff
11. launch `requested`/`accepted`/`preparing` -> pending: launch_pending
12. otherwise (launch `running`, session `active`/`idle`)
    -> running: process_running / session_idle

`reasons` lists every matching row's reason (not only the winning one) so a
discordant state stays visible; the first entry is the winning row.
Expired claims are never counted (same filter as claims service).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from studio_contracts.ai_work import AIWorkStatus
from studio_contracts.auth import MachineStatus
from studio_contracts.common import ContractModel
from studio_contracts.sessions import SessionStatus
from studio_contracts.task_launch import TaskLaunchReasonCode, TaskLaunchStatus

MISSION_DEFAULT_LIMIT = 20
MISSION_MAX_LIMIT = 50


class MissionVerdict(StrEnum):
    """Additive-only: a client must tolerate an unknown verdict."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    NEEDS_ATTENTION = "needs_attention"
    STALE = "stale"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MissionReason(StrEnum):
    """Additive-only reason codes; one per truth-table row condition."""

    LAUNCH_CANCELLED = "launch_cancelled"
    LAUNCH_FAILED = "launch_failed"
    LAUNCH_REJECTED = "launch_rejected"
    LAUNCH_EXPIRED = "launch_expired"
    REVIEW_REQUESTED = "review_requested"
    DECISION_PROPOSED = "decision_proposed"
    HANDED_OFF = "handed_off"
    PROCESS_EXITED_WITHOUT_SESSION = "process_exited_without_session"
    SESSION_ENDED_WITHOUT_HANDOFF = "session_ended_without_handoff"
    PROCESS_EXITED_SESSION_OPEN = "process_exited_session_open"
    SESSION_EXPIRED = "session_expired"
    MACHINE_OFFLINE = "machine_offline"
    LAUNCH_PENDING = "launch_pending"
    PROCESS_RUNNING = "process_running"
    SESSION_IDLE = "session_idle"


class MissionProtocolState(StrEnum):
    """Protocol closure, distinct from the process result (DEC-0201).
    `handed_off`: session ended and a non-`started` AIWork entry is linked to
    it (what `studio_handoff` writes). `ended_without_handoff`: session ended,
    no such entry. `open`: session not ended. `missing`: no session."""

    OPEN = "open"
    HANDED_OFF = "handed_off"
    ENDED_WITHOUT_HANDOFF = "ended_without_handoff"
    MISSING = "missing"


class MissionDataGap(StrEnum):
    """Explicitly incomplete data — never filled with a fabricated value."""

    MACHINE_UNKNOWN = "machine_unknown"
    SESSION_NOT_FOUND = "session_not_found"
    TASK_NOT_FOUND = "task_not_found"


class MissionLaunchRef(ContractModel):
    id: UUID
    status: TaskLaunchStatus
    reason_code: TaskLaunchReasonCode
    harness_id: str
    created_at: datetime
    finished_at: datetime | None = None


class MissionSessionRef(ContractModel):
    id: UUID
    status: SessionStatus
    agent_id: UUID | None = None
    started_at: datetime
    ended_at: datetime | None = None
    last_activity_at: datetime | None = None


class MissionHandoffRef(ContractModel):
    ai_work_id: UUID
    status: AIWorkStatus
    summary: str = Field(max_length=280)
    completed_at: datetime | None = None


class MissionRun(ContractModel):
    run_id: UUID
    source: Literal["launch", "session"]
    task_id: UUID
    task_title: str | None = None
    task_status: str | None = None
    machine_id: UUID
    machine_status: MachineStatus | None = None
    launch: MissionLaunchRef | None = None
    session: MissionSessionRef | None = None
    handoff: MissionHandoffRef | None = None
    protocol_state: MissionProtocolState
    verdict: MissionVerdict
    reasons: list[MissionReason]
    active_claims: int = 0
    data_gaps: list[MissionDataGap] = Field(default_factory=list)
    updated_at: datetime


class MissionCounts(ContractModel):
    """Counts over every run in the window, not only the returned page."""

    by_verdict: dict[MissionVerdict, int]
    total: int


class ProjectMission(ContractModel):
    project_id: UUID
    generated_at: datetime
    window_hours: int
    runs: list[MissionRun]
    counts: MissionCounts
    next_cursor: str | None = None
    truncated: bool = False
