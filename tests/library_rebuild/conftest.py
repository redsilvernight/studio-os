from __future__ import annotations

import os
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from studio_api.db.models.user import UserModel
from studio_api.db.session import get_session
from studio_api.main import app
from studio_api.services import projects as projects_service
from studio_api.services import provisioning as provisioning_service
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.tokens import MemoryTokenStore

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import library_import as li  # noqa: E402

REBUILD_URL_ENV = "STUDIO_LIBRARY_REBUILD_DATABASE_URL"
DB_PREFIX = "studio_lib_rebuild"
BASE_URL = "http://library-rebuild.test"
SHARED_PG_PORT = 5432


def _assert_isolated(url: str) -> None:
    parsed = urlparse(url.replace("+asyncpg", ""))
    assert parsed.hostname in {"127.0.0.1", "localhost", "::1"}, "host must be loopback"
    assert parsed.port not in (None, SHARED_PG_PORT), "shared PostgreSQL port refused"
    assert (parsed.path or "").lstrip("/").startswith(DB_PREFIX), "database name not isolated"


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    client: StudioApiClient


@dataclass(frozen=True)
class World:
    admin: Actor
    installer: Actor
    owner: Actor
    outsider: Actor
    readonly: Actor
    project_id: uuid.UUID
    outsider_project_id: uuid.UUID
    engine: AsyncEngine


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def rebuild_engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ.get(REBUILD_URL_ENV)
    if not url:
        pytest.skip(f"{REBUILD_URL_ENV} not set: isolated PostgreSQL required")
    _assert_isolated(url)
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        port = (await conn.execute(text("select inet_server_port()"))).scalar_one()
        dbname = (await conn.execute(text("select current_database()"))).scalar_one()
    assert port != SHARED_PG_PORT and str(dbname).startswith(DB_PREFIX)
    async with engine.begin() as conn:
        tables = (
            (
                await conn.execute(
                    text(
                        "select quote_ident(tablename) from pg_tables "
                        "where schemaname = 'public' and tablename <> 'alembic_version'"
                    )
                )
            )
            .scalars()
            .all()
        )
        await conn.execute(text(f"truncate {', '.join(tables)} restart identity cascade"))
    yield engine
    await engine.dispose()


async def _actor(sessions: async_sessionmaker[AsyncSession], role: str, label: str) -> Actor:
    async with sessions() as session:
        user = await provisioning_service.create_user(
            session, label, f"{label}-{uuid.uuid4().hex[:8]}@rebuild.test", role
        )
        _, token = await provisioning_service.create_machine(session, user.id, f"{label}-machine")
    store = MemoryTokenStore()
    store.set_token(BASE_URL, token)
    client = StudioApiClient(
        ClientConfig(api_base_url=BASE_URL),
        store,
        transport=ASGITransport(app=app),
    )
    return Actor(user.id, client)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def world(rebuild_engine: AsyncEngine) -> AsyncIterator[World]:
    sessions = async_sessionmaker(rebuild_engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    admin = await _actor(sessions, "admin", "admin")
    installer = await _actor(sessions, "developer", "installer")
    owner = await _actor(sessions, "developer", "owner")
    outsider = await _actor(sessions, "developer", "outsider")
    readonly = await _actor(sessions, "readonly", "readonly")
    async with sessions() as session:
        creator = await session.get(UserModel, admin.user_id)
        project = await projects_service.create_project(
            session, f"rebuild-{uuid.uuid4().hex[:8]}", "Rebuild test", None, creator=creator
        )
        for actor in (installer, owner):
            await projects_service.grant_member(
                session, project.id, actor.user_id, granted_by_user_id=admin.user_id
            )
        other = await projects_service.create_project(
            session, f"outsider-{uuid.uuid4().hex[:8]}", "Outsider project", None, creator=creator
        )
        await projects_service.grant_member(
            session, other.id, outsider.user_id, granted_by_user_id=admin.user_id
        )
    yield World(admin, installer, owner, outsider, readonly, project.id, other.id, rebuild_engine)
    app.dependency_overrides.pop(get_session, None)


EXPECTED = {"core": 38, "project": 2, "personal": 21}


def actor_for(world: World, layer: str) -> Actor:
    return {"core": world.admin, "project": world.installer, "personal": world.owner}[layer]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def rebuilt(world: World) -> dict[str, dict[str, int]]:
    report: dict[str, dict[str, int]] = {}
    for layer in ("core", "project", "personal"):
        plan = li.load_plan(layer)
        results = await li.import_plan(
            actor_for(world, layer).client,
            plan,
            project_id=world.project_id if layer == "project" else None,
        )
        assert len(results) == EXPECTED[layer]
        report[layer] = li.summarize(results)
    return report
