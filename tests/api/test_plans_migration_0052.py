"""Migration 0052: plans catalogue, declarative limits, per-studio counters,
and the `studios.plan` foreign key — reversible."""

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
GIB = 1024**3
MIB = 1024**2


def _alembic(action: str, revision: str) -> None:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    getattr(command, action)(config, revision)


def _asyncpg_url(url: str) -> str:
    return url.replace("+asyncpg", "")


@pytest.mark.infra
@pytest.mark.timeout(300)
async def test_0052_upgrade_seeds_limits_and_downgrade_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = urlsplit(os.environ["STUDIO_TEST_DATABASE_URL"])
    name = f"mig0052_{uuid.uuid4().hex[:8]}"
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
        await asyncio.to_thread(_alembic, "upgrade", "0051")
        await asyncio.to_thread(_alembic, "upgrade", "0052")

        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            plans = await conn.fetch("select code, name, is_default from plans order by plan_rank")
            assert [(r["code"], r["name"], r["is_default"]) for r in plans] == [
                ("free", "Gratuit", True),
                ("pro", "Pro", False),
            ]

            limits = {
                (r["plan_code"], r["limit_key"]): r["max_value"]
                for r in await conn.fetch("select * from plan_limits")
            }
            assert limits[("free", "storage_bytes")] == 2 * GIB
            assert limits[("free", "file_size_bytes")] == 100 * MIB
            assert limits[("free", "vault_versions_per_note")] == 10
            assert limits[("free", "transfer_retention_days")] == 14
            assert limits[("free", "sse_connections")] == 5
            assert limits[("free", "requests_per_minute")] == 60
            assert limits[("free", "studios_per_account")] == 2
            assert limits[("free", "projects")] == 50
            assert limits[("free", "members")] == 10
            assert limits[("free", "machines")] == 5
            assert limits[("pro", "storage_bytes")] == 25 * GIB
            assert limits[("pro", "file_size_bytes")] == 5 * GIB
            assert limits[("pro", "vault_versions_per_note")] == 200
            assert limits[("pro", "transfer_retention_days")] == 90
            assert limits[("pro", "sse_connections")] == 50
            assert limits[("pro", "requests_per_minute")] == 600
            assert limits[("pro", "studios_per_account")] == 10
            assert limits[("pro", "projects")] is None
            assert limits[("pro", "machines")] is None

            # The studio seeded by 0046 still plans `free`, now with a FK.
            assert await conn.fetchval("select plan from studios") == "free"
            with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
                await conn.execute("update studios set plan = 'unknown'")

            # A counter row dies with its studio, never with a plan.
            await conn.execute(
                "insert into studio_plan_counters (studio_id, limit_key, value) "
                "select id, 'storage_bytes', 42 from studios limit 1"
            )
            assert await conn.fetchval("select value from studio_plan_counters") == 42
            assert await conn.fetchval("select count(*) from studio_plan_counters") == 1

            async def _counter_after_plan_delete() -> None:
                await conn.execute("delete from plan_limits where plan_code = 'pro'")
                await conn.execute("delete from plans where code = 'pro'")

            await _counter_after_plan_delete()
            assert await conn.fetchval("select count(*) from studio_plan_counters") == 1
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "downgrade", "0051")
        conn = await asyncpg.connect(_asyncpg_url(url))
        try:
            tables = await conn.fetch(
                "select table_name from information_schema.tables "
                "where table_name in ('plans', 'plan_limits', 'studio_plan_counters')"
            )
            assert tables == []
            fk = await conn.fetchval(
                "select count(*) from pg_constraint where conname = 'fk_studios_plan'"
            )
            assert fk == 0
            assert await conn.fetchval("select count(*) from studios") == 1
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, "upgrade", "0052")
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
