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
SCOPED_TABLES = (
    "agents",
    "budget_policies",
    "decisions",
    "library_resources",
    "runtimes",
    "transfers",
    "vault_notes",
)


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


async def _column(conn: asyncpg.Connection, table: str, column: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "select is_nullable, column_default from information_schema.columns "
        "where table_name = $1 and column_name = $2",
        table,
        column,
    )


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
    admin_user_id = uuid.uuid4()
    member_user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    second_studio_id = uuid.uuid4()
    second_project_id = uuid.uuid4()
    internal_id = uuid.UUID(INTERNAL_STUDIO_ID)
    try:
        # Pre-existing data, before studios existed: the backfill must attach it.
        await asyncio.to_thread(_alembic, "upgrade", "0045")
        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            await conn.execute(
                "INSERT INTO users (id, version, display_name, email, role) VALUES "
                "($1, 1, 'Studio Admin', 'admin@example.test', 'admin'), "
                "($2, 1, 'Studio Member', 'member@example.test', 'developer')",
                admin_user_id,
                member_user_id,
            )
            await conn.execute(
                "INSERT INTO projects (id, version, slug, name, archived) "
                "VALUES ($1, 1, 'backfill-project', 'Backfill Project', false)",
                project_id,
            )
            await conn.execute(
                "INSERT INTO agents (id, version, display_name, agent_kind) "
                "VALUES ($1, 1, 'Backfill Agent', 'session')",
                agent_id,
            )
            await conn.execute(
                "INSERT INTO decisions "
                "(id, readable_id, title, body, status, proposed_by_type, proposed_by_id) "
                "VALUES ($1, 'DEC-9001', 'Backfill', 'Body', 'accepted', 'user', $2)",
                decision_id,
                admin_user_id,
            )
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "upgrade", "0046")
        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            tables = await conn.fetch(
                "select table_name from information_schema.tables "
                "where table_name in ('studio_memberships', 'studios') order by 1"
            )
            assert [r[0] for r in tables] == ["studio_memberships", "studios"]

            studio_cols = await conn.fetch(
                "select column_name from information_schema.columns "
                "where table_name = 'studios' order by 1"
            )
            assert [r[0] for r in studio_cols] == [
                "created_at",
                "id",
                "is_internal",
                "name",
                "plan",
                "slug",
                "status",
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
                "role",
                "studio_id",
                "user_id",
            ]

            studio = await conn.fetchrow(
                "select slug, plan, status, is_internal from studios where id = $1",
                internal_id,
            )
            assert studio is not None
            assert (studio["slug"], studio["plan"], studio["status"]) == (
                "studio-os",
                "free",
                "active",
            )
            assert studio["is_internal"] is True

            roles = await conn.fetch(
                "select user_id, role, granted_by_user_id from studio_memberships "
                "where studio_id = $1 order by role",
                internal_id,
            )
            assert [(r["user_id"], r["role"]) for r in roles] == [
                (member_user_id, "member"),
                (admin_user_id, "owner"),
            ]
            assert all(r["granted_by_user_id"] is None for r in roles)

            operator = await _column(conn, "users", "is_operator")
            assert operator is not None
            assert operator["is_nullable"] == "NO"
            assert await conn.fetchval("select bool_or(is_operator) from users") is False

            # projects.studio_id is NOT NULL with the internal studio as default.
            project_col = await _column(conn, "projects", "studio_id")
            assert project_col is not None
            assert project_col["is_nullable"] == "NO"
            assert INTERNAL_STUDIO_ID in project_col["column_default"]
            assert (
                str(await conn.fetchval("select studio_id from projects where id = $1", project_id))
                == INTERNAL_STUDIO_ID
            )

            # Every scoped table got the column, backfilled and NOT NULL.
            for table in SCOPED_TABLES:
                column = await _column(conn, table, "studio_id")
                assert column is not None, table
                assert column["is_nullable"] == "NO", table
                assert INTERNAL_STUDIO_ID in column["column_default"], table
            # FK is ON DELETE RESTRICT (PostgreSQL confdeltype 'r'), never CASCADE.
            for table in ("projects", *SCOPED_TABLES):
                delete_rule = await conn.fetchval(
                    "select confdeltype from pg_constraint "
                    "where conrelid = $1::regclass and contype = 'f' "
                    "and pg_get_constraintdef(oid) like '%%studios(id)%%'",
                    table,
                )
                assert delete_rule == "r", table
            with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
                await conn.execute("delete from studios where id = $1", internal_id)
            assert (
                str(await conn.fetchval("select studio_id from agents where id = $1", agent_id))
                == INTERNAL_STUDIO_ID
            )
            assert (
                str(
                    await conn.fetchval(
                        "select studio_id from decisions where id = $1", decision_id
                    )
                )
                == INTERNAL_STUDIO_ID
            )

            # Slug is unique per studio, not globally.
            await conn.execute(
                "INSERT INTO studios (id, slug, name) VALUES ($1, 'second-studio', 'Second')",
                second_studio_id,
            )
            await conn.execute(
                "INSERT INTO projects (id, version, studio_id, slug, name, archived) "
                "VALUES ($1, 1, $2, 'backfill-project', 'Other tenant project', false)",
                second_project_id,
                second_studio_id,
            )
            with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO projects (id, version, studio_id, slug, name, archived) "
                    "VALUES ($1, 1, $2, 'backfill-project', 'Duplicate slug', false)",
                    uuid.uuid4(),
                    second_studio_id,
                )
            constraints = await conn.fetch(
                "select conname from pg_constraint "
                "where conrelid = 'projects'::regclass and contype = 'u'"
            )
            assert [r[0] for r in constraints] == ["uq_projects_studio_slug"]
            # Leave no cross-studio duplicate for the (deliberately) strict downgrade.
            await conn.execute("delete from projects where id = $1", second_project_id)
            await conn.execute("delete from studios where id = $1", second_studio_id)
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
            assert await _column(conn, "projects", "studio_id") is None
            assert await _column(conn, "users", "is_operator") is None
            for table in SCOPED_TABLES:
                assert await _column(conn, table, "studio_id") is None, table

            constraints = await conn.fetch(
                "select conname from pg_constraint "
                "where conrelid = 'projects'::regclass and contype = 'u'"
            )
            assert [r[0] for r in constraints] == ["uq_projects_slug"]

            # The pre-existing rows survive the downgrade untouched.
            assert await conn.fetchval("select count(*) from projects") == 1
            assert await conn.fetchval("select count(*) from users") == 2
            assert await conn.fetchval("select count(*) from agents") == 1
            assert await conn.fetchval("select count(*) from decisions") == 1
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "upgrade", "0046")
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
