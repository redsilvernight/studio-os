from __future__ import annotations

import time
from pathlib import Path

from studio_client.knowledge.index import KnowledgeIndex
from studio_client.knowledge.provider import VaultKnowledgeProvider
from studio_contracts.local.graph import GraphPageRequest
from studio_contracts.local.knowledge import KnowledgeSearchRequest
from studio_contracts.local.provider import IndexState

from tests.knowledge.conftest import NO_OBSIDIAN
from tests.knowledge.factories import WORKSPACE_ID, write

DOCUMENTS = 300
INDEX_BUDGET_SECONDS = 30.0
QUERY_BUDGET_SECONDS = 5.0


def _significant_vault(root: Path) -> Path:
    vault = root / "vault"
    for number in range(DOCUMENTS):
        write(
            vault / f"projects/demo/note-{number:04d}.md",
            f"---\ntags: [batch]\n---\n# Note {number}\n\n"
            f"Shared corpus line {number}. Links to [[note-{(number + 1) % DOCUMENTS:04d}]].\n",
        )
    return vault


def test_a_significant_vault_stays_within_budget(tmp_path: Path) -> None:
    vault = _significant_vault(tmp_path)
    index = KnowledgeIndex(tmp_path / "cache", workspace_id=WORKSPACE_ID)
    provider = VaultKnowledgeProvider(
        workspace_id=WORKSPACE_ID, vault_root=vault, index=index, obsidian=NO_OBSIDIAN
    )
    started = time.perf_counter()
    snapshot = index.rebuild(vault, full=True)
    index_seconds = time.perf_counter() - started
    assert snapshot.state is IndexState.READY
    assert snapshot.item_count == DOCUMENTS
    assert index_seconds < INDEX_BUDGET_SECONDS

    started = time.perf_counter()
    result = provider.search(
        KnowledgeSearchRequest(workspace_id=WORKSPACE_ID, query="shared corpus", limit=20)
    )
    query_seconds = time.perf_counter() - started
    assert len(result.hits) == 20
    assert query_seconds < QUERY_BUDGET_SECONDS

    page = provider.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID, limit=100))
    assert len(page.nodes) == 100
    assert page.truncated is True
    assert page.counts.total_nodes is not None and page.counts.total_nodes >= DOCUMENTS
