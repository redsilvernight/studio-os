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
TABLES = (
    "select table_name from information_schema.tables where table_name = 'project_repositories'"
)


def _alembic(action: str, revision: str) -> None:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    getattr(command, action)(config, revision)


@pytest.mark.infra
@pytest.mark.timeout(300)
async def test_0041_upgrade_and_downgrade_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    base = urlsplit(os.environ["STUDIO_TEST_DATABASE_URL"])
    name = f"mig0041_{uuid.uuid4().hex[:8]}"
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
        await asyncio.to_thread(_alembic, "upgrade", "0041")
        conn = await asyncpg.connect(url.replace("+asyncpg", ""))
        try:
            assert [r[0] for r in await conn.fetch(TABLES)] == ["project_repositories"]
            cols = await conn.fetch(
                "select column_name from information_schema.columns "
                "where table_name = 'project_repositories' order by 1"
            )
            assert [r[0] for r in cols] == [
                "created_at",
                "created_by",
                "id",
                "normalized_url",
                "project_id",
            ]
        finally:
            await conn.close()
        await asyncio.to_thread(_alembic, "downgrade", "0040")
        conn = await asyncpg.connect(url.replace("+asyncpg", ""))
        try:
            assert await conn.fetch(TABLES) == []
        finally:
            await conn.close()
        await asyncio.to_thread(_alembic, "upgrade", "0041")
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()
