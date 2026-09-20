"""Roadmaps P10 end-to-end fixtures: the canonical HTTP surface *and* the real MCP
tools on one isolated Postgres transaction.

`tests.mcp.conftest.db_session` points the module-level session factory at the
test connection, which is what MCP tools use; the HTTP client below overrides
`get_session` with a *fresh* session per request from that same factory, exactly
like production (a session per request), so neither surface reads the other's
stale identity map."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db import session as db_session_module
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import provisioning as provisioning_service

from tests.mcp.conftest import FakeContext, db_session, engine  # noqa: F401


@dataclass(frozen=True)
class Actor:
    """One authenticated machine, reachable over both surfaces."""

    role: str
    user_id: uuid.UUID
    machine: MachineModel
    headers: dict[str, str]
    ctx: FakeContext


@pytest.fixture(autouse=True)
def _no_stray_machine_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIO_MCP_MACHINE_TOKEN", raising=False)


async def make_actor(db: AsyncSession, role: str, label: str | None = None) -> Actor:
    user = await provisioning_service.create_user(
        db, f"{label or role} user", f"{uuid.uuid4()}@example.test", role
    )
    machine, token = await provisioning_service.create_machine(db, user.id, f"{label or role}-box")
    bearer = {"authorization": f"Bearer {token}"}
    return Actor(
        role=role,
        user_id=user.id,
        machine=machine,
        headers={"Authorization": f"Bearer {token}"},
        ctx=FakeContext(headers=bearer),
    )


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:  # noqa: F811
    factory = db_session_module.get_session_factory()

    async def _per_request_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _per_request_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)


@pytest_asyncio.fixture
async def developer(db_session: AsyncSession) -> Actor:  # noqa: F811
    return await make_actor(db_session, "developer")


@pytest_asyncio.fixture
async def admin(db_session: AsyncSession) -> Actor:  # noqa: F811
    return await make_actor(db_session, "admin")


@pytest_asyncio.fixture
async def agent(db_session: AsyncSession) -> Actor:  # noqa: F811
    """A machine whose token has the `agent` role: it may read and propose, and
    can never review."""
    return await make_actor(db_session, "agent")


@pytest_asyncio.fixture
async def readonly(db_session: AsyncSession) -> Actor:  # noqa: F811
    return await make_actor(db_session, "readonly")


async def attach_agent(db: AsyncSession, actor: Actor, name: str = "worker") -> AgentModel:
    """A registered agent identity attached to `actor`'s machine (the declared
    `agent_id` of a write). Deliberately a neutral, non-vendor identity."""
    model = AgentModel(machine_id=actor.machine.id, display_name=name, agent_kind="generic")
    db.add(model)
    await db.flush()
    await db.refresh(model)
    return model
