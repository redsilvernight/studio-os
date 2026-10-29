from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.harness.base import AccessMode, AdapterRefusal
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.codex import CodexAdapter
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.service import HarnessServiceError
from studio_contracts.local import fixtures
from studio_contracts.local.bridge import BRIDGE_COMMANDS, BridgeCommand
from studio_contracts.local.handshake import (
    CompatibilityOutcome,
    HandshakeRequest,
    negotiate,
)
from studio_contracts.local.harness import HarnessLaunchPreview, HarnessStatusRequest

from tests.harness.support import MCP_URL, WORKSPACE_ID, make_rig


@pytest.mark.parametrize(
    "session,guard", [(False, False), (True, False), (False, True), (True, True)]
)
def test_claude_preview_matches_the_hooks_passed_to_the_runner(
    tmp_path: Path, session: bool, guard: bool
) -> None:
    rig = make_rig(tmp_path)
    scripts = rig.home / ".claude/scripts"
    scripts.mkdir(parents=True)
    for present, filename in (
        (session, "studio-session-start.ps1"),
        (guard, "studio-git-guard.ps1"),
    ):
        if present:
            (scripts / filename).write_text("secret hook command", encoding="utf-8")
    rig.claude_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "studio-os": {"url": MCP_URL, "headers": {"Authorization": "Bearer PRIVATE"}},
                    "personal-private-server": {"command": "PRIVATE"},
                }
            }
        ),
        encoding="utf-8",
    )
    adapter = ClaudeCodeAdapter()
    preview = adapter.launch_preview(rig.context)
    argv = adapter.headless_extra_argv(rig.context, model=None, isolation_dir=tmp_path)
    settings = json.loads(argv[argv.index("--settings") + 1]) if "--settings" in argv else {}
    actual_hooks = settings.get("hooks", {})

    assert (preview.hooks[0].state == "included") is ("SessionStart" in actual_hooks)
    assert (preview.hooks[1].state == "included") is ("PreToolUse" in actual_hooks)
    assert preview.mcp_servers[0].state == "included"
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert adapter.headless_safety_argv(
        allow_production=False, mode=AccessMode.WORKSPACE_WRITE
    ) == ("--restricted", "--tools", "Read,Edit,Write,Grep,Glob")
    rendered = preview.model_dump_json()
    for forbidden in (
        str(rig.home),
        "PRIVATE",
        "personal-private-server",
        "secret hook command",
        MCP_URL,
    ):
        assert forbidden not in rendered


def test_missing_studio_mcp_is_reported_and_runner_still_refuses(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    adapter = ClaudeCodeAdapter()
    assert adapter.launch_preview(rig.context).mcp_servers[0].state == "unavailable"
    with pytest.raises(AdapterRefusal, match="mcp_entry_missing"):
        adapter.headless_environment(
            rig.context, model=None, isolation_dir=tmp_path, credential="test"
        )


@pytest.mark.parametrize("installed", [True, False])
def test_opencode_preview_matches_the_copied_plugin(tmp_path: Path, installed: bool) -> None:
    rig = make_rig(tmp_path)
    rig.opencode_config.parent.mkdir(parents=True, exist_ok=True)
    rig.opencode_config.write_text(
        json.dumps(
            {
                "mcp": {
                    "studio-os": {
                        "type": "remote",
                        "url": MCP_URL,
                        "headers": {"Authorization": "Bearer PRIVATE"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    plugin_dir = rig.opencode_config.parent / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "personal.js").write_text("PRIVATE", encoding="utf-8")
    if installed:
        (plugin_dir / "studio-os.js").write_text("studio", encoding="utf-8")
    adapter = OpenCodeAdapter()
    preview = adapter.launch_preview(rig.context)
    isolation = tmp_path / "isolated"
    isolation.mkdir()
    env = adapter.headless_environment(
        rig.context, model=None, isolation_dir=isolation, credential="test"
    )
    assert (preview.hooks[0].state == "included") is (
        isolation / "opencode/plugins/studio-os.js"
    ).is_file()
    assert not (isolation / "opencode/plugins/personal.js").exists()
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert list(json.loads(env["OPENCODE_CONFIG_CONTENT"])["mcp"]) == ["studio-os"]
    assert preview.production_approval_required
    assert preview.access_modes == ["workspace_write"]
    with pytest.raises(AdapterRefusal, match="production_safety_unsupported"):
        adapter.headless_safety_argv(allow_production=False, mode=AccessMode.WORKSPACE_WRITE)
    assert "PRIVATE" not in preview.model_dump_json()


def test_codex_does_not_claim_an_isolation_it_does_not_implement(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    adapter = CodexAdapter()
    preview = adapter.launch_preview(rig.context)
    assert preview.isolation == "unverified"
    assert preview.hooks == preview.mcp_servers == preview.settings_sources == []
    assert preview.production_approval_required
    with pytest.raises(AdapterRefusal, match="production_safety_unsupported"):
        adapter.headless_safety_argv(allow_production=False, mode=AccessMode.READ_ONLY)


def test_service_preview_is_read_only_even_when_integrations_are_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path)
    rig.flags["enabled"] = False

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("preview must not provision, probe, plan or write")

    monkeypatch.setattr(rig.service, "_retry_revocations", forbidden)
    monkeypatch.setattr(rig.cli, "__call__", forbidden)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = rig.service.launch_preview(
        HarnessStatusRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    assert isinstance(result, HarnessLaunchPreview)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert not rig.service._plans
    assert not rig.flags["enabled"]


def test_unknown_workspace_or_adapter_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    for workspace_id, adapter_id in ((uuid4(), "claude-code"), (WORKSPACE_ID, "unknown")):
        with pytest.raises(HarnessServiceError):
            rig.service.launch_preview(
                HarnessStatusRequest(workspace_id=workspace_id, adapter_id=adapter_id)
            )


def test_preview_capability_is_optional_in_both_upgrade_directions() -> None:
    capability = "harness.launch_preview"
    request = HandshakeRequest(peer=fixtures.desktop_peer())
    current = negotiate(request, fixtures.daemon_peer())
    old_daemon = negotiate(request, fixtures.daemon_peer(drop=frozenset({capability})))
    old_desktop = request.model_copy(
        update={
            "peer": request.peer.model_copy(
                update={
                    "capabilities": [c for c in request.peer.capabilities if c != capability],
                    "optional_capabilities": [
                        c for c in request.peer.optional_capabilities if c != capability
                    ],
                }
            )
        }
    )
    assert capability in current.granted_capabilities
    assert old_daemon.outcome is CompatibilityOutcome.COMPATIBLE_DEGRADED
    assert capability in old_daemon.missing_optional
    assert capability not in old_daemon.granted_capabilities
    assert negotiate(old_desktop, fixtures.daemon_peer()).outcome is CompatibilityOutcome.COMPATIBLE
    spec = BRIDGE_COMMANDS[BridgeCommand.HARNESS_LAUNCH_PREVIEW]
    assert not spec.mutating
    assert spec.capability == capability
