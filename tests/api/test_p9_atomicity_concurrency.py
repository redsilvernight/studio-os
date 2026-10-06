from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.user import UserModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import provisioning as provisioning_service

from tests.api.test_claims_concurrency import _warm_pool, real_client, real_engine
from tests.api.test_task_launches import _caps, _heartbeat

__all__ = ["real_client", "real_engine"]


@pytest_asyncio.fixture
async def world(
    real_engine: AsyncEngine, real_client: AsyncClient
) -> AsyncIterator[tuple[dict[str, str], str, str, str]]:
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup:
        user = await provisioning_service.create_user(
            setup, "P9 Atomicity User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(
            setup, user.id, "p9-atomicity-machine"
        )
    headers = {"Authorization": f"Bearer {token}"}
    project = await real_client.post(
        "/api/v1/projects",
        json={"slug": f"p9-{uuid.uuid4().hex[:8]}", "name": "P9"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    task = await real_client.post(
        "/api/v1/tasks", json={"project_id": project_id, "title": "t"}, headers=headers
    )
    assert task.status_code == 201, task.text
    await _heartbeat(real_client, headers, str(machine.id), _caps(project_id))
    try:
        yield headers, project_id, task.json()["id"], str(machine.id)
    finally:
        pid = uuid.UUID(project_id)
        async with session_factory() as cleanup:
            await cleanup.execute(delete(TaskLaunchModel).where(TaskLaunchModel.project_id == pid))
            await cleanup.execute(
                delete(EventModel).where(
                    or_(EventModel.project_id == pid, EventModel.machine_id == machine.id)
                )
            )
            await cleanup.execute(
                delete(WorkSessionModel).where(WorkSessionModel.machine_id == machine.id)
            )
            await cleanup.execute(delete(TaskModel).where(TaskModel.project_id == pid))
            await cleanup.execute(delete(ProjectModel).where(ProjectModel.id == pid))
            await cleanup.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup.commit()


async def _create_launch(
    client: AsyncClient, headers: dict[str, str], project_id: str, task_id: str, machine_id: str
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/projects/{project_id}/task-launches",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"task_id": task_id, "machine_id": machine_id, "harness_id": "claude-code"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_concurrent_report_and_cancel_accept_one_version_only(
    real_engine: AsyncEngine,
    real_client: AsyncClient,
    world: tuple[dict[str, str], str, str, str],
) -> None:
    headers, project_id, task_id, machine_id = world
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    for _ in range(5):
        launch = await _create_launch(real_client, headers, project_id, task_id, machine_id)
        version = launch["version"]
        await _warm_pool(session_factory, 6)
        responses = await asyncio.gather(
            *(
                real_client.post(
                    f"/api/v1/task-launches/{launch['id']}/report",
                    json={"expected_version": version, "status": "accepted"},
                    headers=headers,
                )
                for _ in range(3)
            ),
            *(
                real_client.post(
                    f"/api/v1/task-launches/{launch['id']}/cancel",
                    json={"expected_version": version},
                    headers=headers,
                )
                for _ in range(3)
            ),
        )
        codes = Counter(r.status_code for r in responses)
        assert codes[200] == 1, [r.text for r in responses]
        assert codes[409] == 5, [r.text for r in responses]
        async with session_factory() as check:
            row = (
                await check.execute(
                    select(TaskLaunchModel).where(TaskLaunchModel.id == uuid.UUID(launch["id"]))
                )
            ).scalar_one()
        assert row.version == version + 1


async def test_concurrent_emissions_never_exceed_the_session_quota(
    real_engine: AsyncEngine,
    real_client: AsyncClient,
    world: tuple[dict[str, str], str, str, str],
) -> None:
    headers, _project_id, task_id, machine_id = world
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    opened = await real_client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"task_id": task_id, "machine_id": machine_id},
    )
    assert opened.status_code in {200, 201}, opened.text
    session_id = opened.json()["id"]
    attempts = 30
    await _warm_pool(session_factory, attempts)
    responses = await asyncio.gather(
        *(
            real_client.post(
                "/api/v1/coordination",
                headers=headers,
                json={
                    "from_session_id": session_id,
                    "intent": "heads_up",
                    "task_id": task_id,
                    "text": f"n{i}",
                },
            )
            for i in range(attempts)
        )
    )
    codes = Counter(r.status_code for r in responses)
    assert codes[201] == 20, [r.text for r in responses if r.status_code not in (201, 429)]
    assert codes[429] == attempts - 20
