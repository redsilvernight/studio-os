from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from studio_client.knowledge import KnowledgeIndex, VaultKnowledgeProvider
from studio_client.knowledge.obsidian import ObsidianProbe
from studio_contracts.local.common import ComponentState
from studio_contracts.local.knowledge import KnowledgeReindexRequest

from tests.knowledge.factories import WORKSPACE_ID, make_vault

NO_OBSIDIAN = ObsidianProbe(state=ComponentState.NOT_INSTALLED)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return make_vault(tmp_path)


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


def build_provider(
    vault: Path,
    cache_dir: Path,
    *,
    workspace_id: UUID = WORKSPACE_ID,
    indexed: bool = True,
) -> VaultKnowledgeProvider:
    index = KnowledgeIndex(cache_dir / "knowledge-index", workspace_id=workspace_id)
    provider = VaultKnowledgeProvider(
        workspace_id=workspace_id, vault_root=vault, index=index, obsidian=NO_OBSIDIAN
    )
    if indexed:
        provider.reindex(KnowledgeReindexRequest(workspace_id=workspace_id))
    return provider
