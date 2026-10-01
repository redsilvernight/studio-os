from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from studio_contracts.task_launch import (
    TaskLaunch,
    TaskLaunchMachineReport,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)

from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.errors import StudioApiError
from studio_client.launch.policy import LaunchPolicy, evaluate_launch

logger = logging.getLogger(__name__)

ACTIVE_STATUSES: frozenset[TaskLaunchStatus] = frozenset(
    {TaskLaunchStatus.ACCEPTED, TaskLaunchStatus.PREPARING, TaskLaunchStatus.RUNNING}
)

AcceptedHandler = Callable[[TaskLaunch], Awaitable[None]]


@dataclass
class LaunchPoll:
    accepted: list[TaskLaunch] = field(default_factory=list)
    rejected: list[tuple[TaskLaunch, TaskLaunchReasonCode]] = field(default_factory=list)
    running: int = 0


class LaunchPuller:
    """Pulls this machine's pending launches and decides each `requested`
    one against the local policy, reporting `accepted` or `rejected` with a
    closed reason code. Occupancy is read from the server's view of this
    machine's non-terminal launches, so a restart cannot lose count. A
    stale-version or transport failure leaves the launch for the next poll."""

    def __init__(
        self,
        client: StudioApiClient,
        config: ClientConfig,
        *,
        on_accepted: AcceptedHandler | None = None,
    ) -> None:
        if config.machine_id is None:
            raise ValueError("ClientConfig.machine_id must be set to pull launches")
        self._client = client
        self._config = config
        self._machine_id = config.machine_id
        self._on_accepted = on_accepted
        self.running = 0

    async def poll(self) -> LaunchPoll:
        outcome = LaunchPoll()
        try:
            pending = await self._client.pull_pending_launches(self._machine_id)
        except StudioApiError:
            logger.warning("launch pull failed", exc_info=True)
            return outcome
        policy = LaunchPolicy.from_config(self._config)
        running = sum(1 for launch in pending.items if launch.status in ACTIVE_STATUSES)
        for launch in pending.items:
            if launch.status is not TaskLaunchStatus.REQUESTED:
                continue
            reason = evaluate_launch(policy, launch, running=running)
            refused = reason is not TaskLaunchReasonCode.NONE
            report = TaskLaunchMachineReport(
                expected_version=launch.version,
                status=TaskLaunchStatus.REJECTED if refused else TaskLaunchStatus.ACCEPTED,
                reason_code=reason,
            )
            try:
                updated = await self._client.report_launch(launch.id, report)
            except StudioApiError:
                logger.warning("launch report failed", exc_info=True)
                continue
            if refused:
                outcome.rejected.append((updated, reason))
                continue
            running += 1
            outcome.accepted.append(updated)
            if self._on_accepted is not None:
                await self._on_accepted(updated)
        outcome.running = running
        self.running = running
        return outcome
