from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.project_membership import ProjectMembershipModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import projects, provisioning, tasks
from studio_api.services.authz import Principal, load_principal
from studio_contracts.tasks import TaskUpdate

pytestmark = pytest.mark.infra("postgres")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_transfer_storage() -> AsyncIterator[None]:
    yield


@pytest_asyncio.fixture
async def p0_task() -> AsyncIterator[tuple[AsyncEngine, Principal, TaskModel, str]]:
    configured = os.environ["STUDIO_TEST_DATABASE_URL"]
    url = make_url(configured)
    if url.host not in {"127.0.0.1", "localhost", "::1"} or "test" not in (url.database or ""):
        pytest.fail("P0 concurrency requires an explicitly configured local test database")
    engine = create_async_engine(configured)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        user = await provisioning.create_user(
            setup, "P0 Concurrent Writer", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning.create_machine(setup, user.id, "p0-writer")
        project = await projects.create_project(
            setup, f"p0-race-{uuid.uuid4().hex}", "P0 task race", None, creator=user
        )
        principal = await load_principal(setup, machine)
        task = TaskModel(project_id=project.id, title="Initial")
        setup.add(task)
        await setup.commit()
    try:
        yield engine, principal, task, token
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(EventModel).where(EventModel.project_id == project.id))
            await cleanup.execute(delete(TaskModel).where(TaskModel.id == task.id))
            await cleanup.execute(
                delete(ProjectMembershipModel).where(
                    ProjectMembershipModel.project_id == project.id
                )
            )
            await cleanup.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.parametrize("first_writer", [0, 1])
async def test_stale_independent_transactions_cannot_overwrite_committed_update(
    p0_task: tuple[AsyncEngine, Principal, TaskModel, str], first_writer: int
) -> None:
    engine, principal, initial, _ = p0_task
    factory = async_sessionmaker(engine, expire_on_commit=False)
    read_barrier = asyncio.Barrier(2)
    first_committed = asyncio.Event()

    async def write(index: int) -> tuple[int, object]:
        async with factory() as session:
            task = await session.get(TaskModel, initial.id)
            assert task is not None and task.version == initial.version
            await read_barrier.wait()
            if index != first_writer:
                await first_committed.wait()
            try:
                updated = await tasks.update_task(
                    session, principal, task, TaskUpdate(title=f"Writer {index}"), initial.version
                )
                return 200, updated.title
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code, exc.detail
            finally:
                if index == first_writer:
                    first_committed.set()

    outcomes = await asyncio.wait_for(asyncio.gather(write(0), write(1)), timeout=15)
    assert sorted(code for code, _ in outcomes) == [200, 409], outcomes
    assert outcomes[1 - first_writer][1] == {
        "error_code": "version_conflict",
        "server_version": initial.version + 1,
    }
    async with factory() as check:
        final = await check.get(TaskModel, initial.id)
        assert final is not None
        assert (final.title, final.version) == (f"Writer {first_writer}", initial.version + 1)
        count = await check.scalar(
            select(func.count()).select_from(EventModel).where(EventModel.task_id == initial.id)
        )
        assert count == 1


async def test_concurrent_http_updates_with_same_loaded_version_return_200_and_409(
    p0_task: tuple[AsyncEngine, Principal, TaskModel, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _, initial, token = p0_task
    factory = async_sessionmaker(engine, expire_on_commit=False)
    barrier = asyncio.Barrier(2)
    original_get = tasks.get_task

    async def synchronized_read(session: AsyncSession, task_id: uuid.UUID) -> TaskModel | None:
        task = await original_get(session, task_id)
        assert task is not None and task.version == initial.version
        await barrier.wait()
        return task

    async def independent_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    monkeypatch.setattr(tasks, "get_task", synchronized_read)
    previous = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = independent_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            responses = await asyncio.wait_for(
                asyncio.gather(
                    *(
                        client.patch(
                            f"/api/v1/tasks/{initial.id}",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "If-Match-Version": str(initial.version),
                            },
                            json={"title": f"HTTP writer {index}"},
                        )
                        for index in range(2)
                    )
                ),
                timeout=15,
            )
        assert sorted(response.status_code for response in responses) == [200, 409], [
            response.text for response in responses
        ]
        loser = next(response for response in responses if response.status_code == 409)
        assert loser.json()["detail"] == {
            "error_code": "version_conflict",
            "server_version": initial.version + 1,
        }
        winner = next(response for response in responses if response.status_code == 200).json()
        async with factory() as check:
            final = await check.get(TaskModel, initial.id)
            assert final is not None
            assert (final.title, final.version) == (winner["title"], initial.version + 1)
            assert (
                await check.scalar(
                    select(func.count())
                    .select_from(EventModel)
                    .where(EventModel.task_id == initial.id)
                )
                == 1
            )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = previous
