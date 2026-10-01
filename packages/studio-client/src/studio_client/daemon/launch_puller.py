from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from studio_contracts.task_launch import (
    TaskLaunch,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)

from studio_client.api_client import StudioApiClient
from studio_client.daemon.launch_policy import OWNED_STATUSES, LaunchPolicy
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.errors import StudioApiError

logger = logging.getLogger(__name__)

PolicyProvider = Callable[[], LaunchPolicy]


class LaunchPuller:
    """Pulls this machine's pending launches (AIB R3) and answers each new
    `requested` one through the local policy: `accepted`, or `rejected` with a
    closed reason code. Answers go through the shared `LaunchReporter`, so a
    flaky link never loses a decision and the report chain stays ordered.

    Only the decision is made here; preparing and running an accepted launch
    belongs to `LaunchExecutor`."""

    def __init__(
        self,
        client: StudioApiClient,
        machine_id: UUID,
        policy_provider: PolicyProvider,
        reporter: LaunchReporter,
    ) -> None:
        self._client = client
        self._machine_id = machine_id
        self._policy_provider = policy_provider
        self._reporter = reporter
        # Decisions already enqueued but possibly not yet visible server-side;
        # keeps capacity accounting and decisions stable across polls.
        self._decided: dict[UUID, TaskLaunchStatus] = {}

    async def poll(self) -> list[TaskLaunch]:
        """Returns the launches *accepted* during this pass — the ones this
        machine now owns and must execute. A server error is logged and
        swallowed: the next heartbeat retries."""
        try:
            pending = await self._client.pull_pending_launches(self._machine_id)
        except StudioApiError:
            logger.warning("launch pull failed", exc_info=True)
            return []
        live = {launch.id for launch in pending}
        self._decided = {key: value for key, value in self._decided.items() if key in live}

        policy = self._policy_provider()
        active = sum(
            1
            for launch in pending
            if launch.status in OWNED_STATUSES
            or self._decided.get(launch.id) is TaskLaunchStatus.ACCEPTED
        )
        accepted: list[TaskLaunch] = []
        for launch in pending:
            if launch.status is not TaskLaunchStatus.REQUESTED or launch.id in self._decided:
                continue
            reason = policy.evaluate(launch, active=active)
            if reason is TaskLaunchReasonCode.NONE:
                status = TaskLaunchStatus.ACCEPTED
                active += 1
                accepted.append(launch)
            else:
                status = TaskLaunchStatus.REJECTED
            self._reporter.report(launch, status, reason_code=reason)
            self._decided[launch.id] = status
        return accepted
