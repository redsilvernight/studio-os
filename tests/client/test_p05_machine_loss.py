"""P05 — machine loss and local refusal, on the two simulated machines of
`tests.client.test_launch_e2e_acceptance` (whose fixtures/helpers this module
reuses: machine A requests, machine B is the launch target).

Machine loss (M1): A requests a launch on B, B pulls and accepts it (the
machine "starts" the run), then B stops heartbeating past
`settings.heartbeat_offline_after_seconds`. The project launch list — the read
model, never a stored cache — exposes the loss: `offline_wip` for the accepted
attempt, `stale` for one still `requested` on the dead machine. A new
admission of the same task never doubles it while the attempt is live (the
same `Idempotency-Key` returns the original, a fresh request on the dead
machine is refused, an explicit retry is `409 launch_not_terminal`); the
attempt is only replaced once it is cancelled, and the project's active
launches never exceed its budget slots.

Local refusal (M2): the target machine's own policy refuses before anything
runs. The launch is reported `rejected`, stays visible in the list, is never
automatically retried and never doubled."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.settings import Settings
from studio_client.api_client import StudioApiClient
from studio_client.daemon.launch_puller import LaunchPuller
from studio_client.daemon.launch_report import LaunchReporter
from studio_client.errors import StudioApiError
from studio_client.outbox import OutboxReplayer, OutboxStore, OutboxTable, connect
from studio_contracts.auth import MachineStatus
from studio_contracts.budgets import BudgetStatus
from studio_contracts.common import Page
from studio_contracts.task_launch import (
    TaskLaunchReasonCode,
    TaskLaunchRecoveryReason,
    TaskLaunchRecoveryState,
    TaskLaunchStatus,
    TaskLaunchView,
)

from tests.client.test_launch_e2e_acceptance import (
    _RETRY,
    _cancel_launch,
    _client,
    _fleet,
    _launch_mutations,
    _policy,
    _report_capabilities,
    _request_launch,
)

_OFFLINE_AFTER = Settings().heartbeat_offline_after_seconds


async def _stop_heartbeats(db_session: AsyncSession, machine_id: UUID) -> None:
    """The machine goes silent: its last heartbeat falls past the offline
    threshold, so the server derives `offline` at read time."""
    row = await db_session.get(MachineModel, machine_id)
    assert row is not None
    row.last_seen_at = datetime.now(UTC) - timedelta(seconds=_OFFLINE_AFTER + 60)
    await db_session.commit()


async def _launch_view(api: StudioApiClient, project_id: UUID, launch_id: UUID) -> TaskLaunchView:
    response = await api._request("GET", f"/api/v1/projects/{project_id}/task-launches")
    page = Page[TaskLaunchView].model_validate(response.json())
    views = {view.id: view for view in page.items}
    assert launch_id in views, [str(view.id) for view in page.items]
    return views[launch_id]


async def _retry_launch(api: StudioApiClient, launch_id: UUID) -> TaskLaunchView:
    response = await api.send_mutation(
        "POST",
        f"/api/v1/task-launches/{launch_id}/retry",
        {},
        idempotency_key=str(uuid.uuid4()),
    )
    return TaskLaunchView.model_validate(response.json())


async def _set_slots(api: StudioApiClient, project_id: UUID, slots: int) -> None:
    response = await api._request(
        "PUT",
        f"/api/v1/projects/{project_id}/budget-policy",
        json={"max_active_launches": slots},
    )
    assert response.status_code == 200, response.text


async def _active_launches(api: StudioApiClient, project_id: UUID) -> int:
    response = await api._request("GET", f"/api/v1/projects/{project_id}/budget")
    return BudgetStatus.model_validate(response.json()).active_launches


async def _launch_count(db_session: AsyncSession, project_id: UUID) -> int:
    return int(
        await db_session.scalar(
            select(func.count())
            .select_from(TaskLaunchModel)
            .where(TaskLaunchModel.project_id == project_id)
        )
    )


async def test_lost_machine_reads_offline_then_stale_and_is_never_doubled(
    tmp_path: Path,
    app_transport: ASGITransport,
    db_session: AsyncSession,
) -> None:
    fleet = await _fleet(db_session)
    project_id = fleet.project.id
    task_id = fleet.task.id
    machine_a_id = fleet.machine_a.id
    machine_b_id = fleet.machine_b.id
    store = OutboxStore(connect(tmp_path / "machine-b-outbox.sqlite3"))
    try:
        async with _client(fleet.token_a, machine_a_id, app_transport) as api_a:
            async with _client(fleet.token_b, machine_b_id, app_transport) as api_b:
                await _report_capabilities(api_b, machine_b_id, project_id)
                await _set_slots(api_a, project_id, 1)

                launch_key = str(uuid.uuid4())
                launch = await _request_launch(api_a, project_id, task_id, machine_b_id, launch_key)
                assert launch.status is TaskLaunchStatus.REQUESTED
                assert await _active_launches(api_a, project_id) == 1

                # Same task, same Idempotency-Key: the original, never a duplicate.
                replay = await _request_launch(api_a, project_id, task_id, machine_b_id, launch_key)
                assert replay.id == launch.id
                assert await _launch_count(db_session, project_id) == 1

                # M1 (the target) starts the launch: it pulls and accepts it.
                reporter = LaunchReporter(store)
                puller = LaunchPuller(api_b, machine_b_id, lambda: _policy(project_id), reporter)
                [accepted] = await puller.poll()
                assert accepted.id == launch.id
                await OutboxReplayer(store, api_b, _RETRY).replay_ready()
                running = await api_a.get_task_launch(launch.id)
                assert running.status is TaskLaunchStatus.ACCEPTED
                assert running.version == 2

                # M1 stops heartbeating: the accepted attempt reads offline_wip.
                await _stop_heartbeats(db_session, machine_b_id)
                view = await _launch_view(api_a, project_id, launch.id)
                assert view.recovery is not None
                assert view.recovery.state is TaskLaunchRecoveryState.OFFLINE_WIP
                assert view.recovery.reason is TaskLaunchRecoveryReason.MACHINE_OFFLINE
                assert view.recovery.machine_status is MachineStatus.OFFLINE
                assert view.recovery.stale_since is not None

                # A new admission of the same task never doubles a live attempt.
                # A fresh request while M1 is dead is refused (its slot is still
                # held), and an explicit retry is refused while the attempt is
                # not terminal.
                with pytest.raises(StudioApiError) as lost:
                    await _request_launch(
                        api_a, project_id, task_id, machine_b_id, str(uuid.uuid4())
                    )
                assert lost.value.status_code == 409
                assert lost.value.error_code == "machine_offline"
                with pytest.raises(StudioApiError) as refused:
                    await _retry_launch(api_a, launch.id)
                assert refused.value.status_code == 409
                assert refused.value.error_code == "launch_not_terminal"
                assert await _launch_count(db_session, project_id) == 1
                assert await _active_launches(api_a, project_id) == 1

                # The attempt is only replaced once the requester cancels it:
                # cancelling frees its slot, retrying creates a new attempt.
                cancelled = await _cancel_launch(api_a, launch.id, running.version)
                assert cancelled.status is TaskLaunchStatus.CANCELLED
                assert await _active_launches(api_a, project_id) == 0

                await _report_capabilities(api_b, machine_b_id, project_id)
                retried = await _retry_launch(api_a, launch.id)
                assert retried.id != launch.id
                assert retried.attempt == 2
                assert retried.retry_of_launch_id == launch.id
                assert retried.status is TaskLaunchStatus.REQUESTED
                assert await _launch_count(db_session, project_id) == 2
                assert await _active_launches(api_a, project_id) == 1

                # M1 goes silent again: a requested attempt on an offline machine
                # reads stale, and the slot count still never exceeds the budget.
                await _stop_heartbeats(db_session, machine_b_id)
                stale = await _launch_view(api_a, project_id, retried.id)
                assert stale.recovery is not None
                assert stale.recovery.state is TaskLaunchRecoveryState.STALE
                assert stale.recovery.reason is TaskLaunchRecoveryReason.MACHINE_OFFLINE
                assert stale.recovery.machine_status is MachineStatus.OFFLINE
                assert stale.recovery.stale_since is not None
                assert await _active_launches(api_a, project_id) == 1
    finally:
        store.connection.close()


async def test_locally_refused_machine_is_reported_rejected_without_retry_or_double(
    tmp_path: Path,
    app_transport: ASGITransport,
    db_session: AsyncSession,
) -> None:
    fleet = await _fleet(db_session)
    project_id = fleet.project.id
    task_id = fleet.task.id
    machine_a_id = fleet.machine_a.id
    machine_b_id = fleet.machine_b.id
    store = OutboxStore(connect(tmp_path / "machine-b-outbox.sqlite3"))
    try:
        async with _client(fleet.token_b, machine_b_id, app_transport) as api_b:
            await _report_capabilities(api_b, machine_b_id, project_id)
            async with _client(fleet.token_a, machine_a_id, app_transport) as api_a:
                launch = await _request_launch(
                    api_a, project_id, task_id, machine_b_id, str(uuid.uuid4())
                )
                reporter = LaunchReporter(store)
                puller = LaunchPuller(
                    api_b,
                    machine_b_id,
                    lambda: _policy(project_id, opt_in=False),
                    reporter,
                )
                assert await puller.poll() == []
                [report] = _launch_mutations(store)
                assert report["status"] == TaskLaunchStatus.REJECTED.value
                assert report["reason_code"] == TaskLaunchReasonCode.NOT_OPTED_IN.value

                drained = await OutboxReplayer(store, api_b, _RETRY).replay_ready()
                assert drained.succeeded == 1
                assert drained.dead_lettered == 0
                assert store.list_pending(OutboxTable.MUTATIONS, ready_only=False) == []

                refused = await api_a.get_task_launch(launch.id)
                assert refused.status is TaskLaunchStatus.REJECTED
                assert refused.reason_code is TaskLaunchReasonCode.NOT_OPTED_IN
                view = await _launch_view(api_a, project_id, launch.id)
                assert view.status is TaskLaunchStatus.REJECTED

                # No automatic retry, no duplicate: the refusing machine does
                # not pull it again, a second replay adds nothing, and the task
                # still has exactly one launch row.
                assert await puller.poll() == []
                second = await OutboxReplayer(store, api_b, _RETRY).replay_ready()
                assert second.succeeded == 0
                assert await _launch_count(db_session, project_id) == 1
                assert view.retry_of_launch_id is None
    finally:
        store.connection.close()
