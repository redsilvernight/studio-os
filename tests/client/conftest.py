from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_client.config import ClientConfig
from studio_client.tokens import MemoryTokenStore

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@localhost:5432/studio_os_test",
)


@pytest.fixture(autouse=True)
def _clean_client_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolation from the developer's real shell/machine: a stray
    `STUDIO_CLIENT_*` env var or a real `%APPDATA%\\StudioOS\\config.toml`
    must never leak into this suite's precedence tests."""
    monkeypatch.delenv("STUDIO_CLIENT_API_BASE_URL", raising=False)
    monkeypatch.delenv("STUDIO_CLIENT_MACHINE_TOKEN", raising=False)
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(tmp_path / "unused-config.toml"))


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Real Postgres per `.claude/rules/database.md`, same isolation
    strategy as `tests/api/conftest.py` and `tests/mcp/conftest.py`."""
    test_engine = create_async_engine(TEST_DATABASE_URL)
    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with session_factory() as session:
            yield session
        await connection.rollback()


@pytest_asyncio.fixture
async def app_transport(db_session: AsyncSession) -> AsyncIterator[ASGITransport]:
    """The real FastAPI app, wired to an isolated test transaction — used
    only by the stage-2 anti-mock-drift tests (`.claude/rules/contracts.md`),
    never as a dependency of the `studio-client` package itself."""

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield ASGITransport(app=app)
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest_asyncio.fixture
async def machine(db_session: AsyncSession) -> tuple[MachineModel, str]:
    user = await provisioning_service.create_user(
        db_session, "Test User", f"{uuid.uuid4()}@example.test", "developer"
    )
    return await provisioning_service.create_machine(db_session, user.id, "test-machine")


@pytest_asyncio.fixture
async def project(db_session: AsyncSession) -> ProjectModel:
    return await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Test Project", None
    )


@pytest.fixture
def token_store(machine: tuple[MachineModel, str]) -> MemoryTokenStore:
    _, token = machine
    store = MemoryTokenStore()
    store.set_token("http://test", token)
    return store


@pytest.fixture
def client_config() -> ClientConfig:
    return ClientConfig(
        api_base_url="http://test",
        max_attempts=3,
        backoff_initial=0.001,
        backoff_max=0.002,
    )
