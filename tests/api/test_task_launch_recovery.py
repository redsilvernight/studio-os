"""P02 recovery: read-time recovery verdict, explicit retry as a new attempt,
exact session link for a launch credential."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import task_launches as launches_service
from studio_contracts.task_launch import TaskLaunch

from tests.api.test_task_launches import _launch, _ready_target, _report


async def _listed(
    client: AsyncClient, headers: dict[str, str], project_id: str
) -> dict[str, dict[str, Any]]:
    response = await client.get(f"/api/v1/projects/{project_id}/task-launches", headers=headers)
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()["items"]}


async def _failed_launch(
    client: AsyncClient, headers: dict[str, str], machine: tuple[MachineModel, str]
) -> tuple[str, dict[str, Any]]:
    project_id, task_id, machine_id = await _ready_target(client, headers, machine)
    launch = (await _launch(client, headers, project_id, task_id, machine_id)).json()
    launch = await _report(client, headers, launch["id"], launch["version"], "accepted")
    launch = await _report(client, headers, launch["id"], launch["version"], "failed")
    return project_id, launch


async def _retry(
    client: AsyncClient, headers: dict[str, str], launch_id: str, key: str | None = None
) -> Any:
    extra = {"Idempotency-Key": key} if key else {}
    return await client.post(
        f"/api/v1/task-launches/{launch_id}/retry", headers={**headers, **extra}
    )


async def _set_offline(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> None:
    model = await db_session.get(MachineModel, machine[0].id)
    assert model is not None
    model.last_seen_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()


async def test_recovery_ok_while_the_machine_answers(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    item = (await _listed(client, auth_headers, project_id))[launch["id"]]
    assert item["attempt"] == 1
    assert item["retry_of_launch_id"] is None
    assert item["recovery"] == {
        "state": "ok",
        "reason": "none",
        "machine_status": "online",
        "stale_since": None,
    }


async def test_recovery_distinguishes_stale_offline_wip_and_failed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    requested = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    running = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    running = await _report(client, auth_headers, running["id"], running["version"], "accepted")
    running = await _report(client, auth_headers, running["id"], running["version"], "preparing")
    running = await _report(client, auth_headers, running["id"], running["version"], "running")
    failed = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    failed = await _report(client, auth_headers, failed["id"], failed["version"], "accepted")
    failed = await _report(client, auth_headers, failed["id"], failed["version"], "failed")
    await _set_offline(db_session, machine)

    items = await _listed(client, auth_headers, project_id)
    stale = items[requested["id"]]["recovery"]
    assert (stale["state"], stale["reason"], stale["machine_status"]) == (
        "stale",
        "machine_offline",
        "offline",
    )
    assert stale["stale_since"] is not None
    wip = items[running["id"]]["recovery"]
    assert (wip["state"], wip["reason"]) == ("offline_wip", "machine_offline")
    assert wip["stale_since"] == stale["stale_since"]
    # Offline WIP is not a failure: the attempt itself is untouched.
    assert items[running["id"]]["status"] == "running"
    gone = items[failed["id"]]["recovery"]
    assert (gone["state"], gone["reason"]) == ("failed", "launch_failed")


async def test_recovery_of_an_expired_attempt_is_stale(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    row = await db_session.get(TaskLaunchModel, uuid.UUID(launch["id"]))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    read = await client.get(f"/api/v1/task-launches/{launch['id']}", headers=auth_headers)
    assert read.json()["status"] == "expired"
    recovery = (await _listed(client, auth_headers, project_id))[launch["id"]]["recovery"]
    assert (recovery["state"], recovery["reason"]) == ("stale", "launch_expired")
    assert recovery["stale_since"] is not None


async def test_retry_creates_a_new_attempt_and_keeps_the_trace(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, failed = await _failed_launch(client, auth_headers, machine)
    response = await _retry(client, auth_headers, failed["id"])
    assert response.status_code == 201, response.text
    retried = response.json()
    assert retried["id"] != failed["id"]
    assert retried["status"] == "requested"
    assert retried["attempt"] == 2
    assert retried["retry_of_launch_id"] == failed["id"]
    for field in ("task_id", "machine_id", "harness_id", "agent_stable_key"):
        assert retried[field] == failed[field]
    assert retried["recovery"]["state"] == "ok"

    items = await _listed(client, auth_headers, project_id)
    assert set(items) == {failed["id"], retried["id"]}
    previous = items[failed["id"]]
    assert (previous["status"], previous["version"]) == ("failed", failed["version"])
    assert previous["recovery"]["state"] == "failed"

    # A failed retry is retried in turn: the chain grows, nothing is rewritten.
    retried = await _report(client, auth_headers, retried["id"], retried["version"], "rejected")
    third = await _retry(client, auth_headers, retried["id"])
    assert third.status_code == 201, third.text
    assert third.json()["attempt"] == 3
    assert third.json()["retry_of_launch_id"] == retried["id"]


async def test_retry_is_idempotent_and_never_doubles_an_attempt(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, failed = await _failed_launch(client, auth_headers, machine)
    first = await _retry(client, auth_headers, failed["id"], key="retry-a")
    replay = await _retry(client, auth_headers, failed["id"], key="retry-a")
    other_key = await _retry(client, auth_headers, failed["id"], key="retry-b")
    no_key = await _retry(client, auth_headers, failed["id"])
    assert first.status_code == 201, first.text
    for response in (replay, other_key, no_key):
        assert response.status_code == 201, response.text
        assert response.json()["id"] == first.json()["id"]
    assert len(await _listed(client, auth_headers, project_id)) == 2


async def test_retry_of_a_live_attempt_is_409(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    response = await _retry(client, auth_headers, launch["id"])
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error_code"] == "launch_not_terminal"
    # Offline work in progress is never doubled either.
    launch = await _report(client, auth_headers, launch["id"], launch["version"], "accepted")
    await _set_offline(db_session, machine)
    response = await _retry(client, auth_headers, launch["id"])
    assert response.status_code == 409, response.text
    assert len(await _listed(client, auth_headers, project_id)) == 1


async def test_retry_rechecks_the_machine_and_the_requester(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, failed = await _failed_launch(client, auth_headers, machine)
    foreign = await _retry(client, other_auth_headers, failed["id"])
    assert foreign.status_code in {403, 404}, foreign.text
    await _set_offline(db_session, machine)
    offline = await _retry(client, auth_headers, failed["id"])
    assert offline.status_code == 409, offline.text
    assert offline.json()["detail"]["error_code"] == "machine_offline"
    assert len(await _listed(client, auth_headers, project_id)) == 1


async def test_retry_fields_never_reach_the_n_minus_1_routes(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    _, failed = await _failed_launch(client, auth_headers, machine)
    retried = (await _retry(client, auth_headers, failed["id"])).json()
    by_id = await client.get(f"/api/v1/task-launches/{retried['id']}", headers=auth_headers)
    assert by_id.status_code == 200, by_id.text
    for field in ("attempt", "retry_of_launch_id", "recovery", "protocol"):
        assert field not in by_id.json()
    TaskLaunch.model_validate(by_id.json())
    pull = await client.get(
        f"/api/v1/machines/{retried['machine_id']}/task-launches/pending", headers=auth_headers
    )
    assert pull.status_code == 200, pull.text
    assert [item["id"] for item in pull.json()["items"]] == [retried["id"]]
    assert "attempt" not in pull.json()["items"][0]


async def test_scoped_session_links_its_own_attempt_and_never_steals(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    """A harness started with a launch credential reconnecting: its session
    links to that exact attempt, not to the newest live one, and a second
    session never takes over an attempt already linked."""
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    older = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    await _report(client, auth_headers, older["id"], older["version"], "accepted")
    newer = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    await _report(client, auth_headers, newer["id"], newer["version"], "accepted")
    now = datetime.now(UTC)
    sessions = []
    for _ in range(2):
        work_session = WorkSessionModel(
            task_id=uuid.UUID(task_id),
            machine_id=uuid.UUID(machine_id),
            started_at=now,
            last_activity_at=now,
        )
        db_session.add(work_session)
        await db_session.commit()
        sessions.append(work_session)
    older_id = uuid.UUID(older["id"])
    await launches_service.link_session_to_launch(db_session, sessions[0], older_id)
    await launches_service.link_session_to_launch(db_session, sessions[0], older_id)
    await launches_service.link_session_to_launch(db_session, sessions[1], older_id)
    older_row = await db_session.get(TaskLaunchModel, older_id)
    newer_row = await db_session.get(TaskLaunchModel, uuid.UUID(newer["id"]))
    assert older_row is not None and newer_row is not None
    await db_session.refresh(older_row)
    await db_session.refresh(newer_row)
    assert older_row.session_id == sessions[0].id
    assert newer_row.session_id is None
