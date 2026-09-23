from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from studio_client.daemon.service import BridgeService
from studio_code_graph.provider import ProbeState, ProviderProbe
from studio_code_graph.service import CodeGraphService
from studio_contracts.local.graph import GraphPage

from tests.code_graph.support import FakeProvider, commit_all, write
from tests.integration_wave2.conftest import (
    DESKTOP_CAPABILITIES,
    WORKSPACE_ID,
    bridge_request,
    build_workspace,
    controller,
    make_registry,
    negotiate,
)


def _service(tmp_path: Path, provider: FakeProvider) -> CodeGraphService:
    return CodeGraphService(
        [provider],
        tmp_path / "code-graph-cache",
        debounce_seconds=0.0,
        freshness_ttl_seconds=0.0,
        probe_ttl_seconds=0.0,
    )


async def test_b_git_workspace_reaches_the_code_graph_page(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=False, code_graph=True)
    provider = FakeProvider()
    registry = make_registry(
        [workspace.config], tmp_path / "cache", service=_service(tmp_path, provider)
    )
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        await registry.wait_idle()
        service = BridgeService(controller_)
        negotiate(service, DESKTOP_CAPABILITIES)

        status = service.handle_line(
            bridge_request("code_graph.status", {"workspace_id": str(WORKSPACE_ID)})
        )
        assert status["kind"] == "response", status
        assert status["payload"]["state"] == "ready", status["payload"]
        assert status["payload"]["provider"]["provider_id"] == "fake"
        assert status["payload"]["languages"] == ["python"]

        page = service.handle_line(
            bridge_request(
                "code_graph.graph_page", {"workspace_id": str(WORKSPACE_ID), "limit": 100}
            )
        )
        assert page["kind"] == "response", page
        graph = GraphPage.model_validate(page["payload"])
        assert graph.source.kind == "code"
        assert any(node.kind == "file" for node in graph.nodes)
        assert any(node.kind == "function" for node in graph.nodes)
        assert all(
            node.uri is None or node.uri.startswith("studio-local://code/") for node in graph.nodes
        )

        symbols = service.handle_line(
            bridge_request(
                "code_graph.find_symbols",
                {"workspace_id": str(WORKSPACE_ID), "name": "helper", "limit": 10},
            )
        )
        assert symbols["kind"] == "response", symbols
        assert any(symbol["name"] == "helper" for symbol in symbols["payload"]["symbols"])
        assert symbols["payload"]["index_state"] == "ready"
    finally:
        registry.stop()


async def test_c_a_provider_absent_reports_not_installed(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=False, code_graph=True)
    provider = FakeProvider(probe_result=ProviderProbe(ProbeState.NOT_INSTALLED, None, "missing"))
    registry = make_registry(
        [workspace.config], tmp_path / "cache", service=_service(tmp_path, provider)
    )
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        await registry.wait_idle()
        service = BridgeService(controller_)
        negotiate(service, DESKTOP_CAPABILITIES)
        status = service.handle_line(
            bridge_request("code_graph.status", {"workspace_id": str(WORKSPACE_ID)})
        )
        assert status["kind"] == "response", status
        assert status["payload"]["state"] == "not_installed", status["payload"]
        assert status["payload"]["error"]["code"] == "provider_not_installed"

        page = service.handle_line(
            bridge_request("code_graph.graph_page", {"workspace_id": str(WORKSPACE_ID)})
        )
        assert page["kind"] == "error", page
        assert page["error"]["code"] == "provider_not_installed"
    finally:
        registry.stop()


async def test_code_graph_is_disabled_without_the_feature(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=False, code_graph=False)
    provider = FakeProvider()
    registry = make_registry(
        [workspace.config], tmp_path / "cache", service=_service(tmp_path, provider)
    )
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        await registry.wait_idle()
        service = BridgeService(controller_)
        negotiate(service, DESKTOP_CAPABILITIES)
        status = service.handle_line(
            bridge_request("code_graph.status", {"workspace_id": str(WORKSPACE_ID)})
        )
        assert status["kind"] == "response", status
        assert status["payload"]["state"] == "disabled", status["payload"]
        assert status["payload"]["error"]["code"] == "feature_disabled"
    finally:
        registry.stop()


async def test_g_a_code_change_stales_then_rebuilds_the_index(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=False, code_graph=True)
    provider = FakeProvider()
    service_graph = _service(tmp_path, provider)
    registry = make_registry([workspace.config], tmp_path / "cache", service=service_graph)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        await registry.wait_idle()
        bridge = BridgeService(controller_)
        negotiate(bridge, DESKTOP_CAPABILITIES)

        def state() -> str:
            answer = bridge.handle_line(
                bridge_request("code_graph.status", {"workspace_id": str(WORKSPACE_ID)})
            )
            return str(answer["payload"]["state"])

        assert state() == "ready"

        write(
            workspace.repo,
            "src/util.py",
            "class Greeter:\n    pass\n\ndef helper():\n    return 2\n"
            "\n\ndef extra():\n    return 3\n",
        )
        commit_all(workspace.repo, "add extra")

        from studio_client.watchers import GitChange

        change = GitChange(
            repo_path=workspace.repo,
            previous_commit=None,
            previous_branch="main",
            commit_sha="deadbeef",
            branch="main",
        )
        await registry.on_git_change(change)
        await registry.wait_idle()
        assert state() == "ready"
        builds_after = len(provider.requests)
        assert builds_after >= 2, "the change triggered a rebuild"

        page = bridge.handle_line(
            bridge_request(
                "code_graph.graph_page", {"workspace_id": str(WORKSPACE_ID), "limit": 100}
            )
        )
        labels = {node["label"] for node in page["payload"]["nodes"]}
        assert "extra" in labels
    finally:
        registry.stop()


async def test_h_a_non_code_change_does_not_rebuild(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=False, code_graph=True)
    provider = FakeProvider()
    registry = make_registry(
        [workspace.config], tmp_path / "cache", service=_service(tmp_path, provider)
    )
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        await registry.wait_idle()
        builds_before = len(provider.requests)

        write(workspace.repo, "docs/readme.md", "# Readme\n\nNo code change.\n")
        commit_all(workspace.repo, "docs only")

        from studio_client.watchers import GitChange

        change = GitChange(
            repo_path=workspace.repo,
            previous_commit=None,
            previous_branch="main",
            commit_sha="cafebabe",
            branch="main",
        )
        await registry.on_git_change(change)
        await registry.wait_idle()
        assert len(provider.requests) == builds_before, (
            "a documentation-only commit rebuilds nothing"
        )
    finally:
        registry.stop()


GRAPHIFY = shutil.which("graphify") is not None


@pytest.mark.skipif(not GRAPHIFY, reason="graphify executable not installed")
async def test_b_real_graphify_is_isolated_behind_the_provider(tmp_path: Path) -> None:
    from studio_code_graph.graphify import GraphifyProvider

    workspace = build_workspace(tmp_path, knowledge=False, code_graph=True)
    assert workspace.config.code_graph is not None
    workspace.config = workspace.config.model_copy(
        update={
            "code_graph": workspace.config.code_graph.model_copy(update={"provider_id": "graphify"})
        }
    )
    service_graph = CodeGraphService(
        [GraphifyProvider()],
        tmp_path / "code-graph-cache",
        debounce_seconds=0.0,
        freshness_ttl_seconds=0.0,
        probe_ttl_seconds=0.0,
        build_timeout_seconds=120.0,
    )
    registry = make_registry([workspace.config], tmp_path / "cache", service=service_graph)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        await registry.wait_idle()
        bridge = BridgeService(controller_)
        negotiate(bridge, DESKTOP_CAPABILITIES)
        answer = bridge.handle_line(
            bridge_request("code_graph.status", {"workspace_id": str(WORKSPACE_ID)})
        )
        assert answer["kind"] == "response", answer
        assert answer["payload"]["state"] == "ready", answer["payload"]
        assert answer["payload"]["provider"]["provider_id"] == "graphify"
        assert not (workspace.repo / "graphify-out").exists()
    finally:
        registry.stop()
