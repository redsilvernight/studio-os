from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from studio_client.daemon.local_features import LocalFeatureRegistry
from studio_client.daemon.service import BridgeService
from studio_contracts.local.workspace import LocalFeatures

from tests.harness.support import CLAUDE_VERSION_LINE, base_env, install_fake
from tests.integration_wave2.conftest import (
    DESKTOP_CAPABILITIES,
    WORKSPACE_ID,
    bridge_request,
    build_workspace,
    controller,
    negotiate,
)

HARNESS_CAPABILITIES = ["harness.read", "harness.plan", "harness.apply", "harness.verify"]
SCOPE = {"workspace_id": str(WORKSPACE_ID)}
MCP_URL = "https://studio.example/mcp"


@dataclass
class Bridge:
    service: BridgeService
    root: Path
    backups: Path
    env: dict[str, str]

    def call(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.service.handle_line(bridge_request(command, payload))

    def ok(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        answer = self.call(command, payload)
        assert answer["kind"] != "error", answer
        return answer["payload"]

    def preview(self, adapter: str) -> dict[str, Any]:
        return self.ok("harness.preview", {**SCOPE, "adapter_id": adapter})

    def apply(self, plan: dict[str, Any]) -> dict[str, Any]:
        return self.ok(
            "harness.apply",
            {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "confirmed": True},
        )

    def states(self) -> dict[str, str]:
        result = self.ok("harness.detect", SCOPE)
        return {item["adapter_id"]: item["state"] for item in result["harnesses"]}


@contextmanager
def _make_bridge(tmp_path: Path, *, harness: bool, harnesses: bool = True) -> Iterator[Bridge]:
    root = tmp_path / "ws"
    root.mkdir()
    bin_dir = tmp_path / "bin"
    if harnesses:
        install_fake(bin_dir, "claude", CLAUDE_VERSION_LINE)
        install_fake(bin_dir, "opencode", "1.18.31")
    else:
        bin_dir.mkdir()
    env = base_env(bin_dir)
    workspace = build_workspace(root, knowledge=False, code_graph=False)
    config = workspace.config.model_copy(update={"features": LocalFeatures(harness=harness)})
    registry = LocalFeatureRegistry(
        workspace_configs=lambda profile: [config] if config.profile == profile else [],
        cache_root=tmp_path / "cache",
        harness_backups_root=tmp_path / "backups",
        harness_env=lambda: env,
    )
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        service = BridgeService(controller_)
        answer = negotiate(service, [*DESKTOP_CAPABILITIES, *HARNESS_CAPABILITIES])
        assert answer["payload"]["outcome"] == "compatible", answer["payload"]
        yield Bridge(service, workspace.root, tmp_path / "backups", env)
    finally:
        registry.stop()


@pytest.fixture
def bridge(tmp_path: Path) -> Iterator[Bridge]:
    with _make_bridge(tmp_path, harness=True) as opened:
        yield opened


def test_handshake_advertises_and_grants_the_harness_capabilities(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    workspace = build_workspace(root, knowledge=False, code_graph=False)
    registry = LocalFeatureRegistry(
        workspace_configs=lambda profile: [workspace.config],
        cache_root=tmp_path / "cache",
    )
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        service = BridgeService(controller_)
        answer = negotiate(service, [*DESKTOP_CAPABILITIES, *HARNESS_CAPABILITIES])
        advertised = set(answer["payload"]["daemon"]["capabilities"])
        granted = set(answer["payload"]["granted_capabilities"])
        for capability in HARNESS_CAPABILITIES:
            assert capability in advertised
            assert capability in granted
    finally:
        registry.stop()


def test_harness_commands_need_their_capability(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    workspace = build_workspace(root, knowledge=False, code_graph=False)
    registry = LocalFeatureRegistry(
        workspace_configs=lambda profile: [workspace.config],
        cache_root=tmp_path / "cache",
    )
    controller_ = controller(tmp_path, registry)
    registry.start(controller_._profile())
    try:
        service = BridgeService(controller_)
        negotiate(service, ["daemon.control", "harness.read"])
        allowed = service.handle_line(bridge_request("harness.detect", SCOPE))
        assert allowed["kind"] != "error", allowed
        refused = service.handle_line(
            bridge_request("harness.preview", {**SCOPE, "adapter_id": "claude-code"})
        )
        assert refused["kind"] == "error"
        assert refused["error"]["code"] == "capability_missing"
    finally:
        registry.stop()


def test_a_daemon_without_local_features_does_not_serve_the_harness_commands(
    tmp_path: Path,
) -> None:
    from studio_client.config import ClientConfig
    from studio_client.daemon.service import DaemonController

    controller_ = DaemonController(
        ClientConfig(
            api_base_url="https://studio.example/api/v1",
            profile_id="main",
            machine_id=WORKSPACE_ID,
        ),
        data_root=tmp_path,
    )
    service = BridgeService(controller_)
    negotiate(service, [*DESKTOP_CAPABILITIES, *HARNESS_CAPABILITIES])
    refused = service.handle_line(bridge_request("harness.detect", SCOPE))
    assert refused["kind"] == "error"
    assert refused["error"]["code"] == "capability_missing"


# --- scenarios A–J ----------------------------------------------------------


def test_a_list_and_detect_over_the_bridge(bridge: Bridge) -> None:
    assert bridge.states() == {
        "claude-code": "detected",
        "opencode": "detected",
    }
    status = bridge.ok("harness.status", {**SCOPE, "adapter_id": "claude-code"})
    assert status["detected_version"] == "2.1.272"


def test_b_preview_writes_nothing(bridge: Bridge) -> None:
    plan = bridge.preview("claude-code")
    assert [change["kind"] for change in plan["changes"]] == ["create"]
    assert plan["changes"][0]["target"] == ".mcp.json"
    assert not (bridge.root / ".mcp.json").exists()
    assert not bridge.backups.exists() or not any(bridge.backups.rglob("*.bak"))


def test_c_apply_writes_on_the_temp_workspace(bridge: Bridge) -> None:
    result = bridge.apply(bridge.preview("claude-code"))
    assert result["state"] == "configured"
    assert result["rollback_id"]
    data = json.loads((bridge.root / ".mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["studio-os"]["url"] == MCP_URL
    assert bridge.states()["claude-code"] == "configured"


def test_d_second_apply_is_idempotent(bridge: Bridge) -> None:
    bridge.apply(bridge.preview("claude-code"))
    before = (bridge.root / ".mcp.json").read_bytes()
    backups = sorted(bridge.backups.rglob("manifest.json"))
    plan = bridge.preview("claude-code")
    assert plan["changes"] == []
    assert (bridge.root / ".mcp.json").read_bytes() == before
    assert sorted(bridge.backups.rglob("manifest.json")) == backups


def test_e_other_servers_are_preserved(bridge: Bridge) -> None:
    (bridge.root / "opencode.json").write_text(
        json.dumps({"mcp": {"other": {"type": "local", "command": ["x"]}}, "theme": "dark"}),
        encoding="utf-8",
    )
    bridge.apply(bridge.preview("opencode"))
    data = json.loads((bridge.root / "opencode.json").read_text(encoding="utf-8"))
    assert data["mcp"]["other"] == {"type": "local", "command": ["x"]}
    assert data["theme"] == "dark"
    assert "studio-os" in data["mcp"]


def test_f_rollback_restores_the_original(bridge: Bridge) -> None:
    original = json.dumps({"mcpServers": {"other": {"command": "x"}}}, indent=2)
    (bridge.root / ".mcp.json").write_text(original, encoding="utf-8")
    applied = bridge.apply(bridge.preview("claude-code"))
    rolled = bridge.ok(
        "harness.rollback", {"rollback_id": applied["rollback_id"], "confirmed": True}
    )
    assert rolled["state"] == "detected"
    assert (bridge.root / ".mcp.json").read_text(encoding="utf-8") == original


def test_g_rollback_conflict_after_a_user_edit(bridge: Bridge) -> None:
    applied = bridge.apply(bridge.preview("claude-code"))
    path = bridge.root / ".mcp.json"
    edited = path.read_text(encoding="utf-8").replace("{", '{"mine": 1,', 1)
    path.write_text(edited, encoding="utf-8")
    answer = bridge.call(
        "harness.rollback", {"rollback_id": applied["rollback_id"], "confirmed": True}
    )
    assert answer["kind"] == "error"
    assert answer["error"]["details"]["reason"] == "rollback_conflict"
    assert path.read_text(encoding="utf-8") == edited


def test_h_invalid_configuration_fails_closed(bridge: Bridge) -> None:
    path = bridge.root / ".mcp.json"
    path.write_text('{"mcpServers": {', encoding="utf-8")
    assert bridge.states()["claude-code"] == "error"
    answer = bridge.call("harness.preview", {**SCOPE, "adapter_id": "claude-code"})
    assert answer["kind"] == "error"
    assert path.read_text(encoding="utf-8") == '{"mcpServers": {'


def test_preview_is_refused_when_the_feature_is_disabled(tmp_path: Path) -> None:
    with _make_bridge(tmp_path, harness=False) as bridge:
        answer = bridge.call("harness.preview", {**SCOPE, "adapter_id": "claude-code"})
        assert answer["kind"] == "error"
        assert answer["error"]["code"] == "feature_disabled"
        assert bridge.states()["claude-code"] == "detected"


def test_absent_harnesses_are_reported_not_detected(tmp_path: Path) -> None:
    with _make_bridge(tmp_path, harness=True, harnesses=False) as bridge:
        assert set(bridge.states().values()) == {"not_detected"}


def test_verify_unconfigured_before_apply(bridge: Bridge) -> None:
    """verify returns UNCONFIGURED when the harness is not yet applied."""
    result = bridge.call("harness.verify", {**SCOPE, "adapter_id": "claude-code"})
    assert result["kind"] != "error", result
    assert result["payload"]["state"] == "unconfigured"
    assert result["payload"]["adapter_id"] == "claude-code"
    assert result["payload"]["mcp_url"] is None
    assert result["payload"]["error"] is None


def test_verify_configured_after_apply(bridge: Bridge) -> None:
    """verify returns CONFIGURED after apply (without token, no VERIFIED)."""
    bridge.apply(bridge.preview("claude-code"))
    result = bridge.call("harness.verify", {**SCOPE, "adapter_id": "claude-code"})
    assert result["kind"] != "error", result
    assert result["payload"]["state"] == "configured"
    assert result["payload"]["adapter_id"] == "claude-code"
    assert result["payload"]["mcp_url"] == MCP_URL
    assert result["payload"]["error"] is None
    assert result["payload"]["details"]["reason"] == "token_missing"


def test_j_no_provider_credential_is_involved(bridge: Bridge) -> None:
    bridge.env["ANTHROPIC_API_KEY"] = "sk-SECRET-VALUE-123456"
    bridge.env["OPENAI_API_KEY"] = "sk-SECRET-VALUE-123456"
    bridge.env["STUDIO_MCP_MACHINE_TOKEN"] = "sk-SECRET-VALUE-123456"
    answers = [
        bridge.call("harness.detect", SCOPE),
        bridge.call("harness.preview", {**SCOPE, "adapter_id": "claude-code"}),
    ]
    applied = bridge.apply(bridge.preview("claude-code"))
    answers.append(applied)
    assert "SECRET-VALUE" not in json.dumps(answers)
    assert "SECRET-VALUE" not in (bridge.root / ".mcp.json").read_text(encoding="utf-8")
    for file in bridge.backups.rglob("*"):
        if file.is_file():
            assert "SECRET-VALUE" not in file.read_text(encoding="utf-8", errors="replace")
