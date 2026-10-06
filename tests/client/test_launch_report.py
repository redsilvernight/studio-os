from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from studio_client.daemon.launch_report import LaunchReporter
from studio_client.outbox import OutboxStore
from studio_client.outbox.models import OutboxTable
from studio_client.outbox.store import connect
from studio_contracts.task_launch import (
    TaskLaunch,
    TaskLaunchReasonCode,
    TaskLaunchStatus,
)


def _launch(
    *, version: int = 1, status: TaskLaunchStatus = TaskLaunchStatus.ACCEPTED
) -> TaskLaunch:
    now = datetime.now(UTC)
    return TaskLaunch(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        version=version,
        project_id=uuid4(),
        task_id=uuid4(),
        machine_id=uuid4(),
        requested_by_user_id=uuid4(),
        harness_id="claude-code",
        status=status,
        expires_at=now + timedelta(minutes=15),
    )


def test_reporter_chains_expected_versions(tmp_path: Path) -> None:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    reporter = LaunchReporter(store)
    launch = _launch(version=5)

    assert reporter.report(launch, TaskLaunchStatus.PREPARING) == 5
    assert reporter.report(launch, TaskLaunchStatus.RUNNING) == 6
    assert reporter.report(launch, TaskLaunchStatus.SUCCEEDED, output_excerpt="done") == 7

    rows = store.list_pending(OutboxTable.MUTATIONS)
    assert [row.payload["expected_version"] for row in rows] == [5, 6, 7]
    assert [row.payload["status"] for row in rows] == ["preparing", "running", "succeeded"]
    assert rows[0].extra["path"] == f"/api/v1/task-launches/{launch.id}/report"
    assert rows[2].payload["output_excerpt"] == "done"


def test_reporter_counts_are_per_launch(tmp_path: Path) -> None:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    reporter = LaunchReporter(store)
    first, second = _launch(version=2), _launch(version=9)

    assert reporter.report(first, TaskLaunchStatus.PREPARING) == 2
    assert reporter.report(second, TaskLaunchStatus.PREPARING) == 9
    assert reporter.report(first, TaskLaunchStatus.RUNNING) == 3


def test_reporter_carries_the_reason_code(tmp_path: Path) -> None:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    reporter = LaunchReporter(store)
    launch = _launch()
    reporter.report(
        launch,
        TaskLaunchStatus.REJECTED,
        reason_code=TaskLaunchReasonCode.HARNESS_NOT_ALLOWED,
    )
    [row] = store.list_pending(OutboxTable.MUTATIONS)
    assert row.payload["reason_code"] == "harness_not_allowed"
