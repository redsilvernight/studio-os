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

from studio_contracts.bootstrap import HarnessId
from studio_contracts.common import ContractModel, IdempotentCreate, VersionedModel

LAUNCH_DEFAULT_TTL_SECONDS = 900
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
    expires_in_seconds: int = Field(
        default=LAUNCH_DEFAULT_TTL_SECONDS, ge=60, le=LAUNCH_MAX_TTL_SECONDS
    )


class TaskLaunch(VersionedModel):
    """Server-held launch. `status` changes only through the transitions in
    `ALLOWED_TRANSITIONS`, each carrying `expected_version`. `session_id` is
    set by the machine once the work session exists. `requested_by_user_id`
    is the owner-or-granted requester (AIB-J), fixed at creation."""

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
