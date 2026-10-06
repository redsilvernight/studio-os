"""Machine-side launch status reports, enqueued through the outbox (AIB R3).

The report endpoint is version-guarded and *not* idempotent, so a machine must
send `accepted` -> `preparing` -> `running` -> terminal in order, each with the
right `expected_version`. This reporter is the single place that derives both:
it counts the reports it has already enqueued per launch and adds that count to
the launch's version as pulled, so the chain stays coherent across a resume
(where the launch's server version is read fresh) and the outbox's creation
order guarantees the chain is never sent out of order.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from studio_contracts.task_launch import (
    TaskLaunch,
    TaskLaunchMachineReport,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)

from studio_client.outbox import OutboxStore


class LaunchReporter:
    def __init__(self, store: OutboxStore) -> None:
        self._store = store
        self._sent: dict[UUID, int] = {}

    def expected_version(self, launch: TaskLaunch) -> int:
        return launch.version + self._sent.get(launch.id, 0)

    def report(
        self,
        launch: TaskLaunch,
        status: TaskLaunchStatus,
        *,
        reason_code: TaskLaunchReasonCode = TaskLaunchReasonCode.NONE,
        session_id: UUID | None = None,
        output_excerpt: str | None = None,
    ) -> int:
        """Enqueue one machine report and return the `expected_version` used.
        The idempotency key is derived from (launch, expected_version), so a
        duplicate enqueue is ignored locally and a replayed chain reuses the
        same key rather than inventing a second row."""
        expected = self.expected_version(launch)
        report = TaskLaunchMachineReport(
            expected_version=expected,
            status=status,
            reason_code=reason_code,
            session_id=session_id,
            output_excerpt=output_excerpt,
        )
        key = uuid5(NAMESPACE_URL, f"studio:task-launch-report:{launch.id}:{expected}")
        self._store.enqueue_mutation(
            str(key),
            "task_launch_report",
            "POST",
            f"/api/v1/task-launches/{launch.id}/report",
            report.model_dump(mode="json"),
        )
        self._sent[launch.id] = self._sent.get(launch.id, 0) + 1
        return expected
