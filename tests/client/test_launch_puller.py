from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from studio_client.daemon.launch_policy import LaunchPolicy
from studio_client.daemon.launch_puller import LaunchPuller
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.errors import StudioApiError
from studio_client.outbox import OutboxStore
from studio_client.outbox.models import OutboxTable
from studio_client.outbox.store import connect
from studio_contracts.task_launch import TaskLaunch, TaskLaunchReasonCode, TaskLaunchStatus

PROJECT = uuid4()
MACHINE = uuid4()


def _launch(
    *,
    status: TaskLaunchStatus = TaskLaunchStatus.REQUESTED,
    harness: str = "claude-code",
    project_id: UUID = PROJECT,
    version: int = 1,
) -> TaskLaunch:
    now = datetime.now(UTC)
    return TaskLaunch(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        version=version,
        project_id=project_id,
        task_id=uuid4(),
        machine_id=MACHINE,
        requested_by_user_id=uuid4(),
        harness_id=harness,
        status=status,
        expires_at=now + timedelta(minutes=15),
    )


def _policy(**overrides: Any) -> LaunchPolicy:
    base: dict[str, Any] = {
        "opt_in": True,
        "project_ids": frozenset({PROJECT}),
        "allowed_harnesses": frozenset({"claude-code"}),
        "detected_harnesses": frozenset({"claude-code"}),
        "max_concurrent": 1,
    }
    base.update(overrides)
    return LaunchPolicy(**base)


@pytest.mark.parametrize(
    ("overrides", "launch_kwargs", "active", "expected"),
    [
        ({}, {}, 0, TaskLaunchReasonCode.NONE),
        ({"opt_in": False}, {}, 0, TaskLaunchReasonCode.NOT_OPTED_IN),
        ({}, {"project_id": uuid4()}, 0, TaskLaunchReasonCode.PROJECT_NOT_REGISTERED),
        ({}, {"harness": "codex"}, 0, TaskLaunchReasonCode.HARNESS_NOT_ALLOWED),
        (
            {"detected_harnesses": frozenset()},
            {},
            0,
            TaskLaunchReasonCode.HARNESS_NOT_FOUND,
        ),
        ({}, {}, 1, TaskLaunchReasonCode.CAPACITY_REACHED),
        ({"allowed_harnesses": frozenset()}, {}, 0, TaskLaunchReasonCode.HARNESS_NOT_ALLOWED),
    ],
)
def test_policy_refusals(
    overrides: dict[str, Any],
    launch_kwargs: dict[str, Any],
    active: int,
    expected: TaskLaunchReasonCode,
) -> None:
    assert _policy(**overrides).evaluate(_launch(**launch_kwargs), active=active) is expected


class FakeClient:
    def __init__(self, pending: list[TaskLaunch]) -> None:
        self.pending = pending
        self.fail = False

    async def pull_pending_launches(self, machine_id: UUID) -> list[TaskLaunch]:
        assert machine_id == MACHINE
        if self.fail:
            raise StudioApiError(503, "unavailable", "boom")
        return self.pending


def _puller(
    tmp_path: Path, client: FakeClient, policy: LaunchPolicy
) -> tuple[LaunchPuller, OutboxStore]:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    puller = LaunchPuller(  # type: ignore[arg-type]
        client, MACHINE, lambda: policy, LaunchReporter(store)
    )
    return puller, store


def _reports(store: OutboxStore) -> list[tuple[str, str]]:
    rows = store.list_pending(OutboxTable.MUTATIONS)
    return [(str(row.extra["path"]), str(row.payload["status"])) for row in rows]


def test_accepts_then_rejects_over_capacity(tmp_path: Path) -> None:
    first, second = _launch(), _launch()
    puller, store = _puller(tmp_path, FakeClient([first, second]), _policy())
    accepted = asyncio.run(puller.poll())
    assert [launch.id for launch in accepted] == [first.id]
    rows = store.list_pending(OutboxTable.MUTATIONS)
    by_path = {str(r.extra["path"]): r.payload for r in rows}
    assert by_path[f"/api/v1/task-launches/{first.id}/report"]["status"] == "accepted"
    rejected = by_path[f"/api/v1/task-launches/{second.id}/report"]
    assert rejected["status"] == "rejected"
    assert rejected["reason_code"] == "capacity_reached"
    assert rejected["expected_version"] == 1


def test_owned_launch_counts_and_is_not_redecided(tmp_path: Path) -> None:
    running = _launch(status=TaskLaunchStatus.RUNNING)
    queued = _launch()
    puller, store = _puller(tmp_path, FakeClient([running, queued]), _policy())
    asyncio.run(puller.poll())
    assert _reports(store) == [(f"/api/v1/task-launches/{queued.id}/report", "rejected")]


def test_repoll_before_server_update_does_not_duplicate(tmp_path: Path) -> None:
    launch = _launch()
    puller, store = _puller(tmp_path, FakeClient([launch]), _policy())
    assert len(asyncio.run(puller.poll())) == 1
    assert asyncio.run(puller.poll()) == []
    assert len(store.list_pending(OutboxTable.MUTATIONS)) == 1


def test_not_opted_in_rejects_everything(tmp_path: Path) -> None:
    launch = _launch()
    puller, store = _puller(tmp_path, FakeClient([launch]), _policy(opt_in=False))
    asyncio.run(puller.poll())
    [row] = store.list_pending(OutboxTable.MUTATIONS)
    assert row.payload["reason_code"] == "not_opted_in"


def test_pull_failure_is_swallowed(tmp_path: Path) -> None:
    client = FakeClient([_launch()])
    client.fail = True
    puller, store = _puller(tmp_path, client, _policy())
    assert asyncio.run(puller.poll()) == []
    assert store.list_pending(OutboxTable.MUTATIONS) == []
