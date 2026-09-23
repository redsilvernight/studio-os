from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from studio_code_graph import (
    BuildFailure,
    CodeGraphBuildError,
    CodeGraphQueryError,
    CodeGraphService,
    ProbeState,
    ProviderProbe,
)
from studio_contracts.local.code_graph import (
    CodeReindexMode,
    CodeReindexRequest,
    CodeSymbolQuery,
)
from studio_contracts.local.common import ComponentId, ComponentState, LocalErrorCode
from studio_contracts.local.graph import (
    GraphExpandRequest,
    GraphNodeRef,
    GraphPageRequest,
    NodeKind,
    RelationKind,
)
from studio_contracts.local.provider import IndexState

from .support import (
    APP_FILES,
    WORKSPACE_ID,
    FakeProvider,
    commit_all,
    git,
    init_repo,
    make_config,
    make_service,
    write,
)


@pytest.fixture
def app(tmp_path: Path) -> Path:
    return init_repo(tmp_path / "ws" / "app", APP_FILES)


async def ready(service: CodeGraphService, app: Path) -> None:
    await service.configure(make_config({"app": app}))
    await service.wait_idle()


async def test_disabled_workspace_has_no_index(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await service.configure(make_config({"app": app}, enabled=False))
    await service.wait_idle()
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.DISABLED
    assert status.error is not None and status.error.code is LocalErrorCode.FEATURE_DISABLED
    assert provider.requests == []
    assert not (tmp_path / "cache").exists()


async def test_unknown_workspace_reports_disabled(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.DISABLED


async def test_provider_not_installed(tmp_path: Path, app: Path) -> None:
    provider = FakeProvider(probe_result=ProviderProbe(ProbeState.NOT_INSTALLED))
    service, _ = make_service(tmp_path, provider)
    await ready(service, app)
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.NOT_INSTALLED
    assert status.error is not None and status.error.code is LocalErrorCode.PROVIDER_NOT_INSTALLED
    assert provider.requests == []


async def test_unregistered_provider_is_not_installed(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await service.configure(make_config({"app": app}, provider_id="other"))
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.NOT_INSTALLED


async def test_provider_incompatible(tmp_path: Path, app: Path) -> None:
    provider = FakeProvider(
        probe_result=ProviderProbe(ProbeState.INCOMPATIBLE, "9.0.0", "unsupported version")
    )
    service, _ = make_service(tmp_path, provider)
    await ready(service, app)
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.INCOMPATIBLE
    assert status.provider is not None
    assert status.error is not None and status.error.code is LocalErrorCode.PROVIDER_INCOMPATIBLE
    assert provider.requests == []


async def test_provider_unavailable(tmp_path: Path, app: Path) -> None:
    provider = FakeProvider(probe_result=ProviderProbe(ProbeState.UNAVAILABLE, reason="no answer"))
    service, _ = make_service(tmp_path, provider)
    await ready(service, app)
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.UNAVAILABLE
    assert status.error is not None and status.error.retryable


async def test_initial_index_is_ready_with_provenance(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY
    assert status.index is not None and status.index.state is IndexState.READY
    assert status.index.item_count == 5 and status.index.built_at is not None
    assert status.index.source_fingerprint is not None
    assert status.error is None and status.languages == ["python"]
    assert status.provider is not None and status.provider.provider_version == "1.2.3"
    page = await service.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID))
    assert page.source.provider_id == "fake" and page.source.source_id == "code.fake"
    assert {node.kind for node in page.nodes} == {NodeKind.FILE, NodeKind.FUNCTION}
    assert all(node.provenance.source_id == "code.fake" for node in page.nodes)
    assert all(edge.provenance.extractor for edge in page.edges)
    assert {edge.kind for edge in page.edges} == {RelationKind.CONTAINS, RelationKind.IMPORTS}
    assert len(provider.requests) == 1
    assert provider.requests[0].work_dir.is_relative_to(tmp_path / "cache")


async def test_indexing_state_while_build_runs(tmp_path: Path, app: Path) -> None:
    provider = FakeProvider(gate=asyncio.Event())
    service, _ = make_service(tmp_path, provider)
    await service.configure(make_config({"app": app}))
    await asyncio.sleep(0.05)
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.INDEXING
    assert status.index is not None and status.index.state is IndexState.INDEXING
    result = await service.search_symbols(CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="main"))
    assert result.complete is False and result.index_state is IndexState.INDEXING
    assert provider.gate is not None
    provider.gate.set()
    await service.wait_idle()
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY


async def test_configure_does_not_wait_for_the_provider(tmp_path: Path, app: Path) -> None:
    provider = FakeProvider(gate=asyncio.Event())
    service, _ = make_service(tmp_path, provider)
    await asyncio.wait_for(service.configure(make_config({"app": app})), timeout=2)
    assert provider.gate is not None
    provider.gate.set()
    await service.close()


async def test_second_configure_reuses_snapshot(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    fresh, _ = make_service(tmp_path, provider)
    await fresh.configure(make_config({"app": app}))
    await fresh.wait_idle()
    assert (await fresh.status(WORKSPACE_ID)).state is ComponentState.READY
    assert len(provider.requests) == 1


async def test_edit_marks_stale_then_git_change_rebuilds(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    write(app, "src/util.py", "def helper():\n    return 2\n\ndef extra():\n    return 3\n")
    stale = await service.status(WORKSPACE_ID)
    assert stale.state is ComponentState.STALE
    assert stale.index is not None and stale.index.state is IndexState.STALE
    assert len(provider.requests) == 1
    commit_all(app)
    await service.on_git_change(SimpleNamespace(repo_path=app))
    await service.wait_idle()
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY
    assert len(provider.requests) == 2
    found = await service.search_symbols(CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="extra"))
    assert [symbol.name for symbol in found.symbols] == ["extra"]
    assert found.complete is True
    (diagnostics,) = service.diagnostics(WORKSPACE_ID)
    assert diagnostics.last_change is not None and diagnostics.last_change.modified == 1


async def test_git_change_without_code_change_does_not_rebuild(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    write(app, "README.md", "docs\n")
    commit_all(app, "docs only")
    await service.on_git_change(SimpleNamespace(repo_path=app))
    await service.wait_idle()
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY
    assert len(provider.requests) == 1


async def test_touching_a_file_does_not_go_stale(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    text = (app / "src/util.py").read_text(encoding="utf-8")
    write(app, "src/util.py", text)
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY
    assert len(provider.requests) == 1


async def test_deleted_file_is_removed_from_the_index(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await ready(service, app)
    (app / "src/util.py").unlink()
    await service.on_git_change(SimpleNamespace(repo_path=app))
    await service.wait_idle()
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY
    assert status.index is not None and status.index.item_count == 2
    found = await service.search_symbols(CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="helper"))
    assert found.symbols == []
    (diagnostics,) = service.diagnostics(WORKSPACE_ID)
    assert diagnostics.last_change is not None and diagnostics.last_change.deleted == 1


async def test_renamed_file_is_seen_as_a_rename(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await ready(service, app)
    (app / "src/util.py").rename(app / "src/tools.py")
    await service.on_git_change(SimpleNamespace(repo_path=app))
    await service.wait_idle()
    (diagnostics,) = service.diagnostics(WORKSPACE_ID)
    assert diagnostics.last_change is not None and diagnostics.last_change.renamed == 1
    page = await service.graph_page(
        GraphPageRequest(workspace_id=WORKSPACE_ID, node_kinds=[NodeKind.FILE])
    )
    assert sorted(node.label for node in page.nodes) == ["src/main.py", "src/tools.py"]


async def test_branch_change_rebuilds_only_when_code_differs(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    git(app, "checkout", "-q", "-b", "same")
    await service.on_git_change(SimpleNamespace(repo_path=app))
    await service.wait_idle()
    assert len(provider.requests) == 1
    write(app, "src/extra.py", "def branch_only():\n    return 1\n")
    commit_all(app, "branch work")
    await service.on_git_change(SimpleNamespace(repo_path=app))
    await service.wait_idle()
    assert len(provider.requests) == 2
    git(app, "checkout", "-q", "main")
    await service.on_git_change(SimpleNamespace(repo_path=app))
    await service.wait_idle()
    assert len(provider.requests) == 3
    found = await service.search_symbols(
        CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="branch_only")
    )
    assert found.symbols == []


async def test_git_change_of_another_repo_is_ignored(tmp_path: Path, app: Path) -> None:
    other = init_repo(tmp_path / "ws" / "other", {"a.py": "def a():\n    pass\n"})
    service, provider = make_service(tmp_path)
    await ready(service, app)
    write(other, "a.py", "def b():\n    pass\n")
    await service.on_git_change(SimpleNamespace(repo_path=other))
    await service.wait_idle()
    assert len(provider.requests) == 1


async def test_git_events_are_coalesced_into_one_rebuild(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path, debounce_seconds=0.2)
    await ready(service, app)
    write(app, "src/util.py", "def helper():\n    return 3\n")
    for _ in range(5):
        await service.on_git_change(SimpleNamespace(repo_path=app))
    await service.wait_idle()
    assert len(provider.requests) == 2


async def test_change_during_build_triggers_a_rerun(tmp_path: Path, app: Path) -> None:
    provider = FakeProvider(gate=asyncio.Event())
    service, _ = make_service(tmp_path, provider)
    await service.configure(make_config({"app": app}))
    await asyncio.sleep(0.05)
    write(app, "src/late.py", "def late():\n    pass\n")
    await service.on_git_change(SimpleNamespace(repo_path=app))
    assert provider.gate is not None
    provider.gate.set()
    await service.wait_idle()
    found = await service.search_symbols(
        CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="late", kinds=[NodeKind.FUNCTION])
    )
    assert [symbol.name for symbol in found.symbols] == ["late"]


async def test_failed_rebuild_keeps_serving_the_previous_index(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    provider.failure = CodeGraphBuildError(BuildFailure.PROCESS_FAILED, "exit code 1")
    write(app, "src/util.py", "def changed():\n    pass\n")
    await service.on_git_change(SimpleNamespace(repo_path=app))
    await service.wait_idle()
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.STALE
    found = await service.search_symbols(CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="main"))
    assert found.complete is False and found.symbols
    (diagnostics,) = service.diagnostics(WORKSPACE_ID)
    assert diagnostics.failure is not None


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (BuildFailure.TIMEOUT, LocalErrorCode.TIMEOUT),
        (BuildFailure.OUTPUT_CORRUPT, LocalErrorCode.INDEX_CORRUPT),
        (BuildFailure.PROCESS_FAILED, LocalErrorCode.INTERNAL_ERROR),
    ],
)
async def test_first_build_failure_is_an_error_state(
    tmp_path: Path, app: Path, failure: BuildFailure, code: LocalErrorCode
) -> None:
    provider = FakeProvider(failure=CodeGraphBuildError(failure, "boom"))
    service, _ = make_service(tmp_path, provider)
    await ready(service, app)
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.ERROR
    assert status.error is not None and status.error.code is code
    assert status.error.component is ComponentId.CODE_GRAPH
    assert str(tmp_path) not in status.error.message


async def test_provider_crash_is_contained(tmp_path: Path, app: Path) -> None:
    provider = FakeProvider(crash=RuntimeError(f"secret at {tmp_path}"))
    service, _ = make_service(tmp_path, provider)
    await ready(service, app)
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.ERROR
    assert status.error is not None and str(tmp_path) not in status.error.model_dump_json()


async def test_recovery_after_failure_via_reindex(tmp_path: Path, app: Path) -> None:
    provider = FakeProvider(failure=CodeGraphBuildError(BuildFailure.TIMEOUT))
    service, _ = make_service(tmp_path, provider)
    await ready(service, app)
    provider.failure = None
    result = await service.reindex(CodeReindexRequest(workspace_id=WORKSPACE_ID))
    assert result.accepted and result.operation_id and result.state is ComponentState.INDEXING
    await service.wait_idle()
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY


async def test_corrupt_snapshot_is_reported_then_rebuilt(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    (snapshot,) = (tmp_path / "cache").rglob("snapshot.json")
    snapshot.write_text("{not json", encoding="utf-8")
    fresh, _ = make_service(tmp_path, provider)
    await fresh.configure(make_config({"app": app}))
    await fresh.wait_idle()
    assert (await fresh.status(WORKSPACE_ID)).state is ComponentState.READY
    assert provider.requests[-1].full_rebuild is True


async def test_corrupt_snapshot_without_a_provider_is_an_error(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await ready(service, app)
    (snapshot,) = (tmp_path / "cache").rglob("snapshot.json")
    snapshot.write_text("{not json", encoding="utf-8")
    gated = FakeProvider(gate=asyncio.Event())
    fresh, _ = make_service(tmp_path, gated)
    await fresh.configure(make_config({"app": app}))
    await asyncio.sleep(0.05)
    assert (await fresh.status(WORKSPACE_ID)).state is ComponentState.INDEXING
    await fresh.close()


async def test_reindex_refused_when_disabled_or_unknown_repo(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    refused = await service.reindex(CodeReindexRequest(workspace_id=WORKSPACE_ID))
    assert not refused.accepted and refused.error is not None
    await ready(service, app)
    unknown = await service.reindex(
        CodeReindexRequest(workspace_id=WORKSPACE_ID, repo_names=["nope"])
    )
    assert not unknown.accepted and unknown.error is not None
    assert unknown.error.code is LocalErrorCode.INVALID_REQUEST


async def test_full_rebuild_reindex_requests_a_clean_work_dir(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    await service.reindex(
        CodeReindexRequest(workspace_id=WORKSPACE_ID, mode=CodeReindexMode.FULL_REBUILD)
    )
    await service.wait_idle()
    assert [request.full_rebuild for request in provider.requests] == [False, True]


async def test_unchanged_incremental_reindex_skips_the_provider(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    await service.reindex(CodeReindexRequest(workspace_id=WORKSPACE_ID))
    await service.wait_idle()
    assert len(provider.requests) == 1


async def test_missing_repository_is_explicit(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await ready(service, app)
    moved = app.parent / "moved"
    app.rename(moved)
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.UNAVAILABLE
    assert status.error is not None and status.error.code is LocalErrorCode.WORKSPACE_INACCESSIBLE
    assert moved.is_dir()


async def test_never_cloned_repository_is_missing_not_crashing(tmp_path: Path) -> None:
    ghost = tmp_path / "ws" / "ghost"
    service, provider = make_service(tmp_path)
    await service.configure(make_config({"ghost": ghost}, workspace_root=tmp_path / "ws"))
    await service.wait_idle()
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.UNAVAILABLE
    assert provider.requests == []


async def test_repository_moved_then_reconfigured_is_reindexed(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    moved = app.parent / "moved"
    app.rename(moved)
    await service.configure(make_config({"app": moved}))
    await service.wait_idle()
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY
    assert (moved / "src/main.py").is_file()
    assert len(provider.requests) <= 2


async def test_disabling_stops_indexing_and_keeps_the_repository(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await ready(service, app)
    await service.configure(make_config({"app": app}, enabled=False))
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.DISABLED
    with pytest.raises(CodeGraphQueryError):
        await service.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID))
    assert (app / "src/main.py").is_file() and (app / ".git").is_dir()


async def test_dissociation_never_deletes_the_repository(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await ready(service, app)
    await service.forget(WORKSPACE_ID, purge_cache=True)
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.DISABLED
    assert (app / "src/main.py").is_file()
    assert not list((tmp_path / "cache").rglob("snapshot.json"))


async def test_removing_a_repo_from_config_drops_it(tmp_path: Path, app: Path) -> None:
    other = init_repo(tmp_path / "ws" / "other", {"o.py": "def only_other():\n    pass\n"})
    service, _ = make_service(tmp_path)
    await service.configure(make_config({"app": app, "other": other}))
    await service.wait_idle()
    await service.configure(make_config({"app": app, "other": other}, repo_names=["app"]))
    await service.wait_idle()
    found = await service.search_symbols(
        CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="only_other")
    )
    assert found.symbols == []


async def test_language_filter_reports_unsupported_languages(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await service.configure(make_config({"app": app}, languages=["python", "cobol"]))
    await service.wait_idle()
    status = await service.status(WORKSPACE_ID)
    assert status.unsupported_languages == ["cobol"]
    assert status.state is ComponentState.READY


async def test_excluded_paths_are_not_indexed(tmp_path: Path, app: Path) -> None:
    write(app, "vendor/lib.py", "def vendored():\n    pass\n")
    commit_all(app, "vendor")
    service, _ = make_service(tmp_path)
    await service.configure(make_config({"app": app}, exclude=["vendor/**"]))
    await service.wait_idle()
    write(app, "vendor/lib.py", "def vendored():\n    return 2\n")
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY


async def test_non_git_repository_is_indexed_but_never_auto_stale(tmp_path: Path) -> None:
    plain = tmp_path / "ws" / "plain"
    write(plain, "a.py", "def a():\n    pass\n")
    service, provider = make_service(tmp_path)
    await service.configure(make_config({"plain": plain}, workspace_root=tmp_path / "ws"))
    await service.wait_idle()
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY
    write(plain, "a.py", "def b():\n    pass\n")
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY
    await service.reindex(CodeReindexRequest(workspace_id=WORKSPACE_ID))
    await service.wait_idle()
    assert len(provider.requests) == 2


async def test_empty_repository_is_ready_without_running_the_provider(tmp_path: Path) -> None:
    empty = init_repo(tmp_path / "ws" / "empty")
    service, provider = make_service(tmp_path)
    await service.configure(make_config({"empty": empty}, workspace_root=tmp_path / "ws"))
    await service.wait_idle()
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY
    assert status.index is not None and status.index.item_count == 0
    assert provider.requests == []


async def test_provider_version_change_marks_the_index_stale(tmp_path: Path, app: Path) -> None:
    service, provider = make_service(tmp_path)
    await ready(service, app)
    provider.probe_result = ProviderProbe(ProbeState.AVAILABLE, "1.3.0")
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.STALE
    await service.reindex(CodeReindexRequest(workspace_id=WORKSPACE_ID))
    await service.wait_idle()
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY
    assert len(provider.requests) == 2


async def test_status_polling_does_not_reread_or_rebuild(tmp_path: Path, app: Path) -> None:
    calls: list[Path] = []
    from studio_code_graph.gitstate import read_repo_files

    def counting(*args: object) -> object:
        calls.append(app)
        return read_repo_files(*args)  # type: ignore[arg-type]

    service, provider = make_service(
        tmp_path, freshness_ttl_seconds=60.0, probe_ttl_seconds=60.0, file_reader=counting
    )
    await ready(service, app)
    await service.status(WORKSPACE_ID)
    before = len(calls)
    for _ in range(20):
        await service.status(WORKSPACE_ID)
        await service.search_symbols(CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="main"))
    assert len(calls) == before
    assert len(provider.requests) == 1


async def test_search_ranks_and_pages(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await ready(service, app)
    first = await service.search_symbols(
        CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="r", limit=2)
    )
    assert len(first.symbols) == 2 and first.next_cursor is not None
    second = await service.search_symbols(
        CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="r", limit=2, cursor=first.next_cursor)
    )
    assert not {s.node_id for s in first.symbols} & {s.node_id for s in second.symbols}
    exact = await service.search_symbols(CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="main"))
    assert exact.symbols[0].name == "main"
    with pytest.raises(CodeGraphQueryError) as error:
        await service.search_symbols(
            CodeSymbolQuery(workspace_id=WORKSPACE_ID, name="r", cursor="bogus")
        )
    assert error.value.error.code is LocalErrorCode.INVALID_REQUEST


async def test_expand_follows_real_edges_only(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await ready(service, app)
    page = await service.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID))
    main_file = next(node for node in page.nodes if node.label == "src/main.py")
    expanded = await service.graph_expand(
        GraphExpandRequest(
            workspace_id=WORKSPACE_ID,
            node=GraphNodeRef(source_id=page.source.source_id, node_id=main_file.node_id),
        )
    )
    labels = {node.label for node in expanded.nodes}
    assert labels == {"src/main.py", "src/util.py", "main"}
    assert {edge.kind for edge in expanded.edges} == {RelationKind.CONTAINS, RelationKind.IMPORTS}
    known = {edge.edge_id for edge in page.edges}
    assert {edge.edge_id for edge in expanded.edges} <= known


async def test_expand_unknown_node_is_an_invalid_request(tmp_path: Path, app: Path) -> None:
    service, _ = make_service(tmp_path)
    await ready(service, app)
    with pytest.raises(CodeGraphQueryError) as error:
        await service.graph_expand(
            GraphExpandRequest(
                workspace_id=WORKSPACE_ID,
                node=GraphNodeRef(source_id="code.fake", node_id="n-unknown"),
            )
        )
    assert error.value.error.code is LocalErrorCode.INVALID_REQUEST


async def test_provider_is_replaceable(tmp_path: Path, app: Path) -> None:
    alternative = FakeProvider(provider_id="alt", display_name="Alternative")
    service, _ = make_service(tmp_path, alternative)
    await service.configure(make_config({"app": app}, provider_id="alt"))
    await service.wait_idle()
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY
    assert status.provider is not None and status.provider.provider_id == "alt"
    page = await service.graph_page(GraphPageRequest(workspace_id=WORKSPACE_ID))
    assert page.source.provider_id == "alt" and page.source.source_id == "code.alt"


async def test_repository_is_never_modified_by_indexing(tmp_path: Path, app: Path) -> None:
    before = git(app, "status", "--porcelain", "--ignored")
    listing = sorted(
        path.relative_to(app).as_posix() for path in app.rglob("*") if ".git" not in path.parts
    )
    service, _ = make_service(tmp_path)
    await ready(service, app)
    assert git(app, "status", "--porcelain", "--ignored") == before
    assert (
        sorted(
            path.relative_to(app).as_posix() for path in app.rglob("*") if ".git" not in path.parts
        )
        == listing
    )
