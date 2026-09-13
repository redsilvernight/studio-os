from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test",
)


@pytest_asyncio.fixture
async def real_engine() -> AsyncIterator[AsyncEngine]:
    """Separate real, independently-committing connections per request — see
    the identical fixture in test_idempotency_concurrency.py for why a
    savepoint-nested session (tests.api.conftest.db_session) cannot reproduce
    a race that only exists *across* Postgres transactions."""
    engine = create_async_engine(TEST_DATABASE_URL, pool_size=20, max_overflow=0)
    yield engine
    await engine.dispose()


async def _warm_pool(session_factory: async_sessionmaker[AsyncSession], count: int) -> None:
    async def _touch() -> None:
        async with session_factory() as session:
            await session.execute(text("select 1"))

    await asyncio.gather(*(_touch() for _ in range(count)))


@pytest_asyncio.fixture
async def real_client(real_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)


async def test_concurrent_decisions_get_unique_readable_ids(
    real_engine: AsyncEngine, real_client: AsyncClient
) -> None:
    """Regression test for 'Rendre les identifiants DEC-XXXX concurrents'
    (roadmap step 2): `_next_readable_id` used to be `COUNT(*) + 1`, so
    concurrent creations could read the same count before either had
    committed and collide on the same readable_id."""
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup_session:
        user = await provisioning_service.create_user(
            setup_session, "Decision Concurrency User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(
            setup_session, user.id, "decision-concurrency-machine"
        )
        project = await projects_service.create_project(
            setup_session, f"dec-concurrency-{uuid.uuid4().hex[:8]}", "Decision Concurrency", None
        )

    headers = {"Authorization": f"Bearer {token}"}
    concurrency = 10

    try:
        await _warm_pool(session_factory, concurrency)
        responses = await asyncio.gather(
            *(
                real_client.post(
                    "/api/v1/decisions",
                    headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
                    json={
                        "project_id": str(project.id),
                        "title": f"Concurrent decision {i}",
                        "body": "Body",
                        "proposed_by_type": "agent",
                        "proposed_by_id": str(machine.id),
                    },
                )
                for i in range(concurrency)
            )
        )

        for response in responses:
            assert response.status_code == 201, response.text
        readable_ids = [response.json()["readable_id"] for response in responses]
        assert len(set(readable_ids)) == concurrency, (
            f"all {concurrency} concurrent decisions must get distinct readable_ids, "
            f"got {readable_ids}"
        )
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(DecisionModel).where(DecisionModel.project_id == project.id)
            )
            await cleanup_session.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup_session.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup_session.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup_session.commit()
