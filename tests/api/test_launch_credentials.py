from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel

from tests.api.test_task_launches import _launch, _ready_target


async def _accepted_launch(
    client: AsyncClient, headers: dict[str, str], machine: tuple[MachineModel, str]
) -> tuple[str, str, str]:
    project_id, task_id, machine_id = await _ready_target(client, headers, machine)
    created = await _launch(client, headers, project_id, task_id, machine_id)
    assert created.status_code == 201, created.text
    launch = created.json()
    accepted = await client.post(
        f"/api/v1/task-launches/{launch['id']}/report",
        json={"expected_version": launch["version"], "status": "accepted"},
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    return project_id, launch["id"], accepted.json()["id"]


async def _credential(
    client: AsyncClient, headers: dict[str, str], launch_id: str
) -> dict[str, str]:
    response = await client.post(f"/api/v1/task-launches/{launch_id}/credential", headers=headers)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


async def test_credential_reaches_only_the_allowlisted_routes(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, launch_id, _ = await _accepted_launch(client, auth_headers, machine)
    ephemeral = await _credential(client, auth_headers, launch_id)

    allowed = await client.get("/api/v1/agents", headers=ephemeral)
    assert allowed.status_code == 200, allowed.text

    for method, path in (
        ("GET", f"/api/v1/task-launches/{launch_id}"),
        ("GET", f"/api/v1/projects/{project_id}/task-launches"),
        ("GET", "/api/v1/projects"),
        ("POST", f"/api/v1/task-launches/{launch_id}/credential"),
    ):
        denied = await client.request(method, path, headers=ephemeral)
        assert denied.status_code == 403, (method, path, denied.text)
        assert denied.json()["detail"]["error_code"] == "launch_credential_scope"


async def test_credential_is_void_once_the_launch_is_terminal(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    _, launch_id, _ = await _accepted_launch(client, auth_headers, machine)
    ephemeral = await _credential(client, auth_headers, launch_id)
    assert (await client.get("/api/v1/agents", headers=ephemeral)).status_code == 200

    launch = (await client.get(f"/api/v1/task-launches/{launch_id}", headers=auth_headers)).json()
    failed = await client.post(
        f"/api/v1/task-launches/{launch_id}/report",
        json={"expected_version": launch["version"], "status": "failed"},
        headers=auth_headers,
    )
    assert failed.status_code == 200, failed.text

    assert (await client.get("/api/v1/agents", headers=ephemeral)).status_code == 401


async def test_credential_expires_with_the_launch(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    _, launch_id, _ = await _accepted_launch(client, auth_headers, machine)
    ephemeral = await _credential(client, auth_headers, launch_id)

    launch = await db_session.get(TaskLaunchModel, uuid.UUID(launch_id))
    assert launch is not None
    launch.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    assert (await client.get("/api/v1/agents", headers=ephemeral)).status_code == 401


async def test_reissuing_revokes_the_previous_credential(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    _, launch_id, _ = await _accepted_launch(client, auth_headers, machine)
    first = await _credential(client, auth_headers, launch_id)
    second = await _credential(client, auth_headers, launch_id)

    assert (await client.get("/api/v1/agents", headers=first)).status_code == 401
    assert (await client.get("/api/v1/agents", headers=second)).status_code == 200


async def test_only_the_target_machine_obtains_a_credential(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    _, launch_id, _ = await _accepted_launch(client, auth_headers, machine)
    _, other_token = other_machine

    response = await client.post(
        f"/api/v1/task-launches/{launch_id}/credential",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code in (403, 404), response.text


async def test_no_credential_before_the_launch_is_accepted(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    project_id, task_id, machine_id = await _ready_target(client, auth_headers, machine)
    created = await _launch(client, auth_headers, project_id, task_id, machine_id)
    launch_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/task-launches/{launch_id}/credential", headers=auth_headers
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error_code"] == "launch_not_active"


async def test_durable_token_is_unaffected(
    client: AsyncClient, auth_headers: dict[str, str], machine: tuple[MachineModel, str]
) -> None:
    _, launch_id, _ = await _accepted_launch(client, auth_headers, machine)
    await _credential(client, auth_headers, launch_id)

    response = await client.get("/api/v1/projects", headers=auth_headers)

    assert response.status_code == 200, response.text
