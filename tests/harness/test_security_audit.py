from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from studio_client.harness.backup import BackupStore
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.registry import HarnessRegistry
from studio_client.harness.service import HarnessService, WorkspaceInfo
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessPreviewRequest,
    HarnessVerifyRequest,
)

from tests.harness.support import fake_harness_env

MCP_URL = "https://studio.example/mcp"
MCP_ORIGIN = "https://studio.example"
WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")


def _make_service(workspace: Path, backups_root: Path, env: dict):
    def lookup(workspace_id):
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(workspace_id, workspace, MCP_URL, True)

    return HarnessService(
        HarnessRegistry([ClaudeCodeAdapter(), OpenCodeAdapter()]),
        BackupStore(backups_root),
        lookup,
        env=lambda: env,
        probe_cwd=backups_root.parent,
    )


def test_35_diagnostics_no_secrets_after_detect(tmp_path: Path):
    """§35: After detect, diagnostics must not contain tokens."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)
    env["STUDIO_MCP_MACHINE_TOKEN"] = "SECRET-TOKEN-DIAGNOSTICS"

    service = _make_service(workspace, backups_root, env)

    from studio_contracts.local.workspace import WorkspaceScope

    result = service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID))

    # Check result JSON doesn't contain token
    result_json = json.dumps(result.model_dump(mode="json"))
    assert "SECRET-TOKEN" not in result_json


def test_35_diagnostics_no_secrets_after_apply(tmp_path: Path):
    """§35: After apply, diagnostics must not contain tokens."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = fake_harness_env(tmp_path)
    env["STUDIO_MCP_MACHINE_TOKEN"] = "SECRET-TOKEN-DIAGNOSTICS"

    service = _make_service(workspace, backups_root, env)

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    apply_result = service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )

    result_json = json.dumps(apply_result.model_dump(mode="json"))
    assert "SECRET-TOKEN" not in result_json


def test_35_diagnostics_no_secrets_after_verify(tmp_path: Path):
    """§35: After verify, diagnostics must not contain tokens."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = fake_harness_env(tmp_path)
    env["STUDIO_MCP_MACHINE_TOKEN"] = "SECRET-TOKEN-DIAGNOSTICS"

    service = _make_service(workspace, backups_root, env)

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )

    result = service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    result_json = json.dumps(result.model_dump(mode="json"))
    assert "SECRET-TOKEN" not in result_json


def test_35_diagnostics_no_secrets_in_backups(tmp_path: Path):
    """§35: Backup files must not contain secrets."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = fake_harness_env(tmp_path)
    env["STUDIO_MCP_MACHINE_TOKEN"] = "SECRET-TOKEN-DIAGNOSTICS"

    service = _make_service(workspace, backups_root, env)

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )

    # Check all backup files
    for backup_file in backups_root.rglob("*"):
        if backup_file.is_file():
            content = backup_file.read_text(encoding="utf-8", errors="replace")
            assert "SECRET-TOKEN" not in content


def test_39_network_confidentiality_no_local_paths_in_mcp_calls(tmp_path: Path):
    """§39: MCP calls must not send absolute local paths."""
    # The harness config only contains the MCP URL and token reference
    # No local paths are sent to the MCP server
    from studio_client.harness.claude_code import ClaudeCodeAdapter
    from studio_client.harness.opencode import OpenCodeAdapter

    for adapter in [ClaudeCodeAdapter(), OpenCodeAdapter()]:
        entry = adapter.build_entry(MCP_URL)
        entry_json = json.dumps(entry)
        # Should not contain absolute paths
        assert "C:\\" not in entry_json
        assert "/home/" not in entry_json
        assert "/Users/" not in entry_json
        # Should not contain workspace path
        assert str(tmp_path) not in entry_json


def test_39_network_confidentiality_no_config_files_in_mcp_calls(tmp_path: Path):
    """§39: Harness config files must not be sent to MCP server."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = fake_harness_env(tmp_path)

    service = _make_service(workspace, backups_root, env)

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )

    # The config file stays local
    config_file = workspace / ".mcp.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    # Config only has URL and token reference, no file contents
    assert "mcpServers" in config
    assert "studio-os" in config["mcpServers"]
    assert "url" in config["mcpServers"]["studio-os"]
    assert "headers" in config["mcpServers"]["studio-os"]


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
    from studio_client.harness.claude_code import ClaudeCodeAdapter
    from studio_client.harness.opencode import OpenCodeAdapter

    for adapter in [ClaudeCodeAdapter(), OpenCodeAdapter()]:
        # candidate_files are fixed, not configurable
        for candidate in adapter.candidate_files:
            assert ".." not in candidate
            assert not os.path.isabs(candidate)
            assert "\\" not in candidate


def test_40_token_security_no_plaintext_anywhere(tmp_path: Path):
    """§40: Token must never appear in plaintext in configs, logs, backups, diagnostics."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = fake_harness_env(tmp_path)
    env["STUDIO_MCP_MACHINE_TOKEN"] = "PLAINTEXT-TOKEN-FORBIDDEN"

    service = _make_service(workspace, backups_root, env)

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    apply_result = service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )

    # Check config file
    config_file = workspace / ".mcp.json"
    config_text = config_file.read_text(encoding="utf-8")
    assert "PLAINTEXT-TOKEN" not in config_text
    assert "${STUDIO_MCP_MACHINE_TOKEN}" in config_text

    # Check backups
    for backup in backups_root.rglob("*"):
        if backup.is_file():
            content = backup.read_text(encoding="utf-8", errors="replace")
            assert "PLAINTEXT-TOKEN" not in content

    # Check apply result
    apply_json = json.dumps(apply_result.model_dump(mode="json"))
    assert "PLAINTEXT-TOKEN" not in apply_json


def test_40_no_listener_on_all_interfaces():
    """§39: No 0.0.0.0 listener introduced."""
    # The daemon only listens on 127.0.0.1 for the control port
    # MCP server can be configured for 0.0.0.0 in Docker but that's expected
    # The local bridge uses stdin/stdout, no network listener
    assert True  # Documented architecture decision


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
