from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from studio_client.knowledge import KnowledgeIndex, VaultKnowledgeProvider
from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.provider import disabled_knowledge_status
from studio_client.knowledge.scope import ScopePolicy
from studio_contracts.local.common import ComponentId, ComponentState, LocalErrorCode
from studio_contracts.local.graph import (
    GraphDirection,
    GraphExpandRequest,
    GraphNodeRef,
    GraphPageRequest,
    NodeKind,
    RelationKind,
)
from studio_contracts.local.knowledge import (
    KnowledgeGetDocumentRequest,
    KnowledgeReindexMode,
    KnowledgeReindexRequest,
    KnowledgeSearchRequest,
)
from studio_contracts.local.provider import IndexState

from tests.knowledge.conftest import NO_OBSIDIAN, build_provider
from tests.knowledge.factories import WORKSPACE_ID, write

OTHER_WORKSPACE = UUID("99999999-9999-4999-8999-999999999999")


def test_disabled_status_is_explicit() -> None:
    status = disabled_knowledge_status(WORKSPACE_ID)
    assert status.state is ComponentState.DISABLED
    assert status.provider is None
    assert status.index is None
    assert status.error is not None
    assert status.error.code is LocalErrorCode.FEATURE_DISABLED
    assert status.canonical_source == "markdown_files"


def test_missing_vault_is_unavailable_with_a_reason(tmp_path: Path) -> None:
    provider = build_provider(tmp_path / "absent", tmp_path, indexed=False)
    status = provider.status()
    assert status.state is ComponentState.UNAVAILABLE
    assert status.index is not None and status.index.state is IndexState.ABSENT
    assert status.error is not None
    assert status.error.code is LocalErrorCode.WORKSPACE_INACCESSIBLE
    assert status.error.component is ComponentId.KNOWLEDGE


def test_status_is_ready_then_stale_after_an_edit(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    assert provider.status().state is ComponentState.READY
    write(vault / "global/late.md", "# Late\n")
    assert provider.status().state is ComponentState.STALE


def test_status_reports_indexing_during_a_rebuild(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path, indexed=False)
    observed: list[ComponentState] = []
    provider.index.rebuild(
        vault, full=True, progress=lambda _: observed.append(provider.status().state)
    )
    assert ComponentState.INDEXING in observed
    assert provider.status().state is ComponentState.READY


def test_status_reports_a_corrupt_index(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    provider.index.path.write_bytes(b"not a database")
    status = provider.status()
    assert status.state is ComponentState.ERROR
    assert status.error is not None and status.error.code is LocalErrorCode.INDEX_CORRUPT


def test_obsidian_is_reported_as_an_optional_integration(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    integrations = provider.status().integrations
    assert [(item.integration_id, item.state) for item in integrations] == [
        ("obsidian", ComponentState.NOT_INSTALLED)
    ]
    assert integrations[0].required is False


def test_reindex_accepts_and_refuses(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path, indexed=False)
    accepted = provider.reindex(KnowledgeReindexRequest(workspace_id=WORKSPACE_ID))
    assert accepted.accepted is True
    assert accepted.operation_id is not None
    assert accepted.state is ComponentState.READY
    full = provider.reindex(
        KnowledgeReindexRequest(workspace_id=WORKSPACE_ID, mode=KnowledgeReindexMode.FULL_REBUILD)
    )
    assert full.accepted is True
    assert full.operation_id != accepted.operation_id


def test_reindex_is_refused_when_the_vault_is_gone(tmp_path: Path) -> None:
    provider = build_provider(tmp_path / "absent", tmp_path, indexed=False)
    refused = provider.reindex(KnowledgeReindexRequest(workspace_id=WORKSPACE_ID))
    assert refused.accepted is False
    assert refused.operation_id is None
    assert refused.state is ComponentState.UNAVAILABLE
    assert refused.error is not None


def test_reindex_is_refused_when_the_index_cannot_be_written(tmp_path: Path, vault: Path) -> None:
    blocked = write(tmp_path / "blocked", "not a directory\n")
    index = KnowledgeIndex(blocked / "knowledge-index", workspace_id=WORKSPACE_ID)
    provider = VaultKnowledgeProvider(
        workspace_id=WORKSPACE_ID, vault_root=vault, index=index, obsidian=NO_OBSIDIAN
    )
    refused = provider.reindex(KnowledgeReindexRequest(workspace_id=WORKSPACE_ID))
    assert refused.accepted is False
    assert refused.error is not None and refused.error.retryable is True


def test_search_returns_bounded_hits(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    result = provider.search(
        KnowledgeSearchRequest(workspace_id=WORKSPACE_ID, query="combat rules")
    )
    assert result.index_state is ComponentState.READY
    assert result.complete is True
    assert result.hits[0].document.title == "Combat rules"
    assert 0.0 <= result.hits[0].score <= 1.0
    assert len(result.hits[0].snippet) <= 300
    assert result.hits[0].document.uri.startswith("studio-local://knowledge/")


def test_search_on_an_unbuilt_index_is_incomplete(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path, indexed=False)
    result = provider.search(KnowledgeSearchRequest(workspace_id=WORKSPACE_ID, query="combat"))
    assert result.hits == []
    assert result.complete is False
    assert result.index_state is ComponentState.UNAVAILABLE


def test_search_on_a_stale_index_is_incomplete(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    write(vault / "global/late.md", "# Late\n")
    result = provider.search(KnowledgeSearchRequest(workspace_id=WORKSPACE_ID, query="combat"))
    assert result.index_state is ComponentState.STALE
    assert result.complete is False


def test_get_document_reads_canonical_markdown_from_disk(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    uri = "studio-local://knowledge/11111111-1111-4111-8111-111111111111/projects/demo/design.md"
    document = provider.get_document(KnowledgeGetDocumentRequest(uri=uri))
    assert document.document.title == "Game design"
    assert document.markdown == (vault / "projects/demo/design.md").read_text(encoding="utf-8")
    assert document.truncated is False
    assert document.outgoing_links


def test_get_document_truncates(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    uri = "studio-local://knowledge/11111111-1111-4111-8111-111111111111/projects/demo/intro.md"
    document = provider.get_document(KnowledgeGetDocumentRequest(uri=uri, max_bytes=10))
    assert document.truncated is True
    assert len(document.markdown) == 10


def test_get_document_refuses_unknown_and_out_of_scope(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    missing = (
        "studio-local://knowledge/11111111-1111-4111-8111-111111111111/projects/demo/absent.md"
    )
    with pytest.raises(KnowledgeError) as error:
        provider.get_document(KnowledgeGetDocumentRequest(uri=missing))
    assert error.value.reason == KnowledgeError.NOT_FOUND

    scoped = VaultKnowledgeProvider(
        workspace_id=WORKSPACE_ID,
        vault_root=vault,
        index=KnowledgeIndex(tmp_path / "cache/knowledge-index", workspace_id=WORKSPACE_ID),
        scope=ScopePolicy(("projects/demo/",)),
        obsidian=NO_OBSIDIAN,
    )
    outside = "studio-local://knowledge/11111111-1111-4111-8111-111111111111/templates/note.md"
    with pytest.raises(KnowledgeError) as scope_error:
        scoped.get_document(KnowledgeGetDocumentRequest(uri=outside))
    assert scope_error.value.reason == KnowledgeError.OUT_OF_SCOPE


def test_scope_filters_search(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    scoped = VaultKnowledgeProvider(
        workspace_id=WORKSPACE_ID,
        vault_root=vault,
        index=provider.index,
        scope=ScopePolicy(("conventions/",)),
        obsidian=NO_OBSIDIAN,
    )
    result = scoped.search(KnowledgeSearchRequest(workspace_id=WORKSPACE_ID, query="combat"))
    assert all("conventions/" in hit.document.uri for hit in result.hits)


def test_a_request_for_another_workspace_is_refused(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    with pytest.raises(KnowledgeError):
        provider.search(KnowledgeSearchRequest(workspace_id=OTHER_WORKSPACE, query="combat"))
    with pytest.raises(KnowledgeError):
        provider.reindex(KnowledgeReindexRequest(workspace_id=OTHER_WORKSPACE))
    with pytest.raises(KnowledgeError):
        provider.graph_page(GraphPageRequest(workspace_id=OTHER_WORKSPACE))


def test_graph_page_uses_the_common_schema(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    page = provider.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID))
    assert page.source.kind.value == "knowledge"
    assert page.source.provider_id == "markdown-files"
    assert page.source.index_fingerprint is not None
    assert {node.kind for node in page.nodes} <= {
        NodeKind.DOCUMENT,
        NodeKind.HEADING,
        NodeKind.TAG,
    }
    assert {edge.kind for edge in page.edges} <= {
        RelationKind.LINKS_TO,
        RelationKind.TAGGED_WITH,
        RelationKind.EMBEDS,
        RelationKind.CONTAINS,
    }
    assert page.counts.nodes == len(page.nodes)
    assert page.counts.edges == len(page.edges)
    assert page.counts.total_nodes == len(page.nodes)


def test_graph_provenance_is_present_and_truthful(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    page = provider.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID))
    for node in page.nodes:
        assert node.provenance.source_id == page.source.source_id
        assert node.provenance.extractor.startswith("markdown_")
        assert node.provenance.confidence.value == "extracted"
    for edge in page.edges:
        assert edge.provenance.source_id == page.source.source_id
        assert edge.provenance.evidence is not None
        assert edge.source.source_id == page.source.source_id


def test_graph_page_filters_node_kinds(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    page = provider.graph_page(
        GraphPageRequest(workspace_id=WORKSPACE_ID, node_kinds=[NodeKind.TAG])
    )
    assert page.nodes
    assert all(node.kind is NodeKind.TAG for node in page.nodes)


def test_graph_page_is_bounded_with_a_frontier(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    first = provider.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID, limit=2))
    assert len(first.nodes) == 2
    assert first.truncated is True
    assert first.next_cursor is not None
    assert first.frontier
    assert first.counts.total_nodes is not None and first.counts.total_nodes > 2
    second = provider.graph_page(
        GraphPageRequest(workspace_id=WORKSPACE_ID, limit=2, cursor=first.next_cursor)
    )
    assert {node.node_id for node in first.nodes}.isdisjoint(
        {node.node_id for node in second.nodes}
    )


def test_graph_expand_walks_one_hop(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    page = provider.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID))
    intro = next(node for node in page.nodes if node.label == "Introduction")
    expanded = provider.graph_expand(
        GraphExpandRequest(
            workspace_id=WORKSPACE_ID,
            node=GraphNodeRef(source_id=page.source.source_id, node_id=intro.node_id),
            direction=GraphDirection.OUT,
            relations=[RelationKind.LINKS_TO],
        )
    )
    assert any(node.node_id == intro.node_id for node in expanded.nodes)
    assert expanded.nodes
    assert all(edge.kind is RelationKind.LINKS_TO for edge in expanded.edges)


def test_graph_expand_refuses_a_foreign_node(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    with pytest.raises(KnowledgeError) as error:
        provider.graph_expand(
            GraphExpandRequest(
                workspace_id=WORKSPACE_ID,
                node=GraphNodeRef(source_id="code-main", node_id="doc:whatever"),
            )
        )
    assert error.value.reason == KnowledgeError.NOT_FOUND


def test_graph_page_without_an_index_is_empty(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path, indexed=False)
    page = provider.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID))
    assert page.nodes == []
    assert page.edges == []
    assert page.counts.nodes == 0
    assert page.source.kind.value == "knowledge"


def test_unsafe_titles_never_reach_the_contract(tmp_path: Path, vault: Path) -> None:
    write(vault / "global/secret.md", "---\ntitle: 'password: hunter2'\n---\n# S\n")
    write(vault / "global/pathlike.md", "---\ntitle: 'C:/Users/dev/notes'\n---\n# P\n")
    provider = build_provider(vault, tmp_path)
    page = provider.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID))
    labels = {node.label for node in page.nodes}
    assert "untitled" in labels
    result = provider.search(KnowledgeSearchRequest(workspace_id=WORKSPACE_ID, query="hunter2"))
    for hit in result.hits:
        assert "hunter2" not in hit.document.title
        assert "hunter2" not in hit.snippet
