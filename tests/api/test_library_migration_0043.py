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
NULLABLE = (
    "select is_nullable from information_schema.columns "
    "where table_name = 'events' and column_name = 'project_id'"
)
CHECKS = (
    "select count(*) from information_schema.table_constraints "
    "where table_name = 'events' and constraint_name = 'ck_events_project_scope'"
)


def _alembic(action: str, revision: str) -> None:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    getattr(command, action)(config, revision)


@pytest.mark.infra
@pytest.mark.timeout(300)
async def test_0043_upgrade_and_downgrade_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    base = urlsplit(os.environ["STUDIO_TEST_DATABASE_URL"])
    name = f"mig0043_{uuid.uuid4().hex[:8]}"
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
    try:
        await asyncio.to_thread(_alembic, "upgrade", "0043")
        conn = await asyncpg.connect(url.replace("+asyncpg", ""))
        try:
            assert await conn.fetchval(NULLABLE) == "YES"
            assert await conn.fetchval(CHECKS) == 1
            # The CHECK only lets project-less rows be library.*.
            await conn.execute(
                "insert into events (id, event_type, project_id, actor_type, actor_id,"
                " client_timestamp, server_timestamp, payload, schema_version)"
                " values (gen_random_uuid(), 'library.version.activated', NULL,"
                " 'user', gen_random_uuid(), now(), now(), '{}', 2)"
            )
            with pytest.raises(Exception, match="ck_events_project_scope"):
                await conn.execute(
                    "insert into events (id, event_type, project_id, actor_type, actor_id,"
                    " client_timestamp, server_timestamp, payload, schema_version)"
                    " values (gen_random_uuid(), 'task.created', NULL,"
                    " 'user', gen_random_uuid(), now(), now(), '{}', 1)"
                )
            # The downgrade restores NOT NULL: no project-less row may remain.
            await conn.execute("delete from events where project_id is null")
        finally:
            await conn.close()
        await asyncio.to_thread(_alembic, "downgrade", "0042")
        conn = await asyncpg.connect(url.replace("+asyncpg", ""))
        try:
            assert await conn.fetchval(NULLABLE) == "NO"
            assert await conn.fetchval(CHECKS) == 0
        finally:
            await conn.close()
        await asyncio.to_thread(_alembic, "upgrade", "0043")
        conn = await asyncpg.connect(url.replace("+asyncpg", ""))
        try:
            assert await conn.fetchval(NULLABLE) == "YES"
            assert await conn.fetchval(CHECKS) == 1
        finally:
            await conn.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
