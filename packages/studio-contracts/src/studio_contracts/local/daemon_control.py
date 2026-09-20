from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from studio_contracts.local.common import (
    ComponentId,
    ComponentState,
    CorrelationId,
    LocalContractModel,
    LocalError,
    LocalErrorCode,
    SemVer,
    Sha256Hex,
    UtcDatetime,
)
from studio_contracts.local.handshake import ProtocolVersion
from studio_contracts.local.identity import (
    IdentityBinding,
    ProfileRef,
    binding_mismatches,
    partition_key,
)


class DaemonRunState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RECOVERING = "recovering"
    CRASHED = "crashed"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"


DAEMON_STATE_AS_COMPONENT: dict[DaemonRunState, ComponentState] = {
    DaemonRunState.STOPPED: ComponentState.DISABLED,
    DaemonRunState.STARTING: ComponentState.STARTING,
    DaemonRunState.RUNNING: ComponentState.READY,
    DaemonRunState.STOPPING: ComponentState.STOPPING,
    DaemonRunState.RECOVERING: ComponentState.RECOVERING,
    DaemonRunState.CRASHED: ComponentState.ERROR,
    DaemonRunState.UNAVAILABLE: ComponentState.UNAVAILABLE,
    DaemonRunState.INCOMPATIBLE: ComponentState.INCOMPATIBLE,
}


class DaemonOwnership(StrEnum):
    DESKTOP_STARTED = "desktop_started"
    EXTERNAL = "external"


class DaemonAction(StrEnum):
    ATTACH = "attach"
    START = "start"
    STOP = "stop"
    STATUS = "status"
    RESTART = "restart"


class DaemonControlOutcome(StrEnum):
    OK = "ok"
    ALREADY_RUNNING = "already_running"
    NOT_RUNNING = "not_running"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"
    INCOMPATIBLE = "incompatible"
    IDENTITY_MISMATCH = "identity_mismatch"
    FAILED = "failed"


_OUTCOME_ERROR: dict[DaemonControlOutcome, LocalErrorCode] = {
    DaemonControlOutcome.ALREADY_RUNNING: LocalErrorCode.DAEMON_ALREADY_RUNNING,
    DaemonControlOutcome.UNAVAILABLE: LocalErrorCode.DAEMON_UNAVAILABLE,
    DaemonControlOutcome.INCOMPATIBLE: LocalErrorCode.PROTOCOL_INCOMPATIBLE,
    DaemonControlOutcome.IDENTITY_MISMATCH: LocalErrorCode.IDENTITY_MISMATCH,
}


def instance_lock_key(profile: ProfileRef) -> str:
    """Single-instance key: exactly one daemon per (server origin, profile) on a
    machine. A second `start` on the same key resolves to `already_running` and
    the caller attaches instead."""
    material = f"{profile.server_origin}\n{profile.profile_id}"
    return hashlib.sha256(material.encode()).hexdigest()


class DaemonInstanceRef(LocalContractModel):
    instance_id: UUID
    profile: ProfileRef
    lock_key: Sha256Hex
    pid: int | None = Field(default=None, ge=1)
    ownership: DaemonOwnership
    daemon_version: SemVer
    started_at: UtcDatetime

    @model_validator(mode="after")
    def _lock_key_matches_profile(self) -> Self:
        if self.lock_key != instance_lock_key(self.profile):
            raise ValueError("lock_key does not derive from the profile")
        return self


class OutboxSummary(LocalContractModel):
    """What the daemon exposes about its queue. `binding` is the identity the
    queued entries were created under; replay is refused when it does not match
    the active identity."""

    binding: IdentityBinding
    partition_key: Sha256Hex
    pending_count: int = Field(ge=0)
    oldest_pending_at: UtcDatetime | None = None
    replay_blocked: bool = False
    blocked_reason: LocalErrorCode | None = None

    @model_validator(mode="after")
    def _partition_and_block(self) -> Self:
        if self.partition_key != partition_key(self.binding):
            raise ValueError("partition_key does not derive from the binding")
        if self.replay_blocked != (self.blocked_reason is not None):
            raise ValueError("blocked_reason is set exactly when replay is blocked")
        return self


class CrashInfo(LocalContractModel):
    crashed_at: UtcDatetime
    exit_code: int | None = None
    recoveries_attempted: int = Field(ge=0, le=100)
    error: LocalError | None = None


class DaemonStatus(LocalContractModel):
    state: DaemonRunState
    instance: DaemonInstanceRef | None = None
    negotiated: ProtocolVersion | None = None
    outbox: OutboxSummary | None = None
    last_crash: CrashInfo | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        live = {DaemonRunState.RUNNING, DaemonRunState.RECOVERING, DaemonRunState.STOPPING}
        if self.state in live and self.instance is None:
            raise ValueError(f"state {self.state.value} requires an instance")
        if self.state is DaemonRunState.STOPPED and self.instance is not None:
            raise ValueError("a stopped daemon has no live instance")
        if self.state is DaemonRunState.CRASHED and self.last_crash is None:
            raise ValueError("a crashed daemon reports its crash")
        return self

    def as_component_state(self) -> ComponentState:
        return DAEMON_STATE_AS_COMPONENT[self.state]


class DaemonControlRequest(LocalContractModel):
    action: DaemonAction
    profile: ProfileRef
    expected_instance_id: UUID | None = None
    confirm_external: bool = False
    drain_outbox: bool = True
    timeout_ms: int = Field(default=10_000, ge=100, le=60_000)


class DaemonControlResult(LocalContractModel):
    action: DaemonAction
    outcome: DaemonControlOutcome
    status: DaemonStatus
    error: LocalError | None = None

    @model_validator(mode="after")
    def _error_matches_outcome(self) -> Self:
        expected = _OUTCOME_ERROR.get(self.outcome)
        if expected is None:
            if self.outcome is DaemonControlOutcome.FAILED and self.error is None:
                raise ValueError("a failed control action carries an error")
            return self
        if self.error is None or self.error.code is not expected:
            raise ValueError(f"outcome {self.outcome.value} requires error {expected.value}")
        if self.error.component is not ComponentId.DAEMON:
            raise ValueError("daemon control errors are reported by the daemon component")
        return self


class ReplayVerdict(StrEnum):
    ALLOW = "allow"
    REFUSE_IDENTITY_MISMATCH = "refuse_identity_mismatch"


class ReplayDecision(LocalContractModel):
    verdict: ReplayVerdict
    mismatched: list[str] = []
    error: LocalError | None = None


def decide_outbox_replay(
    entry: IdentityBinding, active: IdentityBinding, *, correlation_id: CorrelationId | None = None
) -> ReplayDecision:
    """Fail-closed replay gate: an entry never leaves the machine under a
    server, profile, machine, project or workspace other than its own."""
    mismatched = binding_mismatches(entry, active)
    if not mismatched:
        return ReplayDecision(verdict=ReplayVerdict.ALLOW)
    return ReplayDecision(
        verdict=ReplayVerdict.REFUSE_IDENTITY_MISMATCH,
        mismatched=mismatched,
        error=LocalError(
            code=LocalErrorCode.IDENTITY_MISMATCH,
            message="Queued work belongs to a different identity and was not replayed.",
            component=ComponentId.DAEMON,
            retryable=False,
            details={"mismatched": ",".join(mismatched)},
            correlation_id=correlation_id,
        ),
    )
