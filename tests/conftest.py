from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import bcrypt
import pytest

# The API refuses a weak JWT secret in production (the default environment);
# set before any test imports studio_api.main, which builds the app on import.
os.environ.setdefault("STUDIO_ENVIRONMENT", "test")

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "contracts" / "fixtures"

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_test"
TEST_BCRYPT_ROUNDS = 4

_real_gensalt = bcrypt.gensalt


def _fast_gensalt(rounds: int = TEST_BCRYPT_ROUNDS, prefix: bytes = b"2b") -> bytes:
    return _real_gensalt(rounds, prefix)


bcrypt.gensalt = _fast_gensalt


def _clone_database(url: str, name: str, template: str) -> None:
    parts = urlsplit(url)

    async def _run() -> None:
        conn = await asyncpg.connect(
            host=parts.hostname,
            port=parts.port,
            user=parts.username,
            password=parts.password,
            database="postgres",
        )
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            for attempt in range(20):
                try:
                    await conn.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
                    return
                except asyncpg.ObjectInUseError:
                    if attempt == 19:
                        raise
                    time.sleep(0.25)
        finally:
            await conn.close()

    asyncio.run(_run())


def _resolve_test_database_url() -> str:
    """`localhost` costs ~2 s per connection on Windows (IPv6 tried first), so
    it is pinned to 127.0.0.1. Under pytest-xdist each worker gets its own
    copy of the configured, migrated test database, cloned fresh at startup."""
    configured = os.environ.get("STUDIO_TEST_DATABASE_URL")
    parts = urlsplit(configured or DEFAULT_TEST_DATABASE_URL)
    if parts.hostname == "localhost":
        parts = parts._replace(netloc=parts.netloc.replace("@localhost", "@127.0.0.1"))
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker and configured:
        template = parts.path.lstrip("/")
        name = f"{template}_{worker}"
        parts = parts._replace(path=f"/{name}")
        _clone_database(urlunsplit(parts), name, template)
    return urlunsplit(parts)


os.environ["STUDIO_TEST_DATABASE_URL"] = _resolve_test_database_url()

# Users whose name starts with this prefix never receive the automatic grants
# below: they are the "outsider" of the project isolation tests (DEC-0100).
OUTSIDER_PREFIX = "Outsider"


def load_fixture(name: str) -> list[dict[str, object]]:
    raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return cast(list[dict[str, object]], raw)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "isolation: real project isolation — no automatic memberships (DEC-0100)",
    )


@pytest.fixture(autouse=True)
def _backfilled_memberships(request: pytest.FixtureRequest) -> Iterator[None]:
    """Reproduces the 0014 backfill for the tests written before project
    isolation: every user created in the test (outsiders excepted) is a
    member of every project, whatever the creation order — through any
    session of the test, the app's own included. A Principal is loaded once
    and often before the test creates its project, so the scope of those
    members is the global one (projects created later, or none at all yet).
    Tests marked `isolation` get the real deny-by-default behavior."""
    if "db_session" not in request.fixturenames or request.node.get_closest_marker("isolation"):
        yield
        return

    from sqlalchemy import event, text
    from sqlalchemy.orm import Session
    from studio_api.db.models.project import ProjectModel
    from studio_api.db.models.user import UserModel
    from studio_api.services import authz, events

    db_session = request.getfixturevalue("db_session")
    if db_session is None:  # suites that stub the session out
        yield
        return

    def _grant(session: Any, _flush_context: Any) -> None:
        conn = session.connection()
        for obj in list(session.new):
            if isinstance(obj, ProjectModel):
                conn.execute(
                    text(
                        "INSERT INTO project_memberships (project_id, user_id) "
                        "SELECT :pid, u.id FROM users u WHERE u.display_name NOT LIKE :outsider "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"pid": obj.id, "outsider": f"{OUTSIDER_PREFIX}%"},
                )
            elif isinstance(obj, UserModel) and not obj.display_name.startswith(OUTSIDER_PREFIX):
                conn.execute(
                    text(
                        "INSERT INTO project_memberships (project_id, user_id) "
                        "SELECT p.id, :uid FROM projects p ON CONFLICT DO NOTHING"
                    ),
                    {"uid": obj.id},
                )

    real_scope = authz.load_project_scope

    async def _scope(session: Any, user_id: Any, role: Any) -> Any:
        user = await session.get(UserModel, user_id)
        if user is not None and user.display_name.startswith(OUTSIDER_PREFIX):
            return await real_scope(session, user_id, role)
        return authz.ALL_PROJECTS

    monkeypatch = request.getfixturevalue("monkeypatch")
    monkeypatch.setattr(authz, "load_project_scope", _scope)
    monkeypatch.setattr(events, "load_project_scope", _scope)
    event.listen(Session, "after_flush", _grant)
    try:
        yield
    finally:
        event.remove(Session, "after_flush", _grant)
