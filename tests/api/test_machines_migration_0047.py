"""Migration 0047: `machines.studio_id` is optional, references `studios.id`
with `ON DELETE RESTRICT`, and the migration is reversible without touching
machine rows. Real PostgreSQL."""

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


def _alembic(action: str, revision: str) -> None:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    getattr(command, action)(config, revision)


def _asyncpg_url(url: str) -> str:
    return url.replace("+asyncpg", "")


@pytest.mark.infra
@pytest.mark.timeout(300)
async def test_0047_machine_studio_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    base = urlsplit(os.environ["STUDIO_TEST_DATABASE_URL"])
    name = f"mig0047_{uuid.uuid4().hex[:8]}"
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
    machine_id = uuid.uuid4()
    try:
        await asyncio.to_thread(_alembic, "upgrade", "0046")
        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            await conn.execute(
                "INSERT INTO users (id, version, display_name, email, role) "
                "VALUES ($1, 1, 'Machine Owner', 'owner@example.test', 'developer')",
                user_id,
            )
            await conn.execute(
                "INSERT INTO machines "
                "(id, version, owner_user_id, display_name, credential_hash) "
                "VALUES ($1, 1, $2, 'Test machine', 'hash')",
                machine_id,
                user_id,
            )
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "upgrade", "0047")
        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            column = await conn.fetchrow(
                "select is_nullable from information_schema.columns "
                "where table_name = 'machines' and column_name = 'studio_id'"
            )
            assert column is not None
            assert column["is_nullable"] == "YES"

            delete_rule = await conn.fetchval(
                "select confdeltype::text from pg_constraint "
                "where conrelid = 'machines'::regclass and contype = 'f' "
                "and pg_get_constraintdef(oid) like '%%studios(id)%%'"
            )
            assert delete_rule == "r"

            indexes = await conn.fetch(
                "select indexname from pg_indexes where tablename = 'machines'"
            )
            assert "ix_machines_studio_id" in {row["indexname"] for row in indexes}

            # A machine that never chose a studio keeps NULL; once attached, the
            # studio cannot be deleted underneath it.
            assert (
                await conn.fetchval("select studio_id from machines where id = $1", machine_id)
                is None
            )
            await conn.execute(
                "UPDATE machines SET studio_id = $1 WHERE id = $2",
                uuid.UUID(INTERNAL_STUDIO_ID),
                machine_id,
            )
            with pytest.raises(asyncpg.exceptions.IntegrityConstraintViolationError):
                await conn.execute(
                    "delete from studios where id = $1", uuid.UUID(INTERNAL_STUDIO_ID)
                )
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "downgrade", "0046")
        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            assert (
                await conn.fetchval(
                    "select 1 from information_schema.columns "
                    "where table_name = 'machines' and column_name = 'studio_id'"
                )
                is None
            )
            assert await conn.fetchval("select count(*) from machines") == 1
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "upgrade", "0047")
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
