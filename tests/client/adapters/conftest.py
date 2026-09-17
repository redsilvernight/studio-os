from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def _clean_client_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Mirror the isolation from the parent conftest for adapter-only tests."""
    monkeypatch.delenv("STUDIO_CLIENT_API_BASE_URL", raising=False)
    monkeypatch.delenv("STUDIO_CLIENT_MACHINE_TOKEN", raising=False)
    monkeypatch.delenv("STUDIO_CLIENT_KNOWLEDGE_VAULT_PATH", raising=False)
    monkeypatch.delenv("STUDIO_CLIENT_KNOWLEDGE_GRAPH_DIR", raising=False)
    monkeypatch.delenv("STUDIO_CLIENT_KNOWLEDGE_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("STUDIO_CLIENT_KNOWLEDGE_SCOPE_ALLOW", raising=False)
    monkeypatch.setenv("STUDIO_CLIENT_CONFIG_FILE", str(tmp_path / "unused-config.toml"))


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[Any]:
    """No-op override: adapter tests are pure and offline, no PostgreSQL."""
    yield None


@pytest_asyncio.fixture
async def db_session(engine: Any) -> AsyncIterator[Any]:
    """No-op override: adapter tests create no rows."""
    yield None


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_transfer_storage(db_session: Any) -> AsyncIterator[None]:
    """No-op override: adapter tests create no transfers."""
    yield
