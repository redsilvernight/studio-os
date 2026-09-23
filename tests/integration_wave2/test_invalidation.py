from __future__ import annotations

import asyncio
import time
from pathlib import Path

from studio_client.daemon.service import BridgeService

from tests.integration_wave2.conftest import (
    DESKTOP_CAPABILITIES,
    WORKSPACE_ID,
    bridge_request,
    build_workspace,
    controller,
    make_registry,
    negotiate,
)


async def _wait_for(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_i_a_markdown_change_reaches_the_knowledge_graph(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        service = BridgeService(controller_)
        negotiate(service, DESKTOP_CAPABILITIES)

        def status_state() -> str:
            answer = service.handle_line(
                bridge_request("knowledge.status", {"workspace_id": str(WORKSPACE_ID)})
            )
            assert answer["kind"] == "response", answer
            return str(answer["payload"]["state"])

        def labels() -> set[str]:
            answer = service.handle_line(
                bridge_request(
                    "knowledge.graph_page", {"workspace_id": str(WORKSPACE_ID), "limit": 200}
                )
            )
            assert answer["kind"] == "response", answer
            return {node["label"] for node in answer["payload"]["nodes"]}

        assert await _wait_for(lambda: status_state() == "ready")
        assert "Introduction" in labels() or "Intro" in labels()

        new_note = workspace.vault / "projects/demo/patchnotes.md"
        new_note.write_text(
            "---\ntitle: Patch Notes\n---\n# Patch Notes\n\nSee [combat](combat.md).\n",
            encoding="utf-8",
        )

        assert await _wait_for(lambda: "Patch Notes" in labels()), (
            "the vault watcher reindexed the new Markdown file"
        )
    finally:
        registry.stop()


async def test_the_vault_watcher_reuses_the_shared_polling_lifecycle(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        watchers = list(registry._watchers.values())
        assert len(watchers) == 1, (
            "one bounded poller per knowledge workspace, no second global loop"
        )
        assert all(not task.done() for task in watchers)
        assert all(task.get_name().startswith("vault-watch-") for task in watchers)
    finally:
        registry.stop()


async def test_dissociating_a_workspace_keeps_the_markdown_files(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        await registry.wait_idle()
        files_before = sorted(path.name for path in workspace.vault.rglob("*.md"))
        assert files_before

        registry.refresh(controller_._profile())

        assert sorted(path.name for path in workspace.vault.rglob("*.md")) == files_before
        assert all(path.exists() for path in workspace.vault.rglob("*.md"))
    finally:
        registry.stop()


async def test_g_the_real_git_watcher_drives_the_code_graph_without_a_second_watcher(
    tmp_path: Path,
) -> None:
    from studio_client.outbox import OutboxStore, connect
    from studio_client.watchers import GitWatcher
    from studio_code_graph.service import CodeGraphService

    from tests.code_graph.support import FakeProvider, commit_all, write
    from tests.integration_wave2.conftest import PROJECT_ID, WORKSPACE_ID
    from tests.integration_wave2.test_code_chain import _service

    workspace = build_workspace(tmp_path, knowledge=False, code_graph=True)
    provider = FakeProvider()
    graph = _service(tmp_path, provider)
    assert isinstance(graph, CodeGraphService)
    registry = make_registry([workspace.config], tmp_path / "cache", service=graph)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        await registry.wait_idle()
        service = BridgeService(controller_)
        negotiate(service, DESKTOP_CAPABILITIES)

        def state() -> str:
            answer = service.handle_line(
                bridge_request("code_graph.status", {"workspace_id": str(WORKSPACE_ID)})
            )
            return str(answer["payload"]["state"])

        assert state() == "ready"
        builds_before = len(provider.requests)

        outbox = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
        watcher = GitWatcher(
            repo_path=workspace.repo,
            project_id=PROJECT_ID,
            machine_id=WORKSPACE_ID,
            outbox=outbox,
            on_change=registry.on_git_change,
        )
        await watcher.poll_once()

        write(workspace.repo, "src/extra.py", "def extra():\n    return 3\n")
        commit_all(workspace.repo, "add extra")
        await watcher.poll_once()
        assert await _wait_for(lambda: state() == "ready")
        await registry.wait_idle()
        assert len(provider.requests) == builds_before + 1, (
            "the callback triggered exactly one rebuild"
        )

        answer = service.handle_line(
            bridge_request(
                "code_graph.graph_page", {"workspace_id": str(WORKSPACE_ID), "limit": 100}
            )
        )
        labels = {node["label"] for node in answer["payload"]["nodes"]}
        assert "extra" in labels

        names = [task.get_name() for task in registry._watchers.values()]
        assert all(name.startswith("vault-watch-") for name in names), names
    finally:
        registry.stop()
