from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

from studio_client.daemon.workspace_watch import WorkspaceWatch, WorkspaceWatchSet
from studio_client.outbox import OutboxStore, connect
from studio_client.watchers import GitChange, GitWatcher
from studio_code_graph import CodeGraphService
from studio_contracts.local.common import ComponentState
from studio_contracts.local.workspace import LocalFeatures, WatcherConfig
from studio_workspaces import daemon_watch_plan

from .support import (
    APP_FILES,
    PROJECT_ID,
    WORKSPACE_ID,
    FakeProvider,
    commit_all,
    git,
    init_repo,
    make_config,
    make_service,
    write,
)

MACHINE_ID = WORKSPACE_ID


def make_watcher(repo: Path, service: CodeGraphService, tmp_path: Path) -> GitWatcher:
    return GitWatcher(
        repo_path=repo,
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=OutboxStore(connect(tmp_path / "outbox.sqlite3")),
        on_change=service.on_git_change,
    )


async def indexed(
    tmp_path: Path, **options: object
) -> tuple[CodeGraphService, FakeProvider, Path, GitWatcher]:
    repo = init_repo(tmp_path / "ws" / "app", APP_FILES)
    service, provider = make_service(tmp_path, **options)
    await service.configure(make_config({"app": repo}))
    await service.wait_idle()
    watcher = make_watcher(repo, service, tmp_path)
    await watcher.poll_once()
    return service, provider, repo, watcher


async def test_a_commit_touching_code_triggers_one_rebuild(tmp_path: Path) -> None:
    service, provider, repo, watcher = await indexed(tmp_path)
    assert len(provider.requests) == 1
    write(repo, "src/extra.py", "def extra():\n    return 2\n")
    commit_all(repo, "add code")
    await watcher.poll_once()
    await service.wait_idle()
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY
    assert len(provider.requests) == 2
    assert not provider.requests[1].full_rebuild


async def test_a_commit_without_code_change_does_not_rebuild(tmp_path: Path) -> None:
    service, provider, repo, watcher = await indexed(tmp_path)
    write(repo, "NOTES.md", "notes\n")
    commit_all(repo, "docs")
    await watcher.poll_once()
    await service.wait_idle()
    assert len(provider.requests) == 1
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY


async def test_branch_change_with_different_code_rebuilds(tmp_path: Path) -> None:
    service, provider, repo, watcher = await indexed(tmp_path)
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "src/feature.py", "def feature():\n    return 3\n")
    commit_all(repo, "feature")
    await watcher.poll_once()
    await service.wait_idle()
    assert len(provider.requests) == 2
    git(repo, "checkout", "-q", "main")
    await watcher.poll_once()
    await service.wait_idle()
    assert len(provider.requests) == 3
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY


async def test_branch_change_with_identical_code_does_not_rebuild(tmp_path: Path) -> None:
    service, provider, repo, watcher = await indexed(tmp_path)
    git(repo, "checkout", "-q", "-b", "same-code")
    await watcher.poll_once()
    await service.wait_idle()
    assert len(provider.requests) == 1


async def test_deleted_file_is_dropped_from_the_index(tmp_path: Path) -> None:
    service, provider, repo, watcher = await indexed(tmp_path)
    git(repo, "rm", "-q", "src/util.py")
    git(repo, "commit", "-q", "-m", "remove")
    await watcher.poll_once()
    await service.wait_idle()
    assert len(provider.requests) == 2
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY
    assert status.index is not None and status.index.item_count == 2


async def test_renamed_file_is_reindexed(tmp_path: Path) -> None:
    service, provider, repo, watcher = await indexed(tmp_path)
    git(repo, "mv", "src/util.py", "src/tools.py")
    git(repo, "commit", "-q", "-m", "rename")
    await watcher.poll_once()
    await service.wait_idle()
    assert len(provider.requests) == 2
    status = await service.status(WORKSPACE_ID)
    assert status.state is ComponentState.READY


async def test_the_event_stream_is_still_written_by_the_same_watcher(tmp_path: Path) -> None:
    service, provider, repo, watcher = await indexed(tmp_path)
    write(repo, "src/extra.py", "def extra():\n    return 2\n")
    commit_all(repo, "add code")
    await watcher.poll_once()
    rows = watcher._outbox.connection.execute("SELECT COUNT(*) FROM pending_events").fetchone()
    assert rows is not None and rows[0] >= 1


async def test_a_failing_listener_never_breaks_the_watcher(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "ws" / "app", APP_FILES)
    seen: list[GitChange] = []

    async def broken(change: GitChange) -> None:
        seen.append(change)
        raise RuntimeError("listener bug")

    watcher = GitWatcher(
        repo_path=repo,
        project_id=PROJECT_ID,
        machine_id=MACHINE_ID,
        outbox=OutboxStore(connect(tmp_path / "outbox.sqlite3")),
        on_change=broken,
    )
    await watcher.poll_once()
    write(repo, "src/extra.py", "x = 1\n")
    commit_all(repo, "add")
    await watcher.poll_once()
    assert len(seen) == 1 and seen[0].previous_commit != seen[0].commit_sha


async def test_the_workspace_watch_set_shares_the_same_watcher_lifecycle(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "ws" / "app", APP_FILES)
    service, provider = make_service(tmp_path)
    config = make_config({"app": repo}).model_copy(
        update={
            "features": LocalFeatures(code_graph=True, watchers=True),
            "watchers": WatcherConfig(),
        }
    )
    await service.configure(config)
    await service.wait_idle()
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    watches = WorkspaceWatchSet(
        machine_id=MACHINE_ID,
        outbox=store,
        interval_seconds=0.05,
        change_listener=service.on_git_change,
    )
    await watches.reconcile([WorkspaceWatch(WORKSPACE_ID, PROJECT_ID, daemon_watch_plan(config))])
    try:
        await asyncio.sleep(0.3)
        write(repo, "src/extra.py", "def extra():\n    return 2\n")
        commit_all(repo, "add code")
        for _ in range(80):
            await service.wait_idle()
            if len(provider.requests) >= 2:
                break
            await asyncio.sleep(0.1)
    finally:
        await watches.stop()
    assert len(provider.requests) == 2
    assert (await service.status(WORKSPACE_ID)).state is ComponentState.READY


async def test_no_second_watcher_is_created_by_the_service() -> None:
    import ast

    import studio_code_graph.service as service_module

    tree = ast.parse(Path(service_module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "studio_client" not in imported
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "GitWatcher"]


def test_the_listener_is_a_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(CodeGraphService.on_git_change)
