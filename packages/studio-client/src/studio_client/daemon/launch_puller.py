from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import NAMESPACE_URL, UUID, uuid5

from studio_contracts.task_launch import (
    TaskLaunch,
    TaskLaunchMachineReport,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)

from studio_client.api_client import StudioApiClient
from studio_client.daemon.launch_policy import OWNED_STATUSES, LaunchPolicy
from studio_client.errors import StudioApiError
from studio_client.outbox import OutboxStore

logger = logging.getLogger(__name__)

PolicyProvider = Callable[[], LaunchPolicy]


class LaunchPuller:
    """Pulls this machine's pending launches (AIB R3) and answers each new
    `requested` one through the local policy: `accepted`, or `rejected` with a
    closed reason code. Answers go through the outbox so a flaky link never
    loses a decision; the idempotency key is derived from (launch, status,
    version), so a replayed pull cannot enqueue a second answer.

    Only the decision is made here. Preparing and running an accepted launch
    belongs to later R3 slices; nothing is executed by this class."""

    def __init__(
        self,
        client: StudioApiClient,
        store: OutboxStore,
        machine_id: UUID,
        policy_provider: PolicyProvider,
    ) -> None:
        self._client = client
        self._store = store
        self._machine_id = machine_id
        self._policy_provider = policy_provider
        # Decisions already enqueued but possibly not yet visible server-side;
        # keeps capacity accounting and decisions stable across polls.
        self._decided: dict[UUID, TaskLaunchStatus] = {}

    async def poll(self) -> list[TaskLaunch]:
        """Returns the launches decided during this pass. A server error is
        logged and swallowed: the next heartbeat retries."""
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
        decided: list[TaskLaunch] = []
        for launch in pending:
            if launch.status is not TaskLaunchStatus.REQUESTED or launch.id in self._decided:
                continue
            reason = policy.evaluate(launch, active=active)
            if reason is TaskLaunchReasonCode.NONE:
                status = TaskLaunchStatus.ACCEPTED
                active += 1
            else:
                status = TaskLaunchStatus.REJECTED
            self._enqueue_report(launch, status, reason)
            self._decided[launch.id] = status
            decided.append(launch)
        return decided

    def _enqueue_report(
        self, launch: TaskLaunch, status: TaskLaunchStatus, reason: TaskLaunchReasonCode
    ) -> None:
        report = TaskLaunchMachineReport(
            expected_version=launch.version, status=status, reason_code=reason
        )
        key = uuid5(
            NAMESPACE_URL, f"studio:task-launch-report:{launch.id}:{status}:{launch.version}"
        )
        self._store.enqueue_mutation(
            str(key),
            "task_launch_report",
            "POST",
            f"/api/v1/task-launches/{launch.id}/report",
            report.model_dump(mode="json"),
        )
