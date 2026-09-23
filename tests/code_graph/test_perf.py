from __future__ import annotations

import os
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import pytest
from studio_code_graph import CodeGraphService, ProbeState
from studio_code_graph.graphify import GraphifyProvider
from studio_contracts.local.code_graph import CodeSymbolQuery
from studio_contracts.local.common import ComponentState
from studio_contracts.local.graph import GraphPageRequest

from .support import WORKSPACE_ID, commit_all, init_repo, make_config, make_service

REAL_PERF = os.environ.get("STUDIO_CODE_GRAPH_PERF") == "1"
SIZES = {"small": 10, "medium": 200, "large": 2000}


def generate(count: int) -> dict[str, str]:
    files: dict[str, str] = {}
    for index in range(count):
        package = f"pkg{index // 50}"
        neighbour = max(index - 1, 0)
        files[f"{package}/mod{index}.py"] = (
            f"from pkg{neighbour // 50}.mod{neighbour} import fn{neighbour}\n\n\n"
            f"class Holder{index}:\n    def method(self):\n        return fn{index}()\n\n\n"
            f"def fn{index}():\n    return fn{neighbour}() if {index} else 0\n"
        )
    return files


async def test_queries_never_reread_the_repository_or_rebuild(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "ws" / "app", generate(300))
    service, provider = make_service(tmp_path, freshness_ttl_seconds=30.0)
    await service.configure(make_config({"app": repo}))
    await service.wait_idle()
    assert len(provider.requests) == 1
    started = time.perf_counter()
    for _ in range(50):
        await service.status(WORKSPACE_ID)
        await service.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID, limit=100))
        await service.search_symbols(CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="fn1"))
    elapsed = time.perf_counter() - started
    assert len(provider.requests) == 1
    assert elapsed / 50 < 0.25


async def test_index_memory_stays_bounded_for_a_large_graph(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "ws" / "app", generate(600))
    service, _ = make_service(tmp_path)
    tracemalloc.start()
    await service.configure(make_config({"app": repo}))
    await service.wait_idle()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY
    assert peak < 400 * 1024 * 1024


@pytest.mark.skipif(not REAL_PERF, reason="set STUDIO_CODE_GRAPH_PERF=1 to measure real Graphify")
@pytest.mark.parametrize("size", list(SIZES))
async def test_real_graphify_timings(tmp_path: Path, size: str) -> None:
    if GraphifyProvider().probe().state is not ProbeState.AVAILABLE:
        pytest.skip("graphify executable not installed")
    repo = init_repo(tmp_path / "ws" / "app", generate(SIZES[size]))
    service = CodeGraphService(
        [GraphifyProvider()],
        tmp_path / "cache",
        debounce_seconds=0.0,
        build_timeout_seconds=590.0,
    )
    tracemalloc.start()
    started = time.perf_counter()
    await service.configure(make_config({"app": repo}, provider_id="graphify"))
    await service.wait_idle()
    initial = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY, status.error

    query_started = time.perf_counter()
    await service.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID, limit=100))
    await service.search_symbols(CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="fn1"))
    query = time.perf_counter() - query_started

    (repo / "pkg0" / "added.py").write_text("def added():\n    return 1\n", encoding="utf-8")
    commit_all(repo, "add")
    update_started = time.perf_counter()
    await service.on_git_change(SimpleNamespace(repo_path=repo))
    await service.wait_idle()
    update = time.perf_counter() - update_started

    nodes = status.index.item_count if status.index else 0
    print(
        f"PERF size={size} files={SIZES[size]} nodes={nodes} initial={initial:.1f}s "
        f"update={update:.1f}s query={query * 1000:.0f}ms py_peak={peak / 1e6:.0f}MB"
    )
    assert query < 0.25
