from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from studio_client.context.library import LibraryContextItem
from studio_client.skill_sync import apply_skill_sync, plan_skill_sync
from studio_contracts.library import (
    LibraryActivate,
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersionCreate,
)

from .conftest import DB_PREFIX, REBUILD_URL_ENV, SHARED_PG_PORT, World, _assert_isolated

pytestmark = pytest.mark.asyncio(loop_scope="session")

TABLES = (
    "library_resources",
    "library_resource_versions",
    "library_resource_links",
    "library_project_locks",
    "projects",
    "project_memberships",
    "users",
    "machines",
)


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        scoop = Path.home() / "scoop/apps/postgresql/current/bin" / f"{name}.exe"
        path = str(scoop) if scoop.exists() else None
    if path is None:
        pytest.skip(f"{name} not available")
    return path


def _run(args: list[str], url: str) -> None:
    parsed = make_url(url)
    env = {**os.environ, "PGPASSWORD": parsed.password or ""}
    done = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def _conn_args(url: str, dbname: str) -> list[str]:
    parsed = make_url(url)
    return ["-h", str(parsed.host), "-p", str(parsed.port), "-U", str(parsed.username), dbname]


async def _fingerprint(engine: AsyncEngine) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    async with engine.connect() as conn:
        for table in TABLES:
            row = (
                await conn.execute(
                    text(
                        f"select count(*), coalesce(md5(string_agg(t::text, '|' "
                        f"order by t::text)), '') from {table} t"
                    )
                )
            ).one()
            result[table] = (int(row[0]), str(row[1]))
    return result


def _tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".studio-os/backups" not in p.as_posix()
    }


def _skill(key: str, text_: str, version: int, files: dict[str, str]) -> LibraryContextItem:
    return LibraryContextItem(
        library_kind="skill",
        stable_key=key,
        version=version,
        version_origin="active",
        scope="studio",
        title=key,
        text=text_,
        content_schema="studio.library.skill/v1",
        files=tuple(files.items()),
    )


async def test_snapshot_mutate_restore_isolated(
    world: World, rebuilt: object, tmp_path: Path
) -> None:
    url = os.environ[REBUILD_URL_ENV]
    _assert_isolated(url)
    engine = world.engine
    async with engine.connect() as conn:
        port = (await conn.execute(text("select inet_server_port()"))).scalar_one()
        dbname = str((await conn.execute(text("select current_database()"))).scalar_one())
    assert port != SHARED_PG_PORT and dbname.startswith(DB_PREFIX)
    assert urlparse(url.replace("+asyncpg", "")).port == port

    admin, key = world.admin, f"snap-{uuid.uuid4().hex[:6]}"
    resource = await admin.client.create_library_resource(
        LibraryResourceCreate(
            kind=LibraryKind.SKILL,
            stable_key=key,
            scope=LibraryScope.STUDIO,
            title="snapshot probe",
            content={
                "content_schema": "studio.library.skill/v1",
                "text": "v1",
            },
        ),
        idempotency_key=str(uuid.uuid4()),
    )
    await admin.client.activate_library_version(
        resource.id,
        LibraryActivate(version=1, expected_resource_version=resource.version),
        idempotency_key=str(uuid.uuid4()),
    )
    lock = await admin.client._request(
        "POST",
        "/api/v1/library-locks",
        json={
            "project_id": str(world.project_id),
            "resource_id": str(resource.id),
            "locked_version": 1,
        },
        extra_headers={"Idempotency-Key": str(uuid.uuid4())},
        idempotent=True,
    )
    lock_id = lock.json()["id"]

    home = tmp_path / "home"
    apply_skill_sync(plan_skill_sync(home, [_skill(key, "v1", 1, {"r/a.md": "A1"})]))
    files_before = _tree(home)
    before = await _fingerprint(engine)
    assert all(
        count > 0 for table, (count, _) in before.items() if table != "library_resource_links"
    )

    dump = tmp_path / "snapshot.dump"
    _run(
        [_tool("pg_dump"), "-Fc", "--no-owner", "-f", str(dump), *_conn_args(url, dbname)],
        url,
    )
    assert dump.stat().st_size > 0

    await admin.client.create_library_version(
        resource.id,
        LibraryVersionCreate(
            title="snapshot probe",
            content={"content_schema": "studio.library.skill/v1", "text": "v2"},
        ),
        idempotency_key=str(uuid.uuid4()),
    )
    current = await admin.client.get_library_resource(resource.id)
    await admin.client.activate_library_version(
        resource.id,
        LibraryActivate(version=2, expected_resource_version=current.version),
        idempotency_key=str(uuid.uuid4()),
    )
    await admin.client._request("DELETE", f"/api/v1/library-locks/{lock_id}")
    await admin.client.create_library_resource(
        LibraryResourceCreate(
            kind=LibraryKind.SKILL,
            stable_key=f"{key}-extra",
            scope=LibraryScope.STUDIO,
            title="synthetic extra",
            content={"content_schema": "studio.library.skill/v1", "text": "x"},
        ),
        idempotency_key=str(uuid.uuid4()),
    )
    apply_skill_sync(plan_skill_sync(home, [_skill(key, "v2", 2, {"r/b.md": "B"})]))
    mutated = await _fingerprint(engine)
    assert mutated != before
    assert _tree(home) != files_before

    target = f"{DB_PREFIX}_restore_{uuid.uuid4().hex[:6]}"
    admin_url = make_url(url).set(database="postgres")
    maintenance = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    restored_engine: AsyncEngine | None = None
    try:
        async with maintenance.connect() as conn:
            await conn.execute(text(f'create database "{target}"'))
        _run(
            [
                _tool("pg_restore"),
                "--no-owner",
                "--exit-on-error",
                "-d",
                target,
                *_conn_args(url, target)[:-1],
                str(dump),
            ],
            url,
        )
        restored_url = make_url(url).set(database=target)
        _assert_isolated(restored_url.render_as_string(hide_password=False))
        restored_engine = create_async_engine(restored_url)
        assert await _fingerprint(restored_engine) == before
        async with restored_engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "select r.active_version, "
                        "(select count(*) from library_project_locks l "
                        " where l.resource_id = r.id and l.locked_version = 1), "
                        "(select count(*) from library_resources "
                        " where stable_key = :extra) "
                        "from library_resources r where r.stable_key = :key"
                    ),
                    {"key": key, "extra": f"{key}-extra"},
                )
            ).one()
        assert tuple(row) == (1, 1, 0)
    finally:
        if restored_engine is not None:
            await restored_engine.dispose()
        async with maintenance.connect() as conn:
            await conn.execute(text(f'drop database if exists "{target}" with (force)'))
        await maintenance.dispose()

    shutil.rmtree(home)
    home.mkdir()
    apply_skill_sync(plan_skill_sync(home, [_skill(key, "v1", 1, {"r/a.md": "A1"})]))
    assert _tree(home) == files_before
