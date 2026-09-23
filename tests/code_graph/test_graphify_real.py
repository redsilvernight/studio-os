from __future__ import annotations

from pathlib import Path

import pytest
from studio_code_graph import CodeGraphService, ProbeState
from studio_code_graph.graphify import GraphifyProvider
from studio_contracts.local.common import ComponentState
from studio_contracts.local.graph import Confidence, NodeKind, RelationKind

from .support import WORKSPACE_ID, commit_all, git, init_repo, make_config, write

PROVIDER = GraphifyProvider()
AVAILABLE = PROVIDER.probe().state is ProbeState.AVAILABLE

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="graphify executable not installed")

REAL_FILES = {
    "pkg/__init__.py": "",
    "pkg/base.py": "class Base:\n    def run(self):\n        return 1\n",
    "pkg/child.py": (
        "from pkg.base import Base\n\n\n"
        "class Child(Base):\n    def go(self):\n        return helper()\n\n\n"
        "def helper():\n    return 2\n"
    ),
    "main.py": (
        "from pkg.child import Child, helper\n\n\ndef main():\n    return Child().go() + helper()\n"
    ),
}


def real_service(tmp_path: Path) -> CodeGraphService:
    return CodeGraphService(
        [GraphifyProvider()],
        tmp_path / "cache",
        debounce_seconds=0.0,
        freshness_ttl_seconds=0.0,
        probe_ttl_seconds=0.0,
        build_timeout_seconds=240.0,
    )


async def indexed(
    tmp_path: Path, files: dict[str, str] | None = None
) -> tuple[CodeGraphService, Path]:
    repo = init_repo(tmp_path / "ws" / "app", files or REAL_FILES)
    service = real_service(tmp_path)
    await service.configure(make_config({"app": repo}, provider_id="graphify"))
    await service.wait_idle()
    return service, repo


async def all_nodes_and_edges(service: CodeGraphService):
    from studio_contracts.local.graph import GraphPageRequest

    page = await service.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID, limit=500))
    return page


async def test_probe_reports_a_supported_version() -> None:
    probe = PROVIDER.probe()
    assert probe.state is ProbeState.AVAILABLE and probe.version


async def test_real_index_is_ready_and_leaves_the_repo_untouched(tmp_path: Path) -> None:
    service, repo = await indexed(tmp_path)
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY, status.error
    assert status.provider is not None and status.provider.provider_id == "graphify"
    assert not (repo / "graphify-out").exists()
    assert git(repo, "status", "--porcelain") == ""


async def test_real_graph_has_files_symbols_and_provenance(tmp_path: Path) -> None:
    service, _ = await indexed(tmp_path)
    page = await all_nodes_and_edges(service)
    kinds = {node.kind for node in page.nodes}
    assert {NodeKind.FILE, NodeKind.CLASS, NodeKind.FUNCTION} <= kinds
    labels = {node.label for node in page.nodes}
    assert {"Base", "Child", "helper", "main"} <= {label.split(".")[-1] for label in labels}
    for node in page.nodes:
        assert node.uri.startswith("studio-local://") or node.uri
        assert node.provenance.source_id and node.provenance.extractor
    for edge in page.edges:
        assert edge.provenance.confidence in set(Confidence)
        if edge.provenance.confidence is Confidence.INFERRED:
            assert edge.provenance.evidence


async def test_real_graph_relations_are_only_supported_ones(tmp_path: Path) -> None:
    service, _ = await indexed(tmp_path)
    page = await all_nodes_and_edges(service)
    supported = {
        RelationKind.CONTAINS,
        RelationKind.IMPORTS,
        RelationKind.CALLS,
        RelationKind.INHERITS,
    }
    assert {edge.kind for edge in page.edges} <= supported
    assert RelationKind.CONTAINS in {edge.kind for edge in page.edges}


async def test_real_index_is_deterministic(tmp_path: Path) -> None:
    first, _ = await indexed(tmp_path / "a")
    second, _ = await indexed(tmp_path / "b")
    one = await all_nodes_and_edges(first)
    two = await all_nodes_and_edges(second)
    assert {node.label for node in one.nodes} == {node.label for node in two.nodes}
    assert len(one.edges) == len(two.edges)


async def test_real_incremental_update_after_a_commit(tmp_path: Path) -> None:
    service, repo = await indexed(tmp_path)
    before = await all_nodes_and_edges(service)
    write(repo, "extra.py", "def extra():\n    return 3\n")
    commit_all(repo, "extra")
    from types import SimpleNamespace

    await service.on_git_change(SimpleNamespace(repo_path=repo))
    await service.wait_idle()
    after = await all_nodes_and_edges(service)
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY
    assert "extra" in {node.label.split(".")[-1] for node in after.nodes}
    assert len(after.nodes) > len(before.nodes)


async def test_real_deleted_file_disappears(tmp_path: Path) -> None:
    service, repo = await indexed(tmp_path)
    git(repo, "rm", "-q", "pkg/child.py")
    git(repo, "commit", "-q", "-m", "drop child")
    from types import SimpleNamespace

    await service.on_git_change(SimpleNamespace(repo_path=repo))
    await service.wait_idle()
    page = await all_nodes_and_edges(service)
    assert "Child" not in {node.label.split(".")[-1] for node in page.nodes}


async def test_real_renamed_file_is_followed(tmp_path: Path) -> None:
    service, repo = await indexed(tmp_path)
    git(repo, "mv", "pkg/base.py", "pkg/root.py")
    git(repo, "commit", "-q", "-m", "rename")
    from types import SimpleNamespace

    await service.on_git_change(SimpleNamespace(repo_path=repo))
    await service.wait_idle()
    page = await all_nodes_and_edges(service)
    labels = {node.label for node in page.nodes}
    assert "pkg/root.py" in labels and "pkg/base.py" not in labels


async def test_real_branch_change(tmp_path: Path) -> None:
    service, repo = await indexed(tmp_path)
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "feature.py", "def only_on_feature():\n    return 4\n")
    commit_all(repo, "feature")
    from types import SimpleNamespace

    await service.on_git_change(SimpleNamespace(repo_path=repo))
    await service.wait_idle()
    on_feature = {n.label.split(".")[-1] for n in (await all_nodes_and_edges(service)).nodes}
    assert "only_on_feature" in on_feature
    git(repo, "checkout", "-q", "main")
    await service.on_git_change(SimpleNamespace(repo_path=repo))
    await service.wait_idle()
    on_main = {n.label.split(".")[-1] for n in (await all_nodes_and_edges(service)).nodes}
    assert "only_on_feature" not in on_main
