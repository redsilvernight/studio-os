from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from studio_contracts.profiles import (
    LaunchProfilePin,
    MachinePolicy,
    ProfileEnforcementCode,
    ProfilePermission,
    effective_permissions,
)
from studio_contracts.task_launch import TaskLaunch, TaskLaunchReasonCode, TaskLaunchStatus

from studio_client.capabilities import build_capabilities
from studio_client.config import ClientConfig
from studio_client.harness.base import AccessMode, HarnessContext
from studio_client.harness.registry import HarnessRegistry

# Statuses in which this machine already owns the execution (it reported them).
OWNED_STATUSES: frozenset[TaskLaunchStatus] = frozenset(
    {TaskLaunchStatus.ACCEPTED, TaskLaunchStatus.PREPARING, TaskLaunchStatus.RUNNING}
)


@dataclass(frozen=True)
class LaunchPolicy:
    """Local, machine-side gate for a pulled launch (AIB R3). The server only
    records a request; this policy decides whether the machine honours it.
    Checks run in a fixed order so the refusal reason is deterministic."""

    opt_in: bool
    project_ids: frozenset[UUID]
    allowed_harnesses: frozenset[str]
    detected_harnesses: frozenset[str]
    max_concurrent: int

    def evaluate(self, launch: TaskLaunch, *, active: int) -> TaskLaunchReasonCode:
        """`NONE` = accept. `active` counts launches this machine already owns
        (including ones accepted earlier in the same pull)."""
        if not self.opt_in:
            return TaskLaunchReasonCode.NOT_OPTED_IN
        if launch.project_id not in self.project_ids:
            return TaskLaunchReasonCode.PROJECT_NOT_REGISTERED
        if launch.harness_id not in self.allowed_harnesses:
            return TaskLaunchReasonCode.HARNESS_NOT_ALLOWED
        if launch.harness_id not in self.detected_harnesses:
            return TaskLaunchReasonCode.HARNESS_NOT_FOUND
        if active >= self.max_concurrent:
            return TaskLaunchReasonCode.CAPACITY_REACHED
        return TaskLaunchReasonCode.NONE


def build_launch_policy(
    config: ClientConfig,
    *,
    registry: HarnessRegistry | None = None,
    ctx: HarnessContext | None = None,
    extra_project_ids: Iterable[UUID] = (),
) -> LaunchPolicy:
    """Local launch gate from configuration plus live harness detection.

    `extra_project_ids` mirrors `build_capabilities`: a project registered as a
    Desktop workspace is honoured here too, so the server's eligibility and this
    machine's own gate agree on what "registered" means."""
    capabilities = build_capabilities(
        config, registry=registry, ctx=ctx, extra_project_ids=extra_project_ids
    )
    return LaunchPolicy(
        opt_in=config.launch_opt_in,
        project_ids=frozenset(capabilities.project_ids),
        allowed_harnesses=frozenset(config.launch_allowed_harnesses),
        detected_harnesses=frozenset(
            entry.harness_id for entry in capabilities.harnesses if entry.detected
        ),
        max_concurrent=config.max_concurrent_launches,
    )


@dataclass(frozen=True)
class LaunchProfile:
    """A profiled launch as the machine sees it when the run starts (DEC-0198):
    the pin recorded at preview/admission, the pin recomputed now through the
    common resolver, and the permissions the profile asks for. It carries no
    authority: `enforce_profile` intersects it with the local policy."""

    expected: LaunchProfilePin
    resolved: LaunchProfilePin
    permissions: tuple[ProfilePermission, ...]


@dataclass(frozen=True)
class ProfileEnforcement:
    """Final local verdict: an effective access mode, or a closed refusal code
    with a short diagnostic made of ids and tokens only."""

    mode: AccessMode | None
    refusal: ProfileEnforcementCode | None = None
    diagnostic: str = ""

    @property
    def accepted(self) -> bool:
        return self.refusal is None


def _refuse(code: ProfileEnforcementCode, diagnostic: str) -> ProfileEnforcement:
    return ProfileEnforcement(mode=None, refusal=code, diagnostic=diagnostic)


def enforce_profile(
    profile: LaunchProfile | None,
    *,
    supported_modes: frozenset[AccessMode],
    policy: MachinePolicy,
) -> ProfileEnforcement:
    """Requested profile ∩ adapter guarantees ∩ local policy. A launch without
    a profile keeps the legacy coding mode, already gated by `LaunchPolicy`.
    Fails closed: never widens a mode, never runs a profile that changed since
    it was previewed, never grants what the machine does not."""
    if profile is None:
        if AccessMode.WORKSPACE_WRITE not in supported_modes:
            return _refuse("mode_unsupported", f"mode={AccessMode.WORKSPACE_WRITE.value}")
        return ProfileEnforcement(mode=AccessMode.WORKSPACE_WRITE)
    if profile.expected != profile.resolved:
        return _refuse(
            "profile_version_changed",
            f"profile={profile.resolved.stable_key} "
            f"expected={profile.expected.contract_version}:{profile.expected.digest[7:19]} "
            f"resolved={profile.resolved.contract_version}:{profile.resolved.digest[7:19]}",
        )
    if not policy.opt_in:
        return _refuse("machine_opt_in_off", "machine")
    decisions = effective_permissions(list(profile.permissions), policy)
    denied = [d.permission for d in decisions if not d.granted]
    if denied or "read" not in profile.permissions:
        missing = denied or ["read"]
        return _refuse("permission_denied", "denied=" + ",".join(missing))
    mode = AccessMode.WORKSPACE_WRITE if "write" in profile.permissions else AccessMode.READ_ONLY
    if mode not in supported_modes:
        code: ProfileEnforcementCode = (
            "read_only_unsupported" if mode is AccessMode.READ_ONLY else "mode_unsupported"
        )
        return _refuse(code, f"mode={mode.value}")
    return ProfileEnforcement(mode=mode)


RunDiagnostic = Literal["forbidden_operation", "start_work_not_observed", "handoff_not_observed"]

_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "studio-git-guard:",
    "permission denied",
    "has been denied",
    "not permitted",
    "read-only file system",
    "blocked by policy",
    "sandbox denied",
)


def run_diagnostics(output: str) -> tuple[RunDiagnostic, ...]:
    """What the run's own output shows, in fixed order: a refused or blocked
    operation, and whether the Studio protocol calls were observed. Never a
    success signal on its own: absence of a marker proves nothing."""
    lowered = output.lower()
    found: list[RunDiagnostic] = []
    if any(marker in lowered for marker in _FORBIDDEN_MARKERS):
        found.append("forbidden_operation")
    if "start_work" not in lowered:
        found.append("start_work_not_observed")
    if "handoff" not in lowered:
        found.append("handoff_not_observed")
    return tuple(found)
