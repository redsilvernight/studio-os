from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.user import UserModel
from studio_api.jwt_auth import create_access_token
from studio_api.services.authz import load_principal
from studio_api.services.task_launches import stage_launch
from studio_api.settings import get_settings
from studio_contracts.task_launch import TaskLaunchCreate

from tests.api.test_task_launches import _caps, _heartbeat, _launch, _ready_target


async def test_machine_token_cannot_approve_production(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
    admin_auth_headers: dict[str, str],
) -> None:
    project, task, target = await _ready_target(client, auth_headers, machine)
    for headers in (auth_headers, admin_auth_headers):
        response = await _launch(client, headers, project, task, target, allow_production=True)
        assert response.status_code == 403
        assert (
            response.json()["detail"]["error_code"] == "production_approval_requires_user_session"
        )
    assert (await db_session.execute(select(TaskLaunchModel))).scalars().all() == []


async def test_protected_launch_is_default_and_requires_safe_daemon(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project, task, target = await _ready_target(client, auth_headers, machine)
    await _heartbeat(client, auth_headers, target, _caps(project, launch_safety=None))
    refused = await _launch(client, auth_headers, project, task, target)
    assert refused.status_code == 409
    assert refused.json()["detail"]["error_code"] == "launch_safety_unsupported_by_machine"
    await _heartbeat(client, auth_headers, target, _caps(project))
    created = await _launch(client, auth_headers, project, task, target)
    assert created.status_code == 201, created.text
    row = await db_session.get(TaskLaunchModel, uuid.UUID(created.json()["id"]))
    assert row is not None and row.allow_production is False
    await _heartbeat(client, auth_headers, target, _caps(project, launch_safety=False))
    pending = await client.get(
        f"/api/v1/machines/{target}/task-launches/pending", headers=auth_headers
    )
    assert pending.status_code == 200
    assert pending.json()["items"] == []


async def test_human_approval_is_persisted_idempotent_and_not_inherited(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project, task, target = await _ready_target(client, auth_headers, machine)
    user = await db_session.get(UserModel, machine[0].owner_user_id)
    assert user is not None
    token = create_access_token(user, machine[0], get_settings())
    human = {"Authorization": f"Bearer {token}"}
    key = f"production-{uuid.uuid4()}"
    created = await _launch(client, human, project, task, target, key=key, allow_production=True)
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    assert body["allow_production"] is True
    repeated = await _launch(client, human, project, task, target, key=key, allow_production=True)
    assert repeated.json()["id"] == body["id"]
    machine_replay = await _launch(
        client, auth_headers, project, task, target, key=key, allow_production=True
    )
    assert machine_replay.status_code == 403
    row = await db_session.get(TaskLaunchModel, uuid.UUID(body["id"]))
    assert row is not None and row.allow_production is True
    row.status = "failed"
    await db_session.flush()
    retry = await client.post(
        f"/api/v1/task-launches/{row.id}/retry",
        headers=human,
        json={},
    )
    assert retry.status_code == 201, retry.text
    retried = await db_session.get(TaskLaunchModel, uuid.UUID(retry.json()["id"]))
    assert retried is not None and retried.allow_production is False


async def test_service_creation_cannot_bypass_human_approval(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    project, task, target = await _ready_target(client, auth_headers, machine)
    principal = await load_principal(db_session, machine[0])
    with pytest.raises(HTTPException) as error:
        await stage_launch(
            db_session,
            principal,
            uuid.UUID(project),
            TaskLaunchCreate(
                task_id=uuid.UUID(task),
                machine_id=uuid.UUID(target),
                harness_id="claude-code",
                allow_production=True,
            ),
        )
    assert error.value.status_code == 403
    assert error.value.detail["error_code"] == "production_approval_requires_user_session"
    assert (await db_session.execute(select(TaskLaunchModel))).scalars().all() == []
