from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_api.storage.provider import get_storage

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test",
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Real Postgres (per .claude/rules/database.md — SQLite never stands in for
    the shared source of state), pointed at a dedicated, pre-migrated test DB.

    Session-scoped so pooled connections are reused across tests: asyncpg
    connections are bound to their event loop, which is why every test and
    fixture runs on the single session loop (pyproject `asyncio_default_*`)."""
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


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_transfer_storage(db_session: AsyncSession) -> AsyncIterator[None]:
    """The savepoint rollback on `db_session` erases every `TransferModel`
    row a test created, but never touches the real MinIO objects/multipart
    uploads those transfers point at (.claude/rules/storage-transfers.md) -
    without this, the shared test bucket accumulates orphans across runs."""
    yield
    storage = get_storage()
    object_keys = (await db_session.execute(select(TransferModel.object_key))).scalars().all()
    for object_key in object_keys:
        for upload in await storage.list_multipart_uploads(prefix=object_key):
            if upload["key"] == object_key:
                await storage.abort_multipart_upload(object_key, str(upload["upload_id"]))
        await storage.delete_object(object_key)


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
    """Goes through `services/provisioning.py`, the same path as the real
    `POST /machines` and `studio-admin machine create` — keeps the fixture
    from silently drifting away from the real provisioning behavior."""
    user = await provisioning_service.create_user(
        db_session, "Test User", f"{uuid.uuid4()}@example.test", "developer"
    )
    return await provisioning_service.create_machine(db_session, user.id, "test-machine")


@pytest_asyncio.fixture
async def admin_auth_headers(db_session: AsyncSession) -> dict[str, str]:
    admin = await provisioning_service.create_user(
        db_session, "Admin", f"{uuid.uuid4()}@example.test", "admin"
    )
    _, token = await provisioning_service.create_machine(db_session, admin.id, "admin-machine")
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def auth_headers(machine: tuple[MachineModel, str]) -> dict[str, str]:
    _, token = machine
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def readonly_machine(db_session: AsyncSession) -> tuple[MachineModel, str]:
    user = await provisioning_service.create_user(
        db_session, "Readonly User", f"{uuid.uuid4()}@example.test", "readonly"
    )
    return await provisioning_service.create_machine(db_session, user.id, "readonly-machine")


@pytest_asyncio.fixture
async def readonly_auth_headers(readonly_machine: tuple[MachineModel, str]) -> dict[str, str]:
    _, token = readonly_machine
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def agent_machine(db_session: AsyncSession) -> tuple[MachineModel, str]:
    user = await provisioning_service.create_user(
        db_session, "Agent User", f"{uuid.uuid4()}@example.test", "agent"
    )
    return await provisioning_service.create_machine(db_session, user.id, "agent-machine")


@pytest_asyncio.fixture
async def agent_auth_headers(agent_machine: tuple[MachineModel, str]) -> dict[str, str]:
    _, token = agent_machine
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def other_machine(db_session: AsyncSession) -> tuple[MachineModel, str]:
    """A second developer-owned machine, distinct user — for ownership/access
    matrix tests (two users x two machines, per the audit's lot-3 acceptance
    criteria)."""
    user = await provisioning_service.create_user(
        db_session, "Other User", f"{uuid.uuid4()}@example.test", "developer"
    )
    return await provisioning_service.create_machine(db_session, user.id, "other-machine")


@pytest_asyncio.fixture
async def other_auth_headers(other_machine: tuple[MachineModel, str]) -> dict[str, str]:
    _, token = other_machine
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def project(db_session: AsyncSession) -> ProjectModel:
    return await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Test Project", None, creator=None
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
