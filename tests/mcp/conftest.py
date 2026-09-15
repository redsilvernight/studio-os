from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db import session as db_session_module
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test",
)


@pytest_asyncio.fixture(autouse=True)
def _no_stray_machine_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own shell may export `STUDIO_MCP_MACHINE_TOKEN` for real
    use — strip it here so a test asserting `unauthenticated` isn't silently
    authenticated by an unrelated env var. Tests that need the stdio fallback
    set it explicitly via `monkeypatch.setenv`."""
    monkeypatch.delenv("STUDIO_MCP_MACHINE_TOKEN", raising=False)


class FakeContext:
    """Stand-in for `mcp.server.mcpserver.Context` in tests: the tools under
    test only ever read `.headers` (see `studio_mcp.auth`), never anything
    else the real Context exposes — so this is all a test needs."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    test_engine = create_async_engine(TEST_DATABASE_URL)
    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """One savepoint-nested transaction per test, same isolation strategy as
    `tests/api/conftest.py`. Also points `studio_api.db.session`'s module-level
    engine/session-factory singleton at this connection for the duration of
    the test: MCP tools call `get_session_factory()` directly (DEC-0005 — no
    FastAPI DI to override), so this is the only hook available to redirect
    them at the isolated test connection instead of a real database."""
    async with engine.connect() as connection:
        await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        previous_engine = db_session_module._engine
        previous_factory = db_session_module._session_factory
        db_session_module._engine = engine
        db_session_module._session_factory = session_factory
        try:
            async with session_factory() as session:
                yield session
        finally:
            db_session_module._engine = previous_engine
            db_session_module._session_factory = previous_factory
        await connection.rollback()


@pytest_asyncio.fixture
async def machine(db_session: AsyncSession) -> tuple[MachineModel, str]:
    user = await provisioning_service.create_user(
        db_session, "Test User", f"{uuid.uuid4()}@example.test", "developer"
    )
    return await provisioning_service.create_machine(db_session, user.id, "test-machine")


@pytest_asyncio.fixture
async def auth_ctx(machine: tuple[MachineModel, str]) -> FakeContext:
    _, token = machine
    return FakeContext(headers={"authorization": f"Bearer {token}"})


@pytest_asyncio.fixture
async def readonly_machine(db_session: AsyncSession) -> tuple[MachineModel, str]:
    user = await provisioning_service.create_user(
        db_session, "Readonly User", f"{uuid.uuid4()}@example.test", "readonly"
    )
    return await provisioning_service.create_machine(db_session, user.id, "readonly-machine")


@pytest_asyncio.fixture
async def readonly_auth_ctx(readonly_machine: tuple[MachineModel, str]) -> FakeContext:
    _, token = readonly_machine
    return FakeContext(headers={"authorization": f"Bearer {token}"})


@pytest_asyncio.fixture
async def other_machine(db_session: AsyncSession) -> tuple[MachineModel, str]:
    user = await provisioning_service.create_user(
        db_session, "Other User", f"{uuid.uuid4()}@example.test", "developer"
    )
    return await provisioning_service.create_machine(db_session, user.id, "other-machine")


@pytest_asyncio.fixture
async def other_auth_ctx(other_machine: tuple[MachineModel, str]) -> FakeContext:
    _, token = other_machine
    return FakeContext(headers={"authorization": f"Bearer {token}"})


@pytest_asyncio.fixture
async def admin_machine(db_session: AsyncSession) -> tuple[MachineModel, str]:
    user = await provisioning_service.create_user(
        db_session, "Admin User", f"{uuid.uuid4()}@example.test", "admin"
    )
    return await provisioning_service.create_machine(db_session, user.id, "admin-machine")


@pytest_asyncio.fixture
async def admin_ctx(admin_machine: tuple[MachineModel, str]) -> FakeContext:
    _, token = admin_machine
    return FakeContext(headers={"authorization": f"Bearer {token}"})


@pytest_asyncio.fixture
async def project(db_session: AsyncSession) -> ProjectModel:
    return await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Test Project", None
    )


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
