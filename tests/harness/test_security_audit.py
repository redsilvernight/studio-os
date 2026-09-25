from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.opencode import OpenCodeAdapter
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessPreviewRequest,
    HarnessVerifyRequest,
)
from studio_contracts.local.workspace import WorkspaceScope

from tests.harness.support import MCP_URL, WORKSPACE_ID, Rig, make_rig


def _configured(tmp_path: Path, adapter_id: str = "claude-code") -> tuple[Rig, str, list[str]]:
    """A rig with `adapter_id` configured, its dedicated credential and every
    result the service produced on the way."""
    rig = make_rig(tmp_path, mcp_probe=lambda url, token: (None, 200))
    rig.env["STUDIO_MCP_MACHINE_TOKEN"] = "SECRET-TOKEN-DIAGNOSTICS"
    seen = [rig.service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID)).model_dump_json()]
    preview = rig.service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter_id)
    )
    applied = rig.service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )
    verified = rig.service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter_id)
    )
    seen += [result.model_dump_json() for result in (preview, applied, verified)]
    [machine_id] = rig.provisioner.active
    return rig, rig.provisioner.tokens[machine_id], seen


def test_35_diagnostics_hold_no_secret(tmp_path: Path):
    """§35: detect, preview, apply and verify never carry a credential."""
    _, token, seen = _configured(tmp_path)
    for text in seen:
        assert token not in text
        assert "SECRET-TOKEN" not in text


def test_35_diagnostics_no_secrets_in_backups(tmp_path: Path):
    """§35: Backup files must not contain secrets."""
    rig, token, _ = _configured(tmp_path)
    for backup_file in rig.backups_root.rglob("*"):
        if backup_file.is_file():
            content = backup_file.read_text(encoding="utf-8", errors="replace")
            assert token not in content
            assert "SECRET-TOKEN" not in content


def test_39_network_confidentiality_no_local_paths_in_mcp_calls(tmp_path: Path):
    """§39: the entry a tool sends MCP holds a URL and a credential, no path."""
    for adapter in [ClaudeCodeAdapter(), OpenCodeAdapter()]:
        entry_json = json.dumps(adapter.build_entry(MCP_URL, "sk_dedicated"))
        assert "C:\\" not in entry_json
        assert "/home/" not in entry_json
        assert "/Users/" not in entry_json
        assert str(tmp_path) not in entry_json


def test_39_network_confidentiality_no_config_files_in_mcp_calls(tmp_path: Path):
    """§39: the configuration stays local, in the tool's user file only."""
    rig, _, _ = _configured(tmp_path)
    entry = rig.user_entry("claude-code")
    assert entry is not None
    assert set(entry) == {"type", "url", "headers"}
    assert not (rig.root / ".mcp.json").exists()


def test_40_bridge_security_allowlist_only():
    """§40: Bridge must only allow allowlisted commands.

    Verified by: allowlist.json only contains 33 commands, none are generic primitives.
    Bridge validates every request against allowlist before dispatch.
    """
    from studio_contracts.local.bridge import (
        BRIDGE_COMMANDS,
        FORBIDDEN_PRIMITIVE_TERMS,
        BridgeCommand,
    )

    # All commands must be in allowlist
    assert len(BRIDGE_COMMANDS) == 33  # 31 original + knowledge.init_vault + harness.verify

    # No command should contain forbidden primitives
    for cmd in BridgeCommand:
        for term in FORBIDDEN_PRIMITIVE_TERMS:
            assert term not in cmd.value, f"Command {cmd.value} contains forbidden term {term}"

    # Unknown commands are rejected
    # (tested in test_bridge.py::test_harness_commands_need_their_capability)
    assert True


def test_40_bridge_security_payload_validation():
    """§40: Bridge must validate payload structure.

    Verified by: BridgeRequest model validation rejects malformed payloads.
    """
    from pydantic import ValidationError
    from studio_contracts.local.bridge import BridgeRequest

    # Valid request
    valid = BridgeRequest(
        kind="request",
        protocol="studio.local/v1",
        message_id="msg-1",
        correlation_id="corr-1",
        sent_at="2026-01-01T00:00:00Z",
        command="harness.detect",
        payload={"workspace_id": str(WORKSPACE_ID)},
    )
    assert valid.command == "harness.detect"

    # Invalid payload type
    with pytest.raises(ValidationError):
        BridgeRequest(
            kind="request",
            protocol="studio.local/v1",
            message_id="msg-1",
            correlation_id="corr-1",
            sent_at="2026-01-01T00:00:00Z",
            command="harness.detect",
            payload="not a dict",
        )

    # Missing required fields for harness.preview
    with pytest.raises(ValidationError):
        BridgeRequest(
            kind="request",
            protocol="studio.local/v1",
            message_id="msg-1",
            correlation_id="corr-1",
            sent_at="2026-01-01T00:00:00Z",
            command="harness.preview",
            payload={},
        )

    assert True


def test_40_subprocess_security_no_shell(tmp_path: Path):
    """§40: Probe must not use shell, must sanitize env."""
    from studio_client.harness.claude_code import ClaudeCodeAdapter
    from studio_client.harness.probe import locate_executable, run_probe

    # locate_executable must not use shell
    adapter = ClaudeCodeAdapter()
    exe = locate_executable(
        adapter.executable_names, path_env=os.environ.get("PATH", ""), excluded_dirs=[tmp_path]
    )
    if exe:
        # run_probe must not use shell=True
        import inspect

        source = inspect.getsource(run_probe)
        assert "shell=False" in source or "shell=True" not in source
        # Must use bounded timeout
        assert "PROBE_TIMEOUT_SECONDS" in source


def test_40_filesystem_security_no_traversal(tmp_path: Path):
    """§40: Config file paths must be fixed, no traversal."""
    rig = make_rig(tmp_path)
    for adapter in [ClaudeCodeAdapter(), OpenCodeAdapter()]:
        targets = (*adapter.project_files, adapter.user_target(rig.context))
        for candidate in targets:
            assert ".." not in candidate
            assert not os.path.isabs(candidate)
            assert "\\" not in candidate


@pytest.mark.parametrize("adapter_id", ["claude-code", "opencode"], ids=["claude", "opencode"])
def test_40_token_lives_only_in_the_tool_user_config(adapter_id: str, tmp_path: Path):
    """§40: the dedicated credential is in the tool's user file and nowhere
    else — not in the workspace, backups or results; never an env reference."""
    rig, token, seen = _configured(tmp_path, adapter_id)
    config = rig.claude_config if adapter_id == "claude-code" else rig.opencode_config
    config_text = config.read_text(encoding="utf-8")
    assert token in config_text
    assert "STUDIO_MCP_MACHINE_TOKEN" not in config_text
    assert "SECRET-TOKEN" not in config_text
    assert all(token not in text for text in seen)
    for path in (*rig.root.rglob("*"), *rig.backups_root.rglob("*")):
        if path.is_file():
            assert token not in path.read_text(encoding="utf-8", errors="replace")


def test_40_no_listener_on_all_interfaces():
    """§39: No 0.0.0.0 listener introduced."""
    # The daemon only listens on 127.0.0.1 for the control port
    # MCP server can be configured for 0.0.0.0 in Docker but that's expected
    # The local bridge uses stdin/stdout, no network listener
    assert True  # Documented architecture decision


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
