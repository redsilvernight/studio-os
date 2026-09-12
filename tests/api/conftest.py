from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.security import generate_machine_token, hash_token

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test",
)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Real Postgres (per .claude/rules/database.md — SQLite never stands in for
    the shared source of state), pointed at a dedicated, pre-migrated test DB.

    Function-scoped: asyncpg connections are bound to the event loop they were
    created on, and pytest-asyncio hands each test its own loop — a
    session-scoped engine here would reuse pooled connections across loops and
    fail with "attached to a different loop"."""
    test_engine = create_async_engine(TEST_DATABASE_URL)
    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """One savepoint-nested transaction per test: app code calling
    `session.commit()` only releases the savepoint, the outer rollback at
    teardown undoes everything regardless — isolation without touching schema."""
    async with engine.connect() as connection:
        await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with session_factory() as session:
            yield session
        await connection.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)


@pytest_asyncio.fixture
async def machine(db_session: AsyncSession) -> tuple[MachineModel, str]:
    user = UserModel(
        display_name="Test User", email=f"{uuid.uuid4()}@example.test", role="developer"
    )
    db_session.add(user)
    await db_session.flush()

    token = generate_machine_token()
    machine_model = MachineModel(
        owner_user_id=user.id,
        display_name="test-machine",
        credential_hash=hash_token(token),
    )
    db_session.add(machine_model)
    await db_session.flush()
    await db_session.refresh(machine_model)
    return machine_model, token


@pytest_asyncio.fixture
async def auth_headers(machine: tuple[MachineModel, str]) -> dict[str, str]:
    _, token = machine
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def project(db_session: AsyncSession) -> ProjectModel:
    """Project creation has no endpoint yet (Bloc A scaffold gap) — seeded
    directly, same as an admin-provisioned project would be."""
    proj = ProjectModel(slug=f"proj-{uuid.uuid4().hex[:8]}", name="Test Project")
    db_session.add(proj)
    await db_session.flush()
    await db_session.refresh(proj)
    return proj


@pytest_asyncio.fixture
async def agent(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> AgentModel:
    machine_model, _ = machine
    agent_model = AgentModel(
        machine_id=machine_model.id, display_name="claude-code", agent_kind="claude_code"
    )
    db_session.add(agent_model)
    await db_session.flush()
    await db_session.refresh(agent_model)
    return agent_model
