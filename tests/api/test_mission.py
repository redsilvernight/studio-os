"""Mission Control read model (DEC-0196, P02-read-model).

One test per row of the truth table of `studio_contracts.mission`, plus the
discriminating cases: discordant states (every matching reason stays
visible), expired claims, project isolation, an unreadable cursor, and the
read model never running more SQL statements for 10 runs than for 1.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

MISSION = "/api/v1/projects/{project_id}/mission"


def _ago(**kwargs: float) -> datetime:
    return datetime.now(UTC) - timedelta(**kwargs)


async def _task(db_session: AsyncSession, project_id: uuid.UUID, title: str = "task") -> TaskModel:
    task = TaskModel(project_id=project_id, title=title, status="in_progress")
    db_session.add(task)
    await db_session.flush()
    return task


async def _launch(
    db_session: AsyncSession,
    project_id: uuid.UUID,
    task: TaskModel,
    machine: MachineModel,
    *,
    status: str = "succeeded",
    session_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> TaskLaunchModel:
    launch = TaskLaunchModel(
        project_id=project_id,
        task_id=task.id,
        machine_id=machine.id,
        requested_by_user_id=machine.owner_user_id,
        harness_id="claude-code",
        status=status,
        reason_code="none",
        created_at=created_at or _ago(minutes=5),
        finished_at=finished_at if finished_at is not None else _ago(minutes=4),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        session_id=session_id,
    )
    db_session.add(launch)
    await db_session.flush()
    return launch


async def _session(
    db_session: AsyncSession,
    task: TaskModel,
    machine: MachineModel,
    *,
    agent_id: uuid.UUID | None = None,
    started_at: datetime | None = None,
    last_activity_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> WorkSessionModel:
    work_session = WorkSessionModel(
        task_id=task.id,
        machine_id=machine.id,
        agent_id=agent_id,
        started_at=started_at or _ago(minutes=30),
        last_activity_at=last_activity_at,
        ended_at=ended_at,
    )
    db_session.add(work_session)
    await db_session.flush()
    return work_session


async def _ai_work(
    db_session: AsyncSession,
    project_id: uuid.UUID,
    agent: AgentModel,
    *,
    task: TaskModel | None = None,
    work_session: WorkSessionModel | None = None,
    status: str = "started",
    summary: str = "work",
) -> AIWorkLogModel:
    entry = AIWorkLogModel(
        project_id=project_id,
        agent_id=agent.id,
        task_id=task.id if task is not None else None,
        session_id=work_session.id if work_session is not None else None,
        summary=summary,
        status=status,
        started_at=_ago(minutes=20),
        ended_at=_ago(minutes=10) if status != "started" else None,
    )
    db_session.add(entry)
    await db_session.flush()
    return entry


async def _claim(
    db_session: AsyncSession,
    project_id: uuid.UUID,
    machine: MachineModel,
    task: TaskModel,
    *,
    status: str = "active",
    expires_at: datetime | None = None,
) -> ResourceClaimModel:
    claim = ResourceClaimModel(
        project_id=project_id,
        task_id=task.id,
        resource_path="src/service.py",
        resource_type="file",
        claimed_by_machine_id=machine.id,
        status=status,
        ttl_seconds=600,
        expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(claim)
    await db_session.flush()
    return claim


async def _decision(
    db_session: AsyncSession,
    project_id: uuid.UUID,
    machine: MachineModel,
    task: TaskModel,
    *,
    status: str = "proposed",
) -> DecisionModel:
    decision = DecisionModel(
        readable_id=f"DEC-{uuid.uuid4().hex[:4].upper()}",
        project_id=project_id,
        task_id=task.id,
        title="Adopt SSE",
        body="Server-Sent Events over WebSocket.",
        status=status,
        proposed_by_type="agent",
        proposed_by_id=machine.id,
    )
    db_session.add(decision)
    await db_session.flush()
    return decision


async def _mission(
    client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID, **params: object
) -> dict[str, object]:
    response = await client.get(
        MISSION.format(project_id=project_id), headers=headers, params=params or None
    )
    assert response.status_code == 200, response.text
    payload: dict[str, object] = response.json()
    return payload


def _runs(payload: dict[str, object]) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = payload["runs"]  # type: ignore[assignment]
    return runs


async def _online(
    db_session: AsyncSession, machine: MachineModel, *, seconds_since_seen: float = 1.0
) -> None:
    machine.last_seen_at = datetime.now(UTC) - timedelta(seconds=seconds_since_seen)
    await db_session.flush()


async def _offline_machine(
    db_session: AsyncSession, owner: MachineModel, display_name: str
) -> MachineModel:
    machine, _token = await provisioning_service.create_machine(
        db_session, owner.owner_user_id, display_name
    )
    return machine


async def test_empty_mission_has_no_run(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    payload = await _mission(client, auth_headers, project.id)
    assert payload["runs"] == []
    assert payload["counts"] == {"by_verdict": {}, "total": 0}
    assert payload["next_cursor"] is None
    assert payload["truncated"] is False
    assert payload["window_hours"] == 168


async def test_rule_1_launch_cancelled_wins_over_every_later_row(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
) -> None:
    """A cancelled launch is final even while the work asks for a review and
    a decision is proposed on the same task — the later rows stay visible."""
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    launch = await _launch(db_session, project.id, task, machine_model, status="cancelled")
    await _ai_work(db_session, project.id, agent, task=task, status="review_requested")
    await _decision(db_session, project.id, machine_model, task)

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["run_id"] == str(launch.id)
    assert run["source"] == "launch"
    assert run["verdict"] == "cancelled"
    assert run["reasons"][0] == "launch_cancelled"
    assert "review_requested" in run["reasons"]
    assert "decision_proposed" in run["reasons"]


async def test_rule_2_failed_rejected_and_expired_launches_are_failed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    expected = {
        "failed": "launch_failed",
        "rejected": "launch_rejected",
        "expired": "launch_expired",
    }
    for index, launch_status in enumerate(expected):
        task = await _task(db_session, project.id, title=f"task-{index}")
        await _launch(db_session, project.id, task, machine_model, status=launch_status)

    runs = _runs(await _mission(client, auth_headers, project.id))
    by_status = {run["launch"]["status"]: run for run in runs}
    assert set(by_status) == set(expected)
    for launch_status, reason in expected.items():
        assert by_status[launch_status]["verdict"] == "failed"
        assert by_status[launch_status]["reasons"][0] == reason


async def test_rule_3_review_requested_on_the_session_is_waiting_human(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    work_session = await _session(db_session, task, machine_model, last_activity_at=_ago(minutes=1))
    await _launch(
        db_session, project.id, task, machine_model, status="running", session_id=work_session.id
    )
    await _ai_work(
        db_session, project.id, agent, work_session=work_session, status="review_requested"
    )

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["verdict"] == "waiting_human"
    assert run["reasons"][0] == "review_requested"
    assert run["protocol_state"] == "open"


async def test_rule_3_review_requested_on_the_task_when_there_is_no_session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    await _launch(db_session, project.id, task, machine_model, status="running")
    await _ai_work(db_session, project.id, agent, task=task, status="review_requested")

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["verdict"] == "waiting_human"
    assert run["reasons"][0] == "review_requested"


async def test_rule_4_proposed_decision_on_the_task_is_waiting_human(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    await _launch(db_session, project.id, task, machine_model, status="running")
    await _decision(db_session, project.id, machine_model, task)

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["verdict"] == "waiting_human"
    assert run["reasons"][0] == "decision_proposed"


async def test_rule_4_accepted_decision_leaves_the_run_out_of_the_queue(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    await _launch(db_session, project.id, task, machine_model, status="running")
    await _decision(db_session, project.id, machine_model, task, status="accepted")

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["verdict"] == "running"
    assert "decision_proposed" not in run["reasons"]


async def test_rule_5_handed_off_is_done(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    ended = _ago(minutes=3)
    work_session = await _session(
        db_session, task, machine_model, last_activity_at=ended, ended_at=ended
    )
    await _launch(db_session, project.id, task, machine_model, session_id=work_session.id)
    entry = await _ai_work(
        db_session, project.id, agent, work_session=work_session, status="completed", summary="done"
    )

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["verdict"] == "done"
    assert run["reasons"][0] == "handed_off"
    assert run["protocol_state"] == "handed_off"
    assert run["handoff"]["ai_work_id"] == str(entry.id)
    assert run["handoff"]["status"] == "completed"


async def test_rule_6_launch_succeeded_without_a_session_needs_attention(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    await _launch(db_session, project.id, task, machine_model)

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["verdict"] == "needs_attention"
    assert run["reasons"][0] == "process_exited_without_session"
    assert run["protocol_state"] == "missing"
    assert run["session"] is None


async def test_rule_7_launch_succeeded_and_session_ended_without_handoff(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    ended = _ago(minutes=3)
    work_session = await _session(
        db_session, task, machine_model, last_activity_at=ended, ended_at=ended
    )
    await _launch(db_session, project.id, task, machine_model, session_id=work_session.id)

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["verdict"] == "needs_attention"
    assert run["reasons"][0] == "session_ended_without_handoff"
    assert run["protocol_state"] == "ended_without_handoff"
    assert run["handoff"] is None


async def test_rule_8_launch_succeeded_while_the_session_is_still_open(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    work_session = await _session(db_session, task, machine_model, last_activity_at=_ago(minutes=1))
    await _launch(db_session, project.id, task, machine_model, session_id=work_session.id)

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["verdict"] == "needs_attention"
    assert run["reasons"][0] == "process_exited_session_open"
    assert run["protocol_state"] == "open"


async def test_rule_9_expired_session_and_offline_machine_are_stale(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    online_machine, _ = machine
    await _online(db_session, online_machine)
    expired_task = await _task(db_session, project.id, title="expired")
    expired_session = await _session(
        db_session, expired_task, online_machine, last_activity_at=_ago(hours=10)
    )
    await _launch(
        db_session,
        project.id,
        expired_task,
        online_machine,
        status="running",
        session_id=expired_session.id,
    )

    offline_machine = await _offline_machine(db_session, online_machine, "silenced-machine")
    running_task = await _task(db_session, project.id, title="running")
    running_session = await _session(
        db_session, running_task, offline_machine, last_activity_at=_ago(minutes=1)
    )
    await _launch(
        db_session,
        project.id,
        running_task,
        offline_machine,
        status="running",
        session_id=running_session.id,
    )

    runs = {
        run["task_title"]: run for run in _runs(await _mission(client, auth_headers, project.id))
    }
    assert runs["expired"]["verdict"] == "stale"
    assert runs["expired"]["reasons"] == ["session_expired"]
    assert runs["expired"]["session"]["status"] == "expired"
    assert runs["running"]["verdict"] == "stale"
    assert runs["running"]["reasons"] == ["machine_offline"]
    assert runs["running"]["machine_status"] == "offline"


async def test_rule_10_manual_session_ended_without_handoff_needs_attention(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    ended = _ago(minutes=3)
    work_session = await _session(
        db_session, task, machine_model, last_activity_at=ended, ended_at=ended
    )

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["source"] == "session"
    assert run["run_id"] == str(work_session.id)
    assert run["launch"] is None
    assert run["verdict"] == "needs_attention"
    assert run["reasons"][0] == "session_ended_without_handoff"


async def test_rule_11_not_yet_running_launch_is_pending(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    for index, launch_status in enumerate(("requested", "accepted", "preparing")):
        task = await _task(db_session, project.id, title=f"task-{index}")
        await _launch(db_session, project.id, task, machine_model, status=launch_status)

    runs = _runs(await _mission(client, auth_headers, project.id))
    assert {run["launch"]["status"] for run in runs} == {"requested", "accepted", "preparing"}
    for run in runs:
        assert run["verdict"] == "pending"
        assert run["reasons"][0] == "launch_pending"


async def test_rule_12_a_running_process_is_running(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id, title="active")
    work_session = await _session(db_session, task, machine_model, last_activity_at=_ago(minutes=1))
    await _launch(
        db_session, project.id, task, machine_model, status="running", session_id=work_session.id
    )

    idle_task = await _task(db_session, project.id, title="idle")
    await _session(db_session, idle_task, machine_model, last_activity_at=_ago(minutes=45))

    runs = {
        run["task_title"]: run for run in _runs(await _mission(client, auth_headers, project.id))
    }
    assert runs["active"]["verdict"] == "running"
    assert runs["active"]["reasons"] == ["process_running"]
    assert runs["idle"]["verdict"] == "running"
    assert runs["idle"]["reasons"] == ["session_idle"]


async def test_discordant_run_lists_every_matching_reason(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
) -> None:
    """A review requested on a session that already handed off is three rows
    at once: the human wins the verdict, both rows stay readable."""
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    ended = _ago(minutes=3)
    work_session = await _session(
        db_session, task, machine_model, last_activity_at=ended, ended_at=ended
    )
    await _launch(db_session, project.id, task, machine_model, session_id=work_session.id)
    await _ai_work(
        db_session, project.id, agent, work_session=work_session, status="review_requested"
    )

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["verdict"] == "waiting_human"
    assert run["reasons"] == ["review_requested", "handed_off"]
    assert run["protocol_state"] == "handed_off"


async def test_expired_and_released_claims_are_not_counted(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id)
    await _launch(db_session, project.id, task, machine_model, status="running")
    await _claim(db_session, project.id, machine_model, task)
    await _claim(db_session, project.id, machine_model, task, expires_at=_ago(minutes=1))
    await _claim(db_session, project.id, machine_model, task, status="released")

    run = _runs(await _mission(client, auth_headers, project.id))[0]
    assert run["active_claims"] == 1


async def test_runs_of_another_project_never_leak(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    other = await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Other", None, creator=None
    )
    mine = await _task(db_session, project.id, title="mine")
    await _launch(db_session, project.id, mine, machine_model, status="running")
    theirs = await _task(db_session, other.id, title="theirs")
    await _launch(db_session, other.id, theirs, machine_model, status="cancelled")
    await _session(db_session, theirs, machine_model, last_activity_at=_ago(minutes=1))

    payload = await _mission(client, auth_headers, project.id)
    assert [run["task_title"] for run in _runs(payload)] == ["mine"]
    assert payload["counts"]["total"] == 1


async def test_runs_outside_the_window_are_excluded(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    task = await _task(db_session, project.id, title="recent")
    await _launch(db_session, project.id, task, machine_model, status="running")
    old = await _task(db_session, project.id, title="ancient")
    await _launch(
        db_session,
        project.id,
        old,
        machine_model,
        status="running",
        created_at=_ago(days=30),
        finished_at=_ago(days=30),
    )

    payload = await _mission(client, auth_headers, project.id, window_hours=24)
    assert [run["task_title"] for run in _runs(payload)] == ["recent"]


@pytest.mark.isolation
async def test_inaccessible_project_answers_403(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    """No existence oracle (DEC-0103 §3): the project gate runs before any read."""
    response = await client.get(MISSION.format(project_id=project.id), headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error_code": "forbidden",
        "resource": "project",
        "action": "read",
    }


async def test_pagination_walks_the_whole_window_without_repeats(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    await _online(db_session, machine_model)
    launches = []
    for index in range(5):
        task = await _task(db_session, project.id, title=f"task-{index}")
        launches.append(
            await _launch(
                db_session,
                project.id,
                task,
                machine_model,
                status="running",
                created_at=_ago(minutes=60 - index),
            )
        )

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, object] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        payload = await _mission(client, auth_headers, project.id, **params)
        pages += 1
        seen.extend(run["run_id"] for run in _runs(payload))
        assert payload["counts"]["total"] == len(launches)
        cursor = payload["next_cursor"]  # type: ignore[assignment]
        if cursor is None:
            break
        assert payload["truncated"] is True
    assert pages == 3
    assert sorted(seen) == sorted(str(launch.id) for launch in launches)
    assert seen == [str(launch.id) for launch in reversed(launches)]


async def test_unreadable_cursor_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    response = await client.get(
        MISSION.format(project_id=project.id), headers=auth_headers, params={"cursor": "not-base64"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_cursor"


async def test_sql_statement_count_does_not_grow_with_the_number_of_runs(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    engine: AsyncEngine,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    """One statement per source, whatever the number of runs: no per-run
    lookup sneaks in (a query-count assertion, not a timing one)."""
    machine_model, _ = machine
    await _online(db_session, machine_model)
    statements: list[str] = []

    def _listener(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    async def _measure() -> int:
        statements.clear()
        event.listen(engine.sync_engine, "before_cursor_execute", _listener)
        try:
            response = await client.get(MISSION.format(project_id=project.id), headers=auth_headers)
            assert response.status_code == 200, response.text
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _listener)
        return len(statements)

    first = await _task(db_session, project.id, title="only")
    await _launch(db_session, project.id, first, machine_model, status="running")
    with_one_run = await _measure()

    for index in range(9):
        task = await _task(db_session, project.id, title=f"extra-{index}")
        await _launch(
            db_session,
            project.id,
            task,
            machine_model,
            status="running",
            created_at=_ago(minutes=30 - index),
        )
    with_ten_runs = await _measure()

    assert with_ten_runs == with_one_run
