from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from studio_client.config import ClientConfig
from studio_client.daemon.service import BridgeService, DaemonController

from tests.integration_wave2.conftest import (
    DESKTOP_CAPABILITIES,
    WORKSPACE_ID,
    bridge_request,
    build_workspace,
    controller,
    make_registry,
    negotiate,
)


def test_handshake_advertises_and_grants_the_local_feature_capabilities(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        service = BridgeService(controller_)
        answer = negotiate(service, DESKTOP_CAPABILITIES)
        assert answer["payload"]["outcome"] == "compatible", answer["payload"]
        advertised = set(answer["payload"]["daemon"]["capabilities"])
        granted = set(answer["payload"]["granted_capabilities"])
        for capability in ("knowledge.read", "knowledge.graph", "knowledge.index"):
            assert capability in advertised
            assert capability in granted
    finally:
        registry.stop()


def test_a_missing_capability_is_refused_without_running_the_command(tmp_path: Path) -> None:
    workspace = build_workspace(tmp_path, knowledge=True, code_graph=False)
    registry = make_registry([workspace.config], tmp_path / "cache", service=None)
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        service = BridgeService(controller_)
        negotiate(service, ["daemon.control"])
        answer = service.handle_line(
            bridge_request("knowledge.status", {"workspace_id": str(WORKSPACE_ID)})
        )
        assert answer["kind"] == "error", answer
        assert answer["error"]["code"] == "capability_missing"
    finally:
        registry.stop()


def test_a_daemon_without_local_features_does_not_serve_them(tmp_path: Path) -> None:
    controller_ = DaemonController(
        ClientConfig(
            api_base_url="https://studio.example/api/v1",
            profile_id="main",
            machine_id=uuid4(),
        ),
        data_root=tmp_path,
    )
    service = BridgeService(controller_)
    answer = negotiate(service, DESKTOP_CAPABILITIES)
    assert answer["payload"]["outcome"] == "compatible_degraded", answer["payload"]
    assert "knowledge.read" not in set(answer["payload"]["daemon"]["capabilities"])

    refused = service.handle_line(
        bridge_request("knowledge.status", {"workspace_id": str(WORKSPACE_ID)})
    )
    assert refused["kind"] == "error", refused
    assert refused["error"]["code"] == "capability_missing"
