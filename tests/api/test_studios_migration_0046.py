from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

API_DIR = Path(__file__).resolve().parents[2] / "services" / "api"
INTERNAL_STUDIO_ID = "00000000-0000-0000-0000-000000000001"


def test_internal_studio_id_matches_the_model() -> None:
    """The seeded row and the model's server default must name the same tenant."""
    from studio_api.db.models.project import ProjectModel
    from studio_api.db.models.studio import INTERNAL_STUDIO_ID as model_studio_id

    assert str(model_studio_id) == INTERNAL_STUDIO_ID
    default = ProjectModel.__table__.c.studio_id.server_default
    assert default is not None
    assert INTERNAL_STUDIO_ID in str(default.arg)


def _alembic(action: str, revision: str) -> None:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    getattr(command, action)(config, revision)


def _asyncpg_url(url: str) -> str:
    return url.replace("+asyncpg", "")


@pytest.mark.infra
@pytest.mark.timeout(300)
async def test_0046_upgrade_backfill_and_downgrade_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = urlsplit(os.environ["STUDIO_TEST_DATABASE_URL"])
    name = f"mig0046_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(
        host=base.hostname,
        port=base.port,
        user=base.username,
        password=base.password,
        database="postgres",
    )
    await admin.execute(f'CREATE DATABASE "{name}"')
    url = urlunsplit(base._replace(path=f"/{name}"))
    monkeypatch.setenv("STUDIO_DATABASE_URL", url)
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    try:
        # Pre-existing data, before studios existed: the backfill must attach it.
        await asyncio.to_thread(_alembic, "upgrade", "0045")
        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            await conn.execute(
                "INSERT INTO users (id, version, display_name, email, role) "
                "VALUES ($1, 1, 'Backfill User', 'backfill@example.test', 'developer')",
                user_id,
            )
            await conn.execute(
                "INSERT INTO projects (id, version, slug, name, archived) "
                "VALUES ($1, 1, 'backfill-project', 'Backfill Project', false)",
                project_id,
            )
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "upgrade", "0046")
        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            tables = await conn.fetch(
                "select table_name from information_schema.tables "
                "where table_name in ('projects', 'studio_memberships', 'studios') "
                "order by 1"
            )
            assert [r[0] for r in tables] == ["projects", "studio_memberships", "studios"]

            studio_cols = await conn.fetch(
                "select column_name from information_schema.columns "
                "where table_name = 'studios' order by 1"
            )
            assert [r[0] for r in studio_cols] == [
                "created_at",
                "id",
                "is_internal",
                "name",
                "slug",
                "updated_at",
                "version",
            ]
            membership_cols = await conn.fetch(
                "select column_name from information_schema.columns "
                "where table_name = 'studio_memberships' order by 1"
            )
            assert [r[0] for r in membership_cols] == [
                "created_at",
                "granted_by_user_id",
                "studio_id",
                "user_id",
            ]

            studio = await conn.fetchrow(
                "select id, slug, name, is_internal from studios where id = $1",
                uuid.UUID(INTERNAL_STUDIO_ID),
            )
            assert studio is not None
            assert studio["is_internal"] is True
            assert studio["slug"] == "studio-os"

            column = await conn.fetchrow(
                "select is_nullable, column_default from information_schema.columns "
                "where table_name = 'projects' and column_name = 'studio_id'"
            )
            assert column is not None
            assert column["is_nullable"] == "NO"
            assert INTERNAL_STUDIO_ID in column["column_default"]

            project = await conn.fetchrow(
                "select studio_id from projects where id = $1", project_id
            )
            assert project is not None
            assert str(project["studio_id"]) == INTERNAL_STUDIO_ID

            membership = await conn.fetchrow(
                "select granted_by_user_id from studio_memberships "
                "where studio_id = $1 and user_id = $2",
                uuid.UUID(INTERNAL_STUDIO_ID),
                user_id,
            )
            assert membership is not None
            assert membership["granted_by_user_id"] is None
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "downgrade", "0045")
        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            tables = await conn.fetch(
                "select table_name from information_schema.tables "
                "where table_name in ('studio_memberships', 'studios')"
            )
            assert tables == []
            column = await conn.fetchrow(
                "select column_name from information_schema.columns "
                "where table_name = 'projects' and column_name = 'studio_id'"
            )
            assert column is None
            # The pre-existing rows survive the downgrade untouched.
            assert await conn.fetchval("select count(*) from projects") == 1
            assert await conn.fetchval("select count(*) from users") == 1
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "upgrade", "0046")
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
