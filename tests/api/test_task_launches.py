from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel


async def _project_task(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    project = await client.post(
        "/api/v1/projects",
        json={"slug": f"ln-{uuid.uuid4().hex[:8]}", "name": "Ln"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    task = await client.post(
        "/api/v1/tasks", json={"project_id": project_id, "title": "t"}, headers=headers
    )
    assert task.status_code == 201, task.text
    return project_id, task.json()["id"]


def _caps(project_id: str, **overrides: Any) -> dict[str, Any]:
    caps: dict[str, Any] = {
        "harnesses": [{"harness_id": "claude-code", "version": "2.1.0"}],
        "project_ids": [project_id],
        "accepts_launches": True,
        "running_launches": 0,
        "max_launches": 2,
    }
    caps.update(overrides)
    return caps


async def _heartbeat(
    client: AsyncClient,
    headers: dict[str, str],
    machine_id: str,
    capabilities: dict[str, Any] | None,
) -> None:
    response = await client.post(
        "/api/v1/heartbeats",
        headers=headers,
        json={
            "machine_id": machine_id,
            "client_timestamp": datetime.now(UTC).isoformat(),
            "capabilities": capabilities,
        }
        if capabilities is not None
        else {
            "machine_id": machine_id,
            "client_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200, response.text


async def _launch(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    task_id: str,
    machine_id: str,
    key: str | None = None,
    **overrides: Any,
) -> Any:
    body: dict[str, Any] = {
        "task_id": task_id,
        "machine_id": machine_id,
        "harness_id": "claude-code",
    }
    body.update(overrides)
    extra = {"Idempotency-Key": key} if key else {}
    return await client.post(
        f"/api/v1/projects/{project_id}/task-launches",
        json=body,
        headers={**headers, **extra},
    )


async def _events(
    client: AsyncClient, headers: dict[str, str], task_id: str
) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/events", params={"task": task_id}, headers=headers)
    assert response.status_code == 200, response.text
    launches = [e for e in response.json() if e["event_type"].startswith("task_launch.")]
    return sorted(launches, key=lambda e: e["server_timestamp"])


async def _ready_target(
    client: AsyncClient, headers: dict[str, str], machine: tuple[MachineModel, str]
) -> tuple[str, str, str]:
    model, _ = machine
    project_id, task_id = await _project_task(client, headers)
    await _heartbeat(client, headers, str(model.id), _caps(project_id))
    return project_id, task_id, str(model.id)


async def test_create_launch_requested(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    response = await _launch(client, auth_headers, project_id, task_id, machine_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "requested"
    assert body["version"] == 1
    assert body["project_id"] == project_id
    events = await _events(client, auth_headers, task_id)
    assert [e["event_type"] for e in events] == ["task_launch.requested"]


async def test_create_replay_returns_original_without_new_event(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    key = f"launch-{uuid.uuid4()}"
    first = await _launch(client, auth_headers, project_id, task_id, machine_id, key=key)
    assert first.status_code == 201, first.text
    second = await _launch(client, auth_headers, project_id, task_id, machine_id, key=key)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    events = await _events(client, auth_headers, task_id)
    assert len(events) == 1


async def test_create_same_key_different_body_is_409(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    key = f"launch-{uuid.uuid4()}"
    first = await _launch(client, auth_headers, project_id, task_id, machine_id, key=key)
    assert first.status_code == 201, first.text
    second = await _launch(
        client,
        auth_headers,
        project_id,
        task_id,
        machine_id,
        key=key,
        harness_id="codex",
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"


async def test_create_unknown_task_or_machine_is_404(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    response = await _launch(client, auth_headers, project_id, str(uuid.uuid4()), machine_id)
    assert response.status_code == 404
    response = await _launch(client, auth_headers, project_id, task_id, str(uuid.uuid4()))
    assert response.status_code == 404


async def test_create_task_project_mismatch_is_409(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, _, machine_id = await _ready_target(client, auth_headers, machine)
    _, other_task = await _project_task(client, auth_headers)
    response = await _launch(client, auth_headers, project_id, other_task, machine_id)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "task_project_mismatch"


async def test_create_by_granted_user(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    other_auth_headers: dict[str, str],
) -> None:
    model, _ = machine
    other_model, _ = other_machine
    project_id, task_id, _ = await _ready_target(client, auth_headers, machine)
    grant = await client.put(
        f"/api/v1/machines/{model.id}/launch-grants/{other_model.owner_user_id}",
        json={"project_id": project_id},
        headers=auth_headers,
    )
    assert grant.status_code in (200, 201), grant.text
    response = await _launch(client, other_auth_headers, project_id, task_id, str(model.id))
    assert response.status_code == 201, response.text
    assert response.json()["requested_by_user_id"] == str(other_model.owner_user_id)


async def test_create_by_non_owner_is_403(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    other_auth_headers: dict[str, str],
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    response = await _launch(client, other_auth_headers, project_id, task_id, machine_id)
    assert response.status_code == 403


async def test_create_without_capabilities_report_is_409(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    model, _ = machine
    project_id, task_id = await _project_task(client, auth_headers)
    await _heartbeat(client, auth_headers, str(model.id), None)
    response = await _launch(client, auth_headers, project_id, task_id, str(model.id))
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "machine_capabilities_missing"


async def test_create_not_opted_in_or_unregistered_is_409(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    model, _ = machine
    project_id, task_id = await _project_task(client, auth_headers)
    await _heartbeat(client, auth_headers, str(model.id), _caps(project_id, accepts_launches=False))
    response = await _launch(client, auth_headers, project_id, task_id, str(model.id))
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "machine_not_opted_in"
    await _heartbeat(client, auth_headers, str(model.id), _caps(str(uuid.uuid4())))
    response = await _launch(client, auth_headers, project_id, task_id, str(model.id))
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "project_not_registered"


async def test_report_full_cycle_to_succeeded(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    version = launch["version"]
    for expected, reported in [
        ("accepted", "accepted"),
        ("preparing", "preparing"),
        ("running", "running"),
        ("succeeded", "succeeded"),
    ]:
        response = await client.post(
            f"/api/v1/task-launches/{launch['id']}/report",
            json={"expected_version": version, "status": reported},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == expected
        version = body["version"]
    events = await _events(client, auth_headers, task_id)
    assert [e["event_type"] for e in events] == [
        "task_launch.requested",
        "task_launch.accepted",
        "task_launch.finished",
    ]


async def test_report_attributes_agent_actor(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    agent = await client.post(
        "/api/v1/agents/ensure",
        json={"display_name": "daemon", "stable_key": "daemon-main"},
        headers=auth_headers,
    )
    assert agent.status_code in (200, 201), agent.text
    agent_id = agent.json()["agent"]["id"]
    launch = (
        await _launch(
            client, auth_headers, project_id, task_id, machine_id, agent_stable_key="daemon-main"
        )
    ).json()
    reported = await client.post(
        f"/api/v1/task-launches/{launch['id']}/report",
        json={"expected_version": launch["version"], "status": "accepted"},
        headers=auth_headers,
    )
    assert reported.status_code == 200, reported.text
    events = await _events(client, auth_headers, task_id)
    accepted = [e for e in events if e["event_type"] == "task_launch.accepted"]
    assert len(accepted) == 1
    assert accepted[0]["actor_type"] == "agent"
    assert accepted[0]["actor_id"] == agent_id


async def test_report_invalid_transition_is_409(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    response = await client.post(
        f"/api/v1/task-launches/{launch['id']}/report",
        json={"expected_version": launch["version"], "status": "running"},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "invalid_launch_transition"


async def test_report_stale_version_is_409(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    response = await client.post(
        f"/api/v1/task-launches/{launch['id']}/report",
        json={"expected_version": launch["version"] + 5, "status": "accepted"},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "version_conflict"


async def test_report_by_other_machine_is_403(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    other_auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    other_model, _ = other_machine
    await _heartbeat(client, other_auth_headers, str(other_model.id), _caps(project_id))
    response = await client.post(
        f"/api/v1/task-launches/{launch['id']}/report",
        json={"expected_version": launch["version"], "status": "accepted"},
        headers=other_auth_headers,
    )
    assert response.status_code == 403


async def test_report_machine_cannot_cancel_is_403(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    response = await client.post(
        f"/api/v1/task-launches/{launch['id']}/report",
        json={"expected_version": launch["version"], "status": "cancelled"},
        headers=auth_headers,
    )
    assert response.status_code == 403


async def test_cancel_by_requester(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    response = await client.post(
        f"/api/v1/task-launches/{launch['id']}/cancel",
        json={"expected_version": launch["version"]},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["reason_code"] == "cancelled_by_requester"
    events = await _events(client, auth_headers, task_id)
    assert [e["event_type"] for e in events] == [
        "task_launch.requested",
        "task_launch.cancelled",
    ]


async def test_cancel_terminal_is_409_and_foreign_cancel_is_403(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    other_auth_headers: dict[str, str],
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    cancelled = await client.post(
        f"/api/v1/task-launches/{launch['id']}/cancel",
        json={"expected_version": launch["version"]},
        headers=auth_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    again = await client.post(
        f"/api/v1/task-launches/{launch['id']}/cancel",
        json={"expected_version": cancelled.json()["version"]},
        headers=auth_headers,
    )
    assert again.status_code == 409
    foreign = await client.post(
        f"/api/v1/task-launches/{launch['id']}/cancel",
        json={"expected_version": cancelled.json()["version"]},
        headers=other_auth_headers,
    )
    assert foreign.status_code == 403


async def test_pull_pending_oldest_first_side_effect_free(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    first = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    second = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    first_row = await db_session.get(TaskLaunchModel, uuid.UUID(first["id"]))
    assert first_row is not None
    first_row.created_at = first_row.created_at - timedelta(seconds=1)
    await db_session.commit()
    response = await client.get(
        f"/api/v1/machines/{machine_id}/task-launches/pending", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [i["id"] for i in items] == [first["id"], second["id"]]
    events = await _events(client, auth_headers, task_id)
    assert len(events) == 2


async def test_pull_by_other_machine_is_403(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    other_auth_headers: dict[str, str],
) -> None:
    _, _, machine_id = await _ready_target(client, auth_headers, machine)
    response = await client.get(
        f"/api/v1/machines/{machine_id}/task-launches/pending", headers=other_auth_headers
    )
    assert response.status_code == 403


async def test_overdue_launch_expires_on_read(
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
    response = await client.get(f"/api/v1/task-launches/{launch['id']}", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "expired"
    assert body["reason_code"] == "expired_unpulled"
    events = await _events(client, auth_headers, task_id)
    assert [e["event_type"] for e in events] == [
        "task_launch.requested",
        "task_launch.expired",
    ]


async def test_overdue_accepted_launch_expires_as_timeout(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    accepted = await client.post(
        f"/api/v1/task-launches/{launch['id']}/report",
        json={"expected_version": launch["version"], "status": "accepted"},
        headers=auth_headers,
    )
    assert accepted.status_code == 200, accepted.text
    row = await db_session.get(TaskLaunchModel, uuid.UUID(launch["id"]))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    response = await client.get(
        f"/api/v1/machines/{machine_id}/task-launches/pending", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    events = await _events(client, auth_headers, task_id)
    assert [e["event_type"] for e in events] == [
        "task_launch.requested",
        "task_launch.accepted",
        "task_launch.expired",
    ]
    assert events[-1]["payload"]["reason_code"] == "expired_timeout"


async def _open_session(
    client: AsyncClient, headers: dict[str, str], task_id: str, machine_id: str
) -> str:
    response = await client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"task_id": task_id, "machine_id": machine_id},
    )
    assert response.status_code in {200, 201}, response.text
    return str(response.json()["id"])


async def _report(
    client: AsyncClient, headers: dict[str, str], launch_id: str, version: int, status: str
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/task-launches/{launch_id}/report",
        json={"expected_version": version, "status": status},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_session_on_task_and_machine_links_the_live_launch(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    accepted = await _report(client, auth_headers, launch["id"], launch["version"], "accepted")
    session_id = await _open_session(client, auth_headers, task_id, machine_id)
    fetched = await client.get(f"/api/v1/task-launches/{launch['id']}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["session_id"] == session_id
    assert fetched.json()["version"] == accepted["version"]
    finished = await _report(client, auth_headers, launch["id"], accepted["version"], "preparing")
    finished = await _report(client, auth_headers, launch["id"], finished["version"], "running")
    finished = await _report(client, auth_headers, launch["id"], finished["version"], "succeeded")
    assert finished["session_id"] == session_id


async def test_session_opened_before_the_launch_does_not_link_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    await _open_session(client, auth_headers, task_id, machine_id)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    row = await db_session.get(TaskLaunchModel, uuid.UUID(launch["id"]))
    assert row is not None
    await db_session.refresh(row)
    assert row.session_id is None


async def test_report_session_must_be_live_and_on_the_launch_task(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    other_task = await client.post(
        "/api/v1/tasks", json={"project_id": project_id, "title": "other"}, headers=auth_headers
    )
    assert other_task.status_code == 201, other_task.text
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    wrong_task_session = await _open_session(
        client, auth_headers, other_task.json()["id"], machine_id
    )
    ended_session = await _open_session(client, auth_headers, task_id, machine_id)
    ended = await client.patch(f"/api/v1/sessions/{ended_session}/end", headers=auth_headers)
    assert ended.status_code == 200, ended.text
    for session_id in (wrong_task_session, ended_session):
        response = await client.post(
            f"/api/v1/task-launches/{launch['id']}/report",
            json={
                "expected_version": launch["version"],
                "status": "accepted",
                "session_id": session_id,
            },
            headers=auth_headers,
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["error_code"] == "invalid_launch_session"


async def _protocols(
    client: AsyncClient, headers: dict[str, str], project_id: str
) -> dict[str, dict[str, Any]]:
    response = await client.get(f"/api/v1/projects/{project_id}/task-launches", headers=headers)
    assert response.status_code == 200, response.text
    return {item["id"]: item["protocol"] for item in response.json()["items"]}


async def _task_status(client: AsyncClient, headers: dict[str, str], task_id: str) -> str:
    response = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert response.status_code == 200, response.text
    status: str = response.json()["status"]
    return status


async def test_protocol_exit_zero_without_session_is_unverified(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    for reported in ("accepted", "preparing", "running", "succeeded"):
        launch = await _report(client, auth_headers, launch["id"], launch["version"], reported)
    assert launch["status"] == "succeeded"
    assert (await _protocols(client, auth_headers, project_id))[launch["id"]] == {
        "status": "unverified",
        "session_id": None,
        "task_status": None,
    }
    assert await _task_status(client, auth_headers, task_id) == "created"


async def test_protocol_open_session_on_succeeded_launch_is_unverified(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    launch = await _report(client, auth_headers, launch["id"], launch["version"], "accepted")
    session_id = await _open_session(client, auth_headers, task_id, machine_id)
    for reported in ("preparing", "running", "succeeded"):
        launch = await _report(client, auth_headers, launch["id"], launch["version"], reported)
    assert launch["status"] == "succeeded"
    assert (await _protocols(client, auth_headers, project_id))[launch["id"]] == {
        "status": "unverified",
        "session_id": session_id,
        "task_status": None,
    }


async def test_protocol_open_session_on_running_launch_is_awaiting(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    launch = await _report(client, auth_headers, launch["id"], launch["version"], "accepted")
    session_id = await _open_session(client, auth_headers, task_id, machine_id)
    for reported in ("preparing", "running"):
        launch = await _report(client, auth_headers, launch["id"], launch["version"], reported)
    assert launch["status"] == "running"
    assert (await _protocols(client, auth_headers, project_id))[launch["id"]] == {
        "status": "awaiting",
        "session_id": session_id,
        "task_status": None,
    }


async def test_protocol_rejected_launch_is_not_applicable(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    launch = await _report(client, auth_headers, launch["id"], launch["version"], "rejected")
    assert launch["status"] == "rejected"
    assert (await _protocols(client, auth_headers, project_id))[launch["id"]] == {
        "status": "not_applicable",
        "session_id": None,
        "task_status": None,
    }


async def _cancel(
    client: AsyncClient, headers: dict[str, str], launch: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/task-launches/{launch['id']}/cancel",
        json={"expected_version": launch["version"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_protocol_cancelled_before_running_is_not_applicable(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    for reported in ("accepted", "preparing"):
        launch = await _report(client, auth_headers, launch["id"], launch["version"], reported)
    launch = await _cancel(client, auth_headers, launch)
    assert (await _protocols(client, auth_headers, project_id))[launch["id"]] == {
        "status": "not_applicable",
        "session_id": None,
        "task_status": None,
    }


async def test_protocol_cancelled_while_running_is_unverified(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    for reported in ("accepted", "preparing", "running"):
        launch = await _report(client, auth_headers, launch["id"], launch["version"], reported)
    launch = await _cancel(client, auth_headers, launch)
    assert launch["status"] == "cancelled"
    assert (await _protocols(client, auth_headers, project_id))[launch["id"]] == {
        "status": "unverified",
        "session_id": None,
        "task_status": None,
    }


async def _blocked_handoff(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    task_id: str,
    session_id: str,
) -> dict[str, Any]:
    task = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert task.status_code == 200, task.text
    response = await client.post(
        "/api/v1/handoff",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": project_id,
            "session_id": session_id,
            "expected_version": task.json()["version"],
            "task_status": {"status": "blocked"},
        },
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_protocol_handoff_survives_the_late_terminal_report(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    launch = await _report(client, auth_headers, launch["id"], launch["version"], "accepted")
    session_id = await _open_session(client, auth_headers, task_id, machine_id)
    for reported in ("preparing", "running"):
        launch = await _report(client, auth_headers, launch["id"], launch["version"], reported)
    handoff = await _blocked_handoff(client, auth_headers, project_id, task_id, session_id)
    assert handoff["task_status"] == "blocked"
    assert (await _protocols(client, auth_headers, project_id))[launch["id"]] == {
        "status": "handed_off",
        "session_id": session_id,
        "task_status": "blocked",
    }
    finished = await _report(client, auth_headers, launch["id"], launch["version"], "succeeded")
    assert finished["status"] == "succeeded"
    assert (await _protocols(client, auth_headers, project_id))[launch["id"]] == {
        "status": "handed_off",
        "session_id": session_id,
        "task_status": "blocked",
    }
    assert await _task_status(client, auth_headers, task_id) == "blocked"


async def test_protocol_handoff_replay_keeps_the_same_proof(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    launch = await _report(client, auth_headers, launch["id"], launch["version"], "accepted")
    session_id = await _open_session(client, auth_headers, task_id, machine_id)
    launch = await _report(client, auth_headers, launch["id"], launch["version"], "preparing")
    task = await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert task.status_code == 200, task.text
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {
        "project_id": project_id,
        "session_id": session_id,
        "expected_version": task.json()["version"],
        "task_status": {"status": "blocked"},
    }
    first = await client.post("/api/v1/handoff", headers={**auth_headers, **key}, json=body)
    second = await client.post("/api/v1/handoff", headers={**auth_headers, **key}, json=body)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    assert (await _protocols(client, auth_headers, project_id))[launch["id"]] == {
        "status": "handed_off",
        "session_id": session_id,
        "task_status": "blocked",
    }


async def test_by_id_read_has_no_protocol(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    launch = (await _launch(client, auth_headers, project_id, task_id, machine_id)).json()
    response = await client.get(f"/api/v1/task-launches/{launch['id']}", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert "protocol" not in response.json()
