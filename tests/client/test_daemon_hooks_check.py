"""`hooks.check`: read-only hook state over the daemon bridge."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from studio_client.config import ClientConfig
from studio_client.daemon import hooks_check
from studio_client.daemon.service import BridgeService, DaemonController
from studio_client.hooks import HARNESSES, deploy_guard, deploy_hooks, is_managed
from studio_client.opencode_plugin import deploy_plugin
from studio_client.tokens import MemoryTokenStore
from studio_contracts.local.bridge import BridgeRequest
from studio_contracts.local.handshake import HandshakeRequest
from studio_contracts.local.machine_setup import HookCheckState, SetupHooksCheckResult

ORIGIN = "https://studio.example"
SPECS = {spec.harness: spec for spec in HARNESSES}


def _controller(tmp_path: Path, home: Path, token: str | None = "tok") -> DaemonController:
    store = MemoryTokenStore()
    if token:
        store.set_token(ORIGIN, token)
    config = ClientConfig(api_base_url=f"{ORIGIN}/api/v1", profile_id="main", machine_id=uuid4())
    return DaemonController(config, data_root=tmp_path, token_store=store, skills_home=lambda: home)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _line(command: str, payload: dict) -> str:
    return BridgeRequest.model_validate(
        {
            "message_id": f"msg-{uuid4().hex[:16]}",
            "correlation_id": f"corr-{uuid4().hex[:16]}",
            "sent_at": "2026-09-21T00:00:00Z",
            "command": command,
            "payload": payload,
        }
    ).model_dump_json()


def _negotiate(service: BridgeService, capabilities: list[str]) -> dict:
    payload = HandshakeRequest.model_validate(
        {
            "peer": {
                "role": "desktop",
                "protocol": {
                    "minimum": {"major": 1, "minor": 0},
                    "maximum": {"major": 1, "minor": 0},
                },
                "component_version": "0.1.0",
                "capabilities": capabilities,
                "required_capabilities": ["daemon.control"],
            }
        }
    )
    return service.handle_line(_line("runtime.handshake", payload.model_dump(mode="json")))


def test_all_missing_then_up_to_date_after_deploy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    # Set up markers for all three harnesses
    (home / ".claude.json").write_text("{}", encoding="utf-8")
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.jsonc").write_text("{}", encoding="utf-8")
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text("", encoding="utf-8")
    controller = _controller(tmp_path, home)

    # All missing initially
    before = controller.hooks_check()
    assert len(before.hooks) == 3
    for entry in before.hooks:
        assert entry.hook_state == HookCheckState.MISSING
        if entry.guard_state is not None:
            assert entry.guard_state == HookCheckState.MISSING
        if entry.plugin_state is not None:
            assert entry.plugin_state == HookCheckState.MISSING

    # Deploy all hooks, guard, and plugin
    deploy_hooks(home, list(HARNESSES))
    deploy_guard(home)
    deploy_plugin(home)

    after = controller.hooks_check()
    assert len(after.hooks) == 3
    for entry in after.hooks:
        assert entry.hook_state == HookCheckState.MANAGED
        if entry.guard_state is not None:
            assert entry.guard_state == HookCheckState.MANAGED
        if entry.plugin_state is not None:
            assert entry.plugin_state == HookCheckState.MANAGED


def test_foreign_hook_reported(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    # Set up opencode marker
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.jsonc").write_text("{}", encoding="utf-8")
    controller = _controller(tmp_path, home)

    # Create a foreign hook file for opencode
    spec = SPECS["opencode"]
    target = home / spec.hook_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# operator's own hook\n", encoding="utf-8")

    result = controller.hooks_check()
    opencode_entry = next(e for e in result.hooks if e.harness == "opencode")
    assert opencode_entry.hook_state == HookCheckState.FOREIGN
    assert opencode_entry.guard_state == HookCheckState.MISSING
    assert opencode_entry.plugin_state == HookCheckState.MISSING

    # Other harnesses still missing
    for entry in result.hooks:
        if entry.harness != "opencode":
            assert entry.hook_state == HookCheckState.MISSING


def test_managed_copy_edited_by_hand_is_foreign(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    # Set up codex marker
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text("", encoding="utf-8")
    controller = _controller(tmp_path, home)

    # Deploy managed hook
    deploy_hooks(home, [SPECS["codex"]])
    target = home / SPECS["codex"].hook_rel
    assert is_managed(target)

    # Edit the managed copy
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")

    result = controller.hooks_check()
    codex_entry = next(e for e in result.hooks if e.harness == "codex")
    assert codex_entry.hook_state == HookCheckState.FOREIGN


def test_guard_states(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    controller = _controller(tmp_path, home)

    # No guard
    result = controller.hooks_check()
    for entry in result.hooks:
        if entry.guard_state is not None:
            assert entry.guard_state == HookCheckState.MISSING

    # Foreign guard
    guard_target = home / ".claude" / "scripts" / "studio-git-guard.ps1"
    guard_target.parent.mkdir(parents=True, exist_ok=True)
    guard_target.write_text("# operator's own guard\n", encoding="utf-8")

    result = controller.hooks_check()
    for entry in result.hooks:
        if entry.guard_state is not None:
            assert entry.guard_state == HookCheckState.FOREIGN

    # Managed guard
    deploy_guard(home)
    result = controller.hooks_check()
    for entry in result.hooks:
        if entry.guard_state is not None:
            assert entry.guard_state == HookCheckState.MANAGED


def test_plugin_states(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    # Set up opencode marker
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.jsonc").write_text("{}", encoding="utf-8")
    controller = _controller(tmp_path, home)

    # No plugin
    result = controller.hooks_check()
    opencode_entry = next(e for e in result.hooks if e.harness == "opencode")
    assert opencode_entry.plugin_state == HookCheckState.MISSING

    # Foreign plugin
    plugin_target = home / ".config" / "opencode" / "plugins" / "studio-os.js"
    plugin_target.parent.mkdir(parents=True, exist_ok=True)
    plugin_target.write_text("// operator's own plugin\n", encoding="utf-8")

    result = controller.hooks_check()
    opencode_entry = next(e for e in result.hooks if e.harness == "opencode")
    assert opencode_entry.plugin_state == HookCheckState.FOREIGN

    # Managed plugin
    deploy_plugin(home, overwrite=True)
    result = controller.hooks_check()
    opencode_entry = next(e for e in result.hooks if e.harness == "opencode")
    assert opencode_entry.plugin_state == HookCheckState.MANAGED


def test_served_over_bridge_without_path_or_content(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    deploy_hooks(home, list(HARNESSES))
    deploy_guard(home)
    deploy_plugin(home)
    service = BridgeService(_controller(tmp_path, home))
    _negotiate(service, ["daemon.control", "setup.plan"])
    answer = service.handle_line(_line("hooks.check", {}))
    assert answer["kind"] == "response", answer
    raw = json.dumps(answer, default=str)
    assert str(tmp_path) not in raw
    assert ".claude" not in raw or "scripts" not in raw  # no absolute paths
    SetupHooksCheckResult.model_validate(answer["payload"])


def test_denied_without_capability(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    service = BridgeService(_controller(tmp_path, home))
    _negotiate(service, ["daemon.control"])
    answer = service.handle_line(_line("hooks.check", {}))
    assert answer["kind"] != "response", answer


def test_handshake_offers_setup_plan_capability(tmp_path: Path) -> None:
    service = BridgeService(_controller(tmp_path, tmp_path))
    answer = _negotiate(service, ["daemon.control", "setup.plan"])
    assert "setup.plan" in json.dumps(answer)


def test_detection_by_config_marker(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    controller = _controller(tmp_path, home)

    # No harness detected initially
    result = controller.hooks_check()
    assert len(result.hooks) == 0

    # Add config marker for claude-code
    marker = home / ".claude.json"
    marker.write_text("{}", encoding="utf-8")

    result = controller.hooks_check()
    assert len(result.hooks) == 1
    assert result.hooks[0].harness == "claude-code"
    assert result.hooks[0].label == "Claude Code"
    assert result.hooks[0].hook_state == HookCheckState.MISSING


def test_detection_by_binary(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    controller = _controller(tmp_path, home)

    # No harness detected initially
    result = controller.hooks_check()
    assert len(result.hooks) == 0

    # Add binary for opencode
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "opencode.exe").write_text("stub", encoding="utf-8")

    # Need to pass path_dirs to detect
    result = hooks_check.check_hooks(
        ClientConfig(api_base_url=f"{ORIGIN}/api/v1", profile_id="main", machine_id=uuid4()),
        MemoryTokenStore(),
        home=home,
        path_dirs=lambda: (str(bindir),),
    )
    assert len(result.hooks) == 1
    assert result.hooks[0].harness == "opencode"
    assert result.hooks[0].label == "OpenCode"


def test_only_detected_harnesses_are_reported(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    controller = _controller(tmp_path, home)

    # Add marker only for codex
    marker_dir = home / ".codex"
    marker_dir.mkdir()
    (marker_dir / "config.toml").write_text("", encoding="utf-8")

    result = controller.hooks_check()
    assert len(result.hooks) == 1
    assert result.hooks[0].harness == "codex"
    assert result.hooks[0].label == "Codex"


def test_guard_only_for_claude_and_opencode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    controller = _controller(tmp_path, home)

    # Add markers for all three
    (home / ".claude.json").write_text("{}", encoding="utf-8")
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.jsonc").write_text("{}", encoding="utf-8")
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text("", encoding="utf-8")

    result = controller.hooks_check()
    for entry in result.hooks:
        if entry.harness in {"claude-code", "opencode"}:
            assert entry.guard_state is not None
        elif entry.harness == "codex":
            assert entry.guard_state is None


def test_plugin_only_for_opencode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    controller = _controller(tmp_path, home)

    # Add markers for all three
    (home / ".claude.json").write_text("{}", encoding="utf-8")
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.jsonc").write_text("{}", encoding="utf-8")
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text("", encoding="utf-8")

    result = controller.hooks_check()
    for entry in result.hooks:
        if entry.harness == "opencode":
            assert entry.plugin_state is not None
        else:
            assert entry.plugin_state is None
