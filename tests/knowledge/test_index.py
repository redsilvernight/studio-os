from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

import pytest
from studio_client.knowledge.errors import KnowledgeError
from studio_client.knowledge.index import KnowledgeIndex
from studio_contracts.local.provider import IndexState

from tests.knowledge.factories import WORKSPACE_ID, write


def build_index(tmp_path: Path, vault: Path) -> KnowledgeIndex:
    return KnowledgeIndex(tmp_path / "cache/knowledge-index", workspace_id=WORKSPACE_ID)


def _rowid(index: KnowledgeIndex, relative_path: str) -> int:
    connection = sqlite3.connect(index.path)
    try:
        row = connection.execute(
            "SELECT rowid FROM documents WHERE relative_path = ?", (relative_path,)
        ).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        connection.close()


def test_full_rebuild_reports_ready(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    assert index.snapshot(vault).state is IndexState.ABSENT
    snapshot = index.rebuild(vault, full=True)
    assert snapshot.state is IndexState.READY
    assert snapshot.item_count == 5
    assert snapshot.built_at is not None


def test_empty_vault_indexes_as_ready(tmp_path: Path) -> None:
    empty = tmp_path / "empty-vault"
    empty.mkdir()
    index = build_index(tmp_path, empty)
    snapshot = index.rebuild(empty, full=True)
    assert snapshot.state is IndexState.READY
    assert snapshot.item_count == 0


def test_incremental_rebuild_keeps_untouched_documents(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    untouched = _rowid(index, "projects/demo/intro.md")
    changed = _rowid(index, "projects/demo/design.md")
    write(vault / "projects/demo/design.md", "# Game design\n\nrewritten\n")
    index.rebuild(vault, full=False)
    assert _rowid(index, "projects/demo/intro.md") == untouched
    assert _rowid(index, "projects/demo/design.md") != changed


def test_added_document_becomes_searchable(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    write(vault / "global/roadmap.md", "# Roadmap\n\nmilestone zebra\n")
    index.rebuild(vault, full=False)
    hits, _ = index.search("zebra", limit=10)
    assert [hit.relative_path for hit in hits] == ["global/roadmap.md"]


def test_modified_document_replaces_its_content(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    write(vault / "projects/demo/combat.md", "# Combat rules\n\ninitiative octopus\n")
    index.rebuild(vault, full=False)
    hits, _ = index.search("octopus", limit=10)
    assert [hit.relative_path for hit in hits] == ["projects/demo/combat.md"]
    old_hits, _ = index.search("damage", limit=10)
    assert old_hits == []


def test_deleted_document_disappears_with_its_edges(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    assert index.document("projects/demo/combat.md") is not None
    (vault / "projects/demo/combat.md").unlink()
    index.rebuild(vault, full=False)
    assert index.document("projects/demo/combat.md") is None
    graph = index.graph()
    labels = {node.label for node in graph.nodes}
    assert "Combat rules" not in labels


def test_modified_vault_without_reindex_is_stale(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    write(vault / "global/late.md", "# Late\n")
    assert index.snapshot(vault).state is IndexState.STALE


def test_index_is_deletable_and_rebuildable(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    first = index.graph()
    assert index.drop() is True
    assert not index.path.exists()
    assert index.snapshot(vault).state is IndexState.ABSENT
    index.rebuild(vault, full=True)
    second = index.graph()
    assert [(node.node_id, node.kind) for node in second.nodes] == [
        (node.node_id, node.kind) for node in first.nodes
    ]
    assert [edge.edge_id for edge in second.edges] == [edge.edge_id for edge in first.edges]


def test_a_corrupt_index_is_reported_then_repaired(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    index.path.write_bytes(b"this is not a database")
    assert index.snapshot(vault).state is IndexState.CORRUPT
    snapshot = index.rebuild(vault, full=True)
    assert snapshot.state is IndexState.READY


def test_a_missing_index_file_is_absent(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    index.path.unlink()
    assert index.snapshot(vault).state is IndexState.ABSENT


def test_link_resolution_is_demonstrated_not_guessed(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    graph = index.graph()
    pairs = {
        (edge.kind.value, edge.source_node_id, edge.target_node_id, edge.extractor)
        for edge in graph.edges
    }
    by_uri = {node.uri: node.node_id for node in graph.nodes if node.uri}
    intro = by_uri[
        "studio-local://knowledge/11111111-1111-4111-8111-111111111111/projects/demo/intro.md"
    ]
    design = by_uri[
        "studio-local://knowledge/11111111-1111-4111-8111-111111111111/projects/demo/design.md"
    ]
    combat = by_uri[
        "studio-local://knowledge/11111111-1111-4111-8111-111111111111/projects/demo/combat.md"
    ]
    style = by_uri[
        "studio-local://knowledge/11111111-1111-4111-8111-111111111111/conventions/style.md"
    ]
    assert ("links_to", intro, design, "markdown_links") in pairs
    assert ("links_to", intro, combat, "markdown_wikilinks") in pairs
    assert ("links_to", style, combat, "markdown_links") in pairs
    anchor = [
        edge
        for edge in graph.edges
        if edge.source_node_id == design and edge.kind.value == "links_to"
    ]
    assert len(anchor) == 1
    assert anchor[0].extractor == "markdown_links"
    assert anchor[0].target_node_id != intro
    assert anchor[0].evidence_uri is not None and anchor[0].evidence_uri.endswith("#L5")


def test_external_and_missing_links_create_no_edge(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    write(
        vault / "global/orphan.md",
        "# Orphan\n\n[web](https://example.test/x) and [gone](missing.md) and [[nowhere]]\n",
    )
    index.rebuild(vault, full=True)
    graph = index.graph()
    by_uri = {node.uri: node.node_id for node in graph.nodes if node.uri}
    orphan = by_uri[
        "studio-local://knowledge/11111111-1111-4111-8111-111111111111/global/orphan.md"
    ]
    link_edges = [
        edge
        for edge in graph.edges
        if edge.source_node_id == orphan and edge.kind.value in ("links_to", "embeds")
    ]
    assert link_edges == []


def test_search_is_bounded_and_paginated(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    for number in range(5):
        write(vault / f"global/note-{number}.md", f"# Note {number}\n\nshared keyword\n")
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    first, cursor = index.search("shared keyword", limit=2)
    assert len(first) == 2
    assert cursor is not None
    second, _ = index.search("shared keyword", limit=2, cursor=cursor)
    assert len(second) == 2
    assert {hit.uri for hit in first}.isdisjoint({hit.uri for hit in second})


def test_indexing_never_touches_user_files(tmp_path: Path, vault: Path) -> None:
    before = {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob("*.md")}
    index = build_index(tmp_path, vault)
    index.rebuild(vault, full=True)
    index.search("combat", limit=5)
    index.graph()
    after = {path.relative_to(vault).as_posix(): path.read_bytes() for path in vault.rglob("*.md")}
    assert after == before


def test_unparsable_frontmatter_is_skipped_not_fatal(tmp_path: Path, vault: Path) -> None:
    index = build_index(tmp_path, vault)
    write(vault / "global/broken.md", "---\ntags: [unclosed\n---\n# Broken\n")
    snapshot = index.rebuild(vault, full=True)
    assert snapshot.state is IndexState.READY
    assert index.document("global/broken.md") is None
    assert index.document("projects/demo/intro.md") is not None


def test_workspace_identifier_is_part_of_every_uri(tmp_path: Path, vault: Path) -> None:
    other = UUID("99999999-9999-4999-8999-999999999999")
    index = KnowledgeIndex(tmp_path / "cache/knowledge-index", workspace_id=other)
    index.rebuild(vault, full=True)
    hits, _ = index.search("combat", limit=5)
    assert all(str(other) in hit.uri for hit in hits)


def test_rebuilding_a_missing_vault_is_refused(tmp_path: Path) -> None:
    index = build_index(tmp_path, tmp_path / "absent")
    with pytest.raises(KnowledgeError) as error:
        index.rebuild(tmp_path / "absent", full=True)
    assert error.value.reason == KnowledgeError.VAULT_MISSING
    assert index.snapshot(tmp_path / "absent").state is IndexState.ABSENT
