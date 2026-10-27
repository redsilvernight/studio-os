"""`TaskLaunch` contract (AIB R2, additive): a typed request to start a task
on a target machine with a given harness and agent.

A launch is data, never a command: it carries ids and stable keys only, so
no shell line, argument, path or environment value is representable. The
requester creates and cancels; the target machine alone reports execution
(`accepted` -> `preparing` -> `running` -> terminal); the server alone
expires. The machine pulls the launches that target it (dedicated poll
endpoint) and applies its own local policy before accepting.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from studio_contracts.auth import MachineStatus
from studio_contracts.bootstrap import HarnessId
from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel
from studio_contracts.profiles import LaunchProfilePin
from studio_contracts.task_launch_replay import TaskLaunchReplayBasis, TaskLaunchReplayConfirmation
from studio_contracts.tasks import TaskStatus

LAUNCH_DEFAULT_TTL_SECONDS = 7200
"""Default expiry (task 63a909ea): 2 h — 15 min killed real work sessions
mid-run. Still bounded by LAUNCH_MAX_TTL_SECONDS; see TECH/02."""
LAUNCH_MAX_TTL_SECONDS = 86400
LAUNCH_MAX_OUTPUT_CHARS = 4000
LAUNCH_POLL_MAX = 20

StableKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
"""Library stable key: lowercase token, no separator, whitespace or drive
letter, so a path or a command line cannot be represented."""


class TaskLaunchStatus(StrEnum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TaskLaunchActor(StrEnum):
    """Who may drive a transition: the requester, the target machine, or the
    server itself (expiry)."""

    REQUESTER = "requester"
    MACHINE = "machine"
    SERVER = "server"


class TaskLaunchReasonCode(StrEnum):
    """Closed vocabulary: a reason is a code, never free text, so a machine
    or a requester cannot smuggle instructions through it."""

    NONE = "none"
    NOT_OPTED_IN = "not_opted_in"
    PROJECT_NOT_REGISTERED = "project_not_registered"
    HARNESS_NOT_ALLOWED = "harness_not_allowed"
    HARNESS_NOT_FOUND = "harness_not_found"
    AGENT_NOT_FOUND = "agent_not_found"
    CAPACITY_REACHED = "capacity_reached"
    PREPARATION_FAILED = "preparation_failed"
    HARNESS_EXITED = "harness_exited"
    CANCELLED_BY_REQUESTER = "cancelled_by_requester"
    EXPIRED_UNPULLED = "expired_unpulled"
    EXPIRED_TIMEOUT = "expired_timeout"


TERMINAL_STATUSES: frozenset[TaskLaunchStatus] = frozenset(
    {
        TaskLaunchStatus.SUCCEEDED,
        TaskLaunchStatus.FAILED,
        TaskLaunchStatus.CANCELLED,
        TaskLaunchStatus.REJECTED,
        TaskLaunchStatus.EXPIRED,
    }
)

# (from, to) -> actor allowed to drive it. Any other pair is refused
# (`409 invalid_launch_transition`); a wrong actor is `403`.
ALLOWED_TRANSITIONS: dict[tuple[TaskLaunchStatus, TaskLaunchStatus], TaskLaunchActor] = {
    (TaskLaunchStatus.REQUESTED, TaskLaunchStatus.ACCEPTED): TaskLaunchActor.MACHINE,
    (TaskLaunchStatus.REQUESTED, TaskLaunchStatus.REJECTED): TaskLaunchActor.MACHINE,
    (TaskLaunchStatus.REQUESTED, TaskLaunchStatus.CANCELLED): TaskLaunchActor.REQUESTER,
    (TaskLaunchStatus.REQUESTED, TaskLaunchStatus.EXPIRED): TaskLaunchActor.SERVER,
    (TaskLaunchStatus.ACCEPTED, TaskLaunchStatus.PREPARING): TaskLaunchActor.MACHINE,
    (TaskLaunchStatus.ACCEPTED, TaskLaunchStatus.FAILED): TaskLaunchActor.MACHINE,
    (TaskLaunchStatus.ACCEPTED, TaskLaunchStatus.CANCELLED): TaskLaunchActor.REQUESTER,
    (TaskLaunchStatus.ACCEPTED, TaskLaunchStatus.EXPIRED): TaskLaunchActor.SERVER,
    (TaskLaunchStatus.PREPARING, TaskLaunchStatus.RUNNING): TaskLaunchActor.MACHINE,
    (TaskLaunchStatus.PREPARING, TaskLaunchStatus.FAILED): TaskLaunchActor.MACHINE,
    (TaskLaunchStatus.PREPARING, TaskLaunchStatus.CANCELLED): TaskLaunchActor.REQUESTER,
    (TaskLaunchStatus.PREPARING, TaskLaunchStatus.EXPIRED): TaskLaunchActor.SERVER,
    (TaskLaunchStatus.RUNNING, TaskLaunchStatus.SUCCEEDED): TaskLaunchActor.MACHINE,
    (TaskLaunchStatus.RUNNING, TaskLaunchStatus.FAILED): TaskLaunchActor.MACHINE,
    (TaskLaunchStatus.RUNNING, TaskLaunchStatus.CANCELLED): TaskLaunchActor.REQUESTER,
    (TaskLaunchStatus.RUNNING, TaskLaunchStatus.EXPIRED): TaskLaunchActor.SERVER,
}


class TaskLaunchCreate(IdempotentCreate):
    """Requester input. Ids and stable keys only: the model forbids unknown
    fields, so there is no field that could hold a command, argument, path or
    environment value. `agent_stable_key` and `expires_in_seconds` are
    optional; the server defaults the expiry. The `Idempotency-Key` header
    makes a retried POST return the original launch."""

    task_id: UUID
    machine_id: UUID
    harness_id: HarnessId
    agent_stable_key: StableKey | None = None
    profile_key: StableKey | None = None
    allow_production: bool = False
    expires_in_seconds: int = Field(
        default=LAUNCH_DEFAULT_TTL_SECONDS, ge=60, le=LAUNCH_MAX_TTL_SECONDS
    )


class TaskLaunch(VersionedModel):
    """Server-held launch. `status` changes only through the transitions in
    `ALLOWED_TRANSITIONS`, each carrying `expected_version`. `session_id` is
    set by the machine once the work session exists. `requested_by_user_id`
    is the owner-or-granted requester (AIB-J), fixed at creation.

    `profile` (additive) is the work-profile pin computed by the
    server at creation. It is omitted from the serialized form when absent, so
    an unprofiled launch reads exactly as before for an N-1 daemon; a profiled
    launch only targets a machine that reported `launch_profiles`."""

    id: UUID
    project_id: UUID
    task_id: UUID
    machine_id: UUID
    requested_by_user_id: UUID
    harness_id: HarnessId
    agent_stable_key: StableKey | None = None
    status: TaskLaunchStatus = TaskLaunchStatus.REQUESTED
    reason_code: TaskLaunchReasonCode = TaskLaunchReasonCode.NONE
    session_id: UUID | None = None
    output_excerpt: str | None = Field(default=None, max_length=LAUNCH_MAX_OUTPUT_CHARS)
    expires_at: datetime
    finished_at: datetime | None = None
    profile: LaunchProfilePin | None = Field(default=None, exclude_if=lambda v: v is None)
    allow_production: bool = False


class TaskLaunchProtocolStatus(StrEnum):
    """Whether the launched agent followed the Studio protocol, derived at
    read time from the launch's linked work session, never stored and never
    inferred from the exit code. `not_applicable`: the harness never ran
    (rejected, cancelled or expired before `running`). `awaiting`: the launch
    is live and its session is not closed yet. `unverified`: the launch is
    terminal without a linked session or with a session never closed — an
    exit code 0 alone lands here. `handed_off`: the linked session is closed,
    whatever the launch status, so a deferred terminal report or a
    `blocked`/`in_progress` handoff is never a failure. Never an approval:
    `handed_off` does not complete or review the task."""

    NOT_APPLICABLE = "not_applicable"
    AWAITING = "awaiting"
    UNVERIFIED = "unverified"
    HANDED_OFF = "handed_off"


class TaskLaunchProtocol(ContractModel):
    """Protocol proof of one launch. `task_status` is the task's current
    status, set only when `handed_off`."""

    status: TaskLaunchProtocolStatus
    session_id: UUID | None = None
    task_status: TaskStatus | None = None


class TaskLaunchRecoveryState(StrEnum):
    """Recovery verdict of one attempt (P02), derived at read time from the
    launch status and the target machine's presence — never stored, never
    reported by a machine. `failed`: the attempt ended `failed`.
    `offline_wip`: the attempt is `accepted`/`preparing`/`running` and its
    machine is `offline`, so work may still be in progress where nobody can
    reach it — not a failure, never retried implicitly. `stale`: the attempt
    can no longer progress on its own — `requested` on an `offline` machine,
    or closed `expired`. `ok`: nothing to recover (a live attempt on an
    answering machine, `succeeded`, `cancelled`, `rejected`)."""

    OK = "ok"
    STALE = "stale"
    OFFLINE_WIP = "offline_wip"
    FAILED = "failed"


class TaskLaunchRecoveryReason(StrEnum):
    """Closed vocabulary behind a recovery verdict, never free text."""

    NONE = "none"
    LAUNCH_FAILED = "launch_failed"
    LAUNCH_EXPIRED = "launch_expired"
    MACHINE_OFFLINE = "machine_offline"


class TaskLaunchRecovery(ContractModel):
    """Why an attempt reads the way it does (P02). `machine_status` is the
    target machine's derived presence; `stale_since` is when the attempt
    stopped progressing (machine last seen, or the attempt's expiry), `None`
    when there is nothing to recover. Recovery itself is always explicit: a
    retry creates a new attempt, the previous one is never rewritten."""

    state: TaskLaunchRecoveryState
    reason: TaskLaunchRecoveryReason = TaskLaunchRecoveryReason.NONE
    machine_status: MachineStatus
    stale_since: datetime | None = None


class TaskLaunchRetry(IdempotentCreate):
    """Explicit recovery input (P02): retry a terminal attempt as a new one.
    Only `expires_in_seconds` is settable — task, machine, harness and agent
    are inherited from the attempt it retries, so a retry can never quietly
    become a different job. The body is optional."""

    expires_in_seconds: int = Field(
        default=LAUNCH_DEFAULT_TTL_SECONDS, ge=60, le=LAUNCH_MAX_TTL_SECONDS
    )
    replay: TaskLaunchReplayConfirmation | None = None


class TaskLaunchView(TaskLaunch):
    """Read model of the project launch list (dashboard, MCP) and of a retry.
    `TaskLaunch` itself stays unchanged: daemons parse it strictly from the
    pending pull and the by-id read, so an N-1 daemon never sees `protocol`,
    `recovery` or the attempt chain. `attempt` starts at 1; a retry points at
    the attempt it replaces through `retry_of_launch_id` (P02, additive)."""

    protocol: TaskLaunchProtocol
    attempt: int = 1
    retry_of_launch_id: UUID | None = None
    recovery: TaskLaunchRecovery | None = None
    replay_basis: TaskLaunchReplayBasis | None = None


class TaskLaunchMachineReport(ContractModel):
    """Machine-only transition report. The server checks the caller is the
    launch's target machine and that `(current, status)` is an allowed
    machine transition. `output_excerpt` is bounded and redacted by the
    machine before sending."""

    expected_version: int
    status: TaskLaunchStatus
    reason_code: TaskLaunchReasonCode = TaskLaunchReasonCode.NONE
    session_id: UUID | None = None
    output_excerpt: str | None = Field(default=None, max_length=LAUNCH_MAX_OUTPUT_CHARS)


class TaskLaunchCancel(ContractModel):
    """Requester cancel: `409` on a terminal launch. The pending pull returns
    non-terminal launches only, so the target machine observes the cancellation
    by re-reading the launch by id and must stop the work."""

    expected_version: int


class TaskLaunchPull(ContractModel):
    """What the daemon pulls: non-terminal launches targeting its machine,
    oldest first, bounded. A pull never changes a launch."""

    items: list[TaskLaunch] = Field(default_factory=list, max_length=LAUNCH_POLL_MAX)


class TaskLaunchCredential(ContractModel):
    """Ephemeral bearer credential for the harness a launch starts (AIB P9,
    additive). Returned once to the target machine, bound to the launch's
    project, task and machine, valid until `expires_at` (never past the
    launch's own expiry) and void as soon as the launch is terminal. It opens
    only the launch allowlist of REST routes and MCP tools."""

    token: str
    expires_at: datetime
