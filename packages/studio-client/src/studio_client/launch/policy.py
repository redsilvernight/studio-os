from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from studio_contracts.task_launch import TaskLaunch, TaskLaunchReasonCode

from studio_client.capabilities import registered_project_ids
from studio_client.config import ClientConfig


@dataclass(frozen=True)
class LaunchPolicy:
    """Machine-local launch policy. Default deny: no opt-in, no registered
    project or no allowed harness means every launch is refused."""

    opt_in: bool
    project_ids: frozenset[UUID]
    allowed_harnesses: frozenset[str]
    max_concurrent: int

    @classmethod
    def from_config(cls, config: ClientConfig) -> LaunchPolicy:
        return cls(
            opt_in=config.launch_opt_in,
            project_ids=frozenset(registered_project_ids(config)),
            allowed_harnesses=frozenset(config.launch_allowed_harnesses),
            max_concurrent=config.max_concurrent_launches,
        )


def evaluate_launch(
    policy: LaunchPolicy, launch: TaskLaunch, *, running: int
) -> TaskLaunchReasonCode:
    """First refusal reason, or `NONE` when the launch may be accepted.
    `running` counts launches already accepted/preparing/running here."""
    if not policy.opt_in:
        return TaskLaunchReasonCode.NOT_OPTED_IN
    if launch.project_id not in policy.project_ids:
        return TaskLaunchReasonCode.PROJECT_NOT_REGISTERED
    if launch.harness_id not in policy.allowed_harnesses:
        return TaskLaunchReasonCode.HARNESS_NOT_ALLOWED
    if running >= policy.max_concurrent:
        return TaskLaunchReasonCode.CAPACITY_REACHED
    return TaskLaunchReasonCode.NONE
