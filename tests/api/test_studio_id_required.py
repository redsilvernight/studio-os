"""0049 follow-up: no default on `studio_id`, and one internal-studio id everywhere."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.studio import INTERNAL_STUDIO_ID

VERSIONS = Path(__file__).resolve().parents[2] / "services" / "api" / "alembic" / "versions"


def _migration_constant(filename: str) -> str:
    spec = importlib.util.spec_from_file_location(filename, VERSIONS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.INTERNAL_STUDIO_ID)


@pytest.mark.parametrize("filename", ["0046_studios.py", "0049_drop_studio_default.py"])
def test_internal_studio_id_matches_the_model_constant(filename: str) -> None:
    assert _migration_constant(filename) == str(INTERNAL_STUDIO_ID)


async def test_an_insert_without_studio_id_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("INSERT INTO projects (id, slug, name) VALUES (:id, :slug, 'x')"),
                {"id": uuid.uuid4(), "slug": f"no-studio-{uuid.uuid4().hex[:8]}"},
            )
