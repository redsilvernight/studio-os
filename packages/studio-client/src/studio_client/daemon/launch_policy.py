from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from studio_contracts.task_launch import TaskLaunch, TaskLaunchReasonCode, TaskLaunchStatus

from studio_client.capabilities import build_capabilities
from studio_client.config import ClientConfig
from studio_client.harness.base import HarnessContext
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
) -> LaunchPolicy:
    """Local launch gate from configuration plus live harness detection."""
    capabilities = build_capabilities(config, registry=registry, ctx=ctx)
    return LaunchPolicy(
        opt_in=config.launch_opt_in,
        project_ids=frozenset(capabilities.project_ids),
        allowed_harnesses=frozenset(config.launch_allowed_harnesses),
        detected_harnesses=frozenset(
            entry.harness_id for entry in capabilities.harnesses if entry.detected
        ),
        max_concurrent=config.max_concurrent_launches,
    )
