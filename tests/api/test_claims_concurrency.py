from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.event import EventModel
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
    """Same rationale as `tests.api.test_idempotency_concurrency.real_engine`:
    each concurrent request needs its own independently-committing connection
    to genuinely race at Postgres, which the shared-savepoint `db_session`
    fixture cannot reproduce."""
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


async def test_concurrent_claims_on_same_resource_never_block(
    real_engine: AsyncEngine, real_client: AsyncClient
) -> None:
    """Non-negotiable project invariant (`.agents/rules/database.md`:
    a ResourceClaim warns, it never blocks Git) under genuine concurrency, not
    just sequential calls sharing one session (`tests/api/test_claims.py`):
    N callers claiming the identical resource_path at the same real instant
    must all succeed as `active` claims. Conflict detection
    (`resource.conflict` event) is soft and best-effort by design — it races
    with the other commits and is not asserted here, only that it never
    rejects or blocks a claim."""
    session_factory = async_sessionmaker(real_engine, expire_on_commit=False)
    async with session_factory() as setup_session:
        user = await provisioning_service.create_user(
            setup_session, "Claims Concurrency User", f"{uuid.uuid4()}@example.test", "developer"
        )
        machine, token = await provisioning_service.create_machine(
            setup_session, user.id, "claims-concurrency-machine"
        )
        project = await projects_service.create_project(
            setup_session, f"claims-concurrency-{uuid.uuid4().hex[:8]}", "Claims Concurrency", None
        )

    headers = {"Authorization": f"Bearer {token}"}
    resource_path = "scenes/shared_level.tscn"
    concurrency = 10

    try:
        await _warm_pool(session_factory, concurrency)
        responses = await asyncio.gather(
            *(
                real_client.post(
                    "/api/v1/claims",
                    headers=headers,
                    json={
                        "project_id": str(project.id),
                        "resource_path": resource_path,
                        "resource_type": "file",
                        "ttl_seconds": 600,
                    },
                )
                for _ in range(concurrency)
            )
        )

        for response in responses:
            assert response.status_code == 201, response.text
            assert response.json()["status"] == "active"
        claim_ids = {response.json()["id"] for response in responses}
        assert len(claim_ids) == concurrency, (
            f"each of the {concurrency} concurrent callers must get its own claim, "
            f"got {len(claim_ids)} distinct ids"
        )

        async with session_factory() as check_session:
            result = await check_session.execute(
                select(ResourceClaimModel).where(ResourceClaimModel.project_id == project.id)
            )
            claims = result.scalars().all()
        assert len(claims) == concurrency
        assert all(c.status == "active" for c in claims), (
            "no concurrently-created claim may end up rejected or blocked"
        )
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(EventModel).where(EventModel.project_id == project.id)
            )
            await cleanup_session.execute(
                delete(ResourceClaimModel).where(ResourceClaimModel.project_id == project.id)
            )
            await cleanup_session.execute(delete(ProjectModel).where(ProjectModel.id == project.id))
            await cleanup_session.execute(delete(MachineModel).where(MachineModel.id == machine.id))
            await cleanup_session.execute(delete(UserModel).where(UserModel.id == user.id))
            await cleanup_session.commit()
