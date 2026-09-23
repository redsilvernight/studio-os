from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

from studio_client.knowledge import KnowledgeIndex, VaultKnowledgeProvider, initialize_vault
from studio_contracts.local.graph import GraphPageRequest
from studio_contracts.local.knowledge import KnowledgeReindexRequest, KnowledgeSearchRequest
from studio_contracts.local.workspace import KnowledgeConfig

from tests.knowledge.conftest import NO_OBSIDIAN
from tests.knowledge.factories import WORKSPACE_ID, write

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_knowledge_stack_never_opens_a_connection(tmp_path: Path, monkeypatch: object) -> None:
    def denied(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the knowledge stack attempted a network connection")

    socket.socket.connect = denied  # type: ignore[method-assign]
    socket.create_connection = denied  # type: ignore[assignment]
    try:
        vault = tmp_path / "vault"
        initialize_vault(vault)
        write(vault / "projects/demo/note.md", "# Note\n\ncontent here\n")
        index = KnowledgeIndex(tmp_path / "cache", workspace_id=WORKSPACE_ID)
        provider = VaultKnowledgeProvider(
            workspace_id=WORKSPACE_ID, vault_root=vault, index=index, obsidian=NO_OBSIDIAN
        )
        assert provider.status().state.value in {"unavailable", "ready", "stale", "indexing"}
        assert provider.reindex(KnowledgeReindexRequest(workspace_id=WORKSPACE_ID)).accepted
        result = provider.search(KnowledgeSearchRequest(workspace_id=WORKSPACE_ID, query="content"))
        assert result.hits
        uri = result.hits[0].document.uri
        from studio_contracts.local.knowledge import KnowledgeGetDocumentRequest

        assert provider.get_document(KnowledgeGetDocumentRequest(uri=uri)).markdown
        assert provider.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID)).nodes
    finally:
        del socket.socket.connect
        del socket.create_connection


def test_importing_the_knowledge_package_pulls_no_http_client() -> None:
    script = (
        "import sys\n"
        "import studio_client.knowledge\n"
        "forbidden = [name for name in ('httpx', 'requests', 'urllib.request') "
        "if name in sys.modules]\n"
        "print(','.join(forbidden))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == ""


def test_the_workspace_config_carries_no_secret() -> None:
    config = KnowledgeConfig(
        provider_id="markdown-files", content_root="vault", index=_index_location()
    )
    dumped = config.model_dump_json()
    assert "token" not in dumped
    assert "secret" not in dumped


def _index_location() -> object:
    from studio_contracts.local.workspace import IndexLocation

    return IndexLocation(directory_name="knowledge-index")
