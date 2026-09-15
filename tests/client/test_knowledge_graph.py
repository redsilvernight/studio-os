"""8.2 graph adapter tests. Every fixture is synthetic under `tmp_path` —
never the centralized `graphify-out`, on the explicit model of
`tests/graphify/test_vault_sync_and_lint.py`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from studio_client.knowledge import GraphifyGraphProvider, KnowledgeError

CLIENT = "pkg/client.py"
CONFIG = "pkg/config.py"
OTHER = "other/x.py"


def _node(node_id: str, label: str, source_file: str, location: str = "L1") -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "source_file": source_file,
        "source_location": location,
    }


def _link(source: str, target: str) -> dict[str, Any]:
    return {"source": source, "target": target, "relation": "calls", "confidence": "EXTRACTED"}


def _seed_source(root: Path) -> dict[str, float]:
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "other").mkdir(parents=True, exist_ok=True)
    client = root / CLIENT
    config = root / CONFIG
    client.write_text("class StudioApiClient: ...\n", encoding="utf-8")
    config.write_text("class ClientConfig: ...\n", encoding="utf-8")
    return {
        CLIENT: client.stat().st_mtime,
        CONFIG: config.stat().st_mtime,
    }


def _seed_graph(
    graph_dir: Path,
    mtimes: dict[str, float],
    *,
    with_manifest: bool = True,
    broken: bool = False,
) -> None:
    graph_dir.mkdir(parents=True, exist_ok=True)
    if broken:
        (graph_dir / "graph.json").write_text("{not json", encoding="utf-8")
        return
    graph = {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": [
            _node("n-client", "StudioApiClient", CLIENT, "L33"),
            _node("n-close", "StudioApiClient.close", CLIENT, "L70"),
            _node("n-config", "ClientConfig", CONFIG, "L27"),
            _node("n-other", "UnrelatedHelper", OTHER, "L5"),
        ],
        "links": [_link("n-close", "n-client"), _link("n-client", "n-config")],
    }
    (graph_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    if with_manifest:
        manifest = {path: {"mtime": mtime, "seen": mtime} for path, mtime in mtimes.items()}
        (graph_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _provider(tmp_path: Path) -> GraphifyGraphProvider:
    source_root = tmp_path / "src"
    graph_dir = tmp_path / "graph-out"
    _seed_graph(graph_dir, _seed_source(source_root))
    return GraphifyGraphProvider(graph_dir, source_root=source_root)


def test_query_matches_labels_and_respects_limit(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    result = provider.query("StudioApiClient")
    assert result.stale is False
    assert [node.label for node in result.nodes] == ["StudioApiClient", "StudioApiClient.close"]
    limited = provider.query("StudioApiClient", limit=1)
    assert len(limited.nodes) == 1


def test_query_empty_returns_empty(tmp_path: Path) -> None:
    assert _provider(tmp_path).query("   ").nodes == []


def test_relevant_files_topic(tmp_path: Path) -> None:
    result = _provider(tmp_path).relevant_files("ClientConfig")
    assert result.stale is False
    assert result.files == [CONFIG]


def test_relevant_files_covered_path_is_fresh(tmp_path: Path) -> None:
    result = _provider(tmp_path).relevant_files(CLIENT)
    assert result.stale is False
    assert result.stale_reason is None
    assert CLIENT in result.files


def test_relevant_files_uncovered_path_is_stale_not_silent(tmp_path: Path) -> None:
    result = _provider(tmp_path).relevant_files(OTHER)
    assert result.stale is True
    assert result.stale_reason == GraphifyGraphProvider.NOT_COVERED
    assert result.files == [OTHER]


def test_dependencies_returns_neighbour_files(tmp_path: Path) -> None:
    result = _provider(tmp_path).dependencies(CLIENT)
    assert result.stale is False
    assert result.files == [CONFIG]


def test_dependencies_uncovered_file_is_stale(tmp_path: Path) -> None:
    result = _provider(tmp_path).dependencies(OTHER)
    assert result.stale is True
    assert result.stale_reason == GraphifyGraphProvider.NOT_COVERED
    assert result.files == []


def test_changed_source_is_reported_stale(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    graph_dir = tmp_path / "graph-out"
    mtimes = _seed_source(source_root)
    _seed_graph(graph_dir, mtimes)
    provider = GraphifyGraphProvider(graph_dir, source_root=source_root)
    assert provider.dependencies(CLIENT).stale is False
    changed = source_root / CLIENT
    stamp = mtimes[CLIENT] + 100.0
    os.utime(changed, (stamp, stamp))
    result = provider.dependencies(CLIENT)
    assert result.stale is True
    assert result.stale_reason == GraphifyGraphProvider.CHANGED_SINCE_INDEXED
    assert result.files == [CONFIG]


def test_missing_graph_dir_degrades_to_stale(tmp_path: Path) -> None:
    provider = GraphifyGraphProvider(tmp_path / "no-such-dir")
    result = provider.query("anything")
    assert result.nodes == []
    assert result.stale is True
    assert result.stale_reason == GraphifyGraphProvider.GRAPH_MISSING
    assert GraphifyGraphProvider(None).dependencies(CLIENT).stale_reason == "graph_missing"


def test_missing_manifest_is_stale(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    graph_dir = tmp_path / "graph-out"
    _seed_graph(graph_dir, _seed_source(source_root), with_manifest=False)
    provider = GraphifyGraphProvider(graph_dir, source_root=source_root)
    result = provider.query("StudioApiClient")
    assert result.nodes != []
    assert result.stale is True
    assert result.stale_reason == GraphifyGraphProvider.MANIFEST_MISSING


def test_invalid_graph_json_is_stale(tmp_path: Path) -> None:
    graph_dir = tmp_path / "graph-out"
    _seed_graph(graph_dir, {}, broken=True)
    provider = GraphifyGraphProvider(graph_dir)
    result = provider.query("anything")
    assert result.nodes == []
    assert result.stale is True
    assert result.stale_reason == GraphifyGraphProvider.GRAPH_INVALID


def test_refresh_graph_is_unsupported_and_launches_nothing(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeError) as exc_info:
        _provider(tmp_path).refresh_graph()
    assert exc_info.value.reason == KnowledgeError.REFRESH_UNSUPPORTED


def test_related_symbols_by_file(tmp_path: Path) -> None:
    result = _provider(tmp_path).related_symbols(CLIENT)
    assert result.stale is False
    assert [node.label for node in result.nodes] == ["StudioApiClient", "StudioApiClient.close"]


def test_related_symbols_by_label_includes_neighbours(tmp_path: Path) -> None:
    result = _provider(tmp_path).related_symbols("ClientConfig")
    labels = [node.label for node in result.nodes]
    assert "ClientConfig" in labels
    assert "StudioApiClient" in labels


def test_related_symbols_uncovered_path_is_stale(tmp_path: Path) -> None:
    result = _provider(tmp_path).related_symbols(OTHER)
    assert result.stale is True
    assert result.stale_reason == GraphifyGraphProvider.NOT_COVERED
    assert [node.label for node in result.nodes] == ["UnrelatedHelper"]
