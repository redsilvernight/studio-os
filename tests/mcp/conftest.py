from __future__ import annotations

import os
import sys
import uuid
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from mcp.server.mcpserver import Context
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

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _src in (
    "services/api/src",
    "services/mcp/src",
    "packages/studio-contracts/src",
    "packages/studio-client/src",
    "packages/studio-code-graph/src",
    "packages/studio-workspaces/src",
):
    _p = str(_REPO_ROOT / _src)
    if _p not in sys.path:
        sys.path.insert(0, _p)

TEST_DATABASE_URL = os.environ.get(
    "STUDIO_TEST_DATABASE_URL",
    "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test",
)


@pytest.fixture(autouse=True)
def _no_stray_machine_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own shell may export `STUDIO_MCP_MACHINE_TOKEN` for real
    use — strip it here so a test asserting `unauthenticated` isn't silently
    authenticated by an unrelated env var. Tests that need the stdio fallback
    set it explicitly via `monkeypatch.setenv`."""
    monkeypatch.delenv("STUDIO_MCP_MACHINE_TOKEN", raising=False)


class FakeContext(Context[dict[str, Any], Any]):
    """Stand-in for `mcp.server.mcpserver.Context` in tests: the tools under
    test only ever read `.headers` (see `studio_mcp.auth`), never anything
    else the real Context exposes — so this is all a test needs. Subclasses
    the real `Context` (rather than duck-typing it) so it type-checks as one;
    `headers` is a read-only property upstream, backed here by a private
    attribute set via `object.__setattr__` to bypass pydantic's `BaseModel`
    field validation."""

    if TYPE_CHECKING:
        _fake_headers: Mapping[str, str] | None

    def __init__(self, headers: Mapping[str, str] | None = None) -> None:
        super().__init__()
        object.__setattr__(self, "_fake_headers", headers)

    @property
    def headers(self) -> Mapping[str, str] | None:
        return self._fake_headers


@pytest_asyncio.fixture(scope="session", loop_scope="session")
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


async def start_test_session(
    task_id: str, ctx: Context, agent_id: str | None = None
) -> dict[str, Any]:
    """Open a work session through the same service and auth path as
    `POST /sessions`, without claiming the task. The MCP tool that did this
    (`studio_start_session`) was removed (DEC-0186); `studio_start_work` also
    claims the task, which tests needing several sessions on one task or a
    session without an agent cannot use."""
    from studio_api.services import sessions as sessions_service
    from studio_api.services.authz import Principal
    from studio_contracts.sessions import WorkSessionCreate
    from studio_mcp.errors import run_tool

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_task = uuid.UUID(task_id)
        parsed_agent = uuid.UUID(agent_id) if agent_id else None
        await sessions_service.authorize_start(session, principal, parsed_task, parsed_agent)
        work_session = await sessions_service.start_session(
            session,
            principal,
            WorkSessionCreate(
                task_id=parsed_task, machine_id=principal.machine.id, agent_id=parsed_agent
            ),
        )
        return {"id": str(work_session.id), "task_id": task_id}

    return await run_tool(ctx, _handler)
