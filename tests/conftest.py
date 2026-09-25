from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "contracts" / "fixtures"

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
