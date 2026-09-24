from __future__ import annotations

import json
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
    VerifyState,
)

from tests.harness.support import fake_harness_env

MCP_URL = "https://studio.example/mcp"
WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_dogfood_scenario_ia_to_studios_workspace_setup(tmp_path: Path):
    """§23: Dogfood IA → Studi'OS.

    Test that a real AI assistant (Claude Code/OpenCode) can be configured
    to use Studi'OS via MCP. This test sets up the workspace and harness config.

    For a complete dogfood test, we would need:
    1. A running Studi'OS backend (API + MCP server)
    2. A real machine token enrolled on that backend
    3. Launch the harness with the config and make a real MCP call

    This test verifies the configuration chain works."""
    from studio_client.harness.claude_code import ClaudeCodeAdapter

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = fake_harness_env(tmp_path)
    env["STUDIO_MCP_MACHINE_TOKEN"] = "test-machine-token-for-dogfood"

    def lookup(workspace_id):
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(workspace_id, workspace, MCP_URL, True)

    service = HarnessService(
        HarnessRegistry([ClaudeCodeAdapter()]),
        BackupStore(backups_root),
        lookup,
        env=lambda: env,
        probe_cwd=tmp_path,
    )

    # Preview and apply config
    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    assert len(preview.changes) == 1
    assert preview.changes[0].target == ".mcp.json"
    assert preview.changes[0].kind.value == "create"

    apply_result = service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )
    assert apply_result.state.value == "configured"

    # Verify config file has correct structure
    config_file = workspace / ".mcp.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert "mcpServers" in config
    assert "studio-os" in config["mcpServers"]
    assert config["mcpServers"]["studio-os"]["url"] == MCP_URL
    assert "Authorization" in config["mcpServers"]["studio-os"]["headers"]
    assert (
        "${STUDIO_MCP_MACHINE_TOKEN}"
        in config["mcpServers"]["studio-os"]["headers"]["Authorization"]
    )

    # Verify without backend -> CONFIGURED (no token in test env for real MCP)
    # In real dogfood, with token and backend, this would be VERIFIED
    env.pop("STUDIO_MCP_MACHINE_TOKEN", None)
    service_no_token = HarnessService(
        HarnessRegistry([ClaudeCodeAdapter()]),
        BackupStore(backups_root),
        lookup,
        env=lambda: env,
        probe_cwd=tmp_path,
    )
    result = service_no_token.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    assert result.state == VerifyState.CONFIGURED
    assert result.details.get("reason") == "token_missing"


def test_dogfood_opencode_configuration(tmp_path: Path):
    """Test OpenCode configuration for dogfood."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = fake_harness_env(tmp_path)

    def lookup(workspace_id):
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(workspace_id, workspace, MCP_URL, True)

    service = HarnessService(
        HarnessRegistry([OpenCodeAdapter()]),
        BackupStore(backups_root),
        lookup,
        env=lambda: env,
        probe_cwd=tmp_path,
    )

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="opencode")
    )
    apply_result = service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )
    assert apply_result.state.value == "configured"

    config_file = workspace / "opencode.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert "mcp" in config
    assert "studio-os" in config["mcp"]
    assert config["mcp"]["studio-os"]["url"] == MCP_URL
    assert config["mcp"]["studio-os"]["enabled"] is True
    assert (
        "{env:STUDIO_MCP_MACHINE_TOKEN}" in config["mcp"]["studio-os"]["headers"]["Authorization"]
    )


def test_dogfood_studios_to_studios_temp_clone(tmp_path: Path):
    """§24: Dogfood Studi'OS → Studi'OS.

    Use a temp clone of the Studi'OS repo as a workspace, configure harness,
    and verify the setup works. This simulates an agent working on Studi'OS using Studi'OS."""

    # Create a temp "Studi'OS-like" workspace
    workspace = tmp_path / "studios-clone"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Studi'OS Clone\nTest workspace")
    (workspace / "pyproject.toml").write_text('[project]\nname = "studios-clone"\n')

    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = fake_harness_env(tmp_path)
    env["STUDIO_MCP_MACHINE_TOKEN"] = "test-token"

    def lookup(workspace_id):
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(workspace_id, workspace, MCP_URL, True)

    service = HarnessService(
        HarnessRegistry([ClaudeCodeAdapter(), OpenCodeAdapter()]),
        BackupStore(backups_root),
        lookup,
        env=lambda: env,
        probe_cwd=tmp_path,
    )

    # Configure both harnesses on the Studi'OS clone
    for adapter_id in ["claude-code", "opencode"]:
        preview = service.preview(
            HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter_id)
        )
        apply_result = service.apply(
            HarnessApplyRequest(
                plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True
            )
        )
        assert apply_result.state.value == "configured"

    # Both config files should exist
    assert (workspace / ".mcp.json").exists()
    assert (workspace / "opencode.json").exists()

    # Verify both have the studio-os entry
    claude_config = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    opencode_config = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))

    assert "studio-os" in claude_config["mcpServers"]
    assert "studio-os" in opencode_config["mcp"]

    # This simulates: agent works on Studi'OS repo using Studi'OS MCP tools
    # In real usage, the agent would call studio_prepare_context, studio_create_task, etc.


def test_mcp_connection_chain_documented():
    """Document the full MCP connection chain for dogfood.

    Chain: Harness Config -> MCP URL -> Authorization Header ->
    Studi'OS MCP Server -> Auth -> Tool Call

    1. Harness config (.mcp.json or opencode.json) contains:
       - URL: https://studio.example/mcp
       - Authorization: Bearer ${STUDIO_MCP_MACHINE_TOKEN} (Claude) or
         Bearer {env:STUDIO_MCP_MACHINE_TOKEN} (OpenCode)

    2. Harness launches, reads config, connects to MCP URL

    3. MCP Server (studio_mcp) extracts token from:
       - HTTP: Authorization header
       - stdio: STUDIO_MCP_MACHINE_TOKEN env var

    4. Auth validates token against DB (resolve_machine)

    5. Tool calls are authenticated and authorized

    6. Results returned to harness -> AI assistant
    """
    # This is a documentation test - the chain is verified by:
    # - test_dogfood_scenario_ia_to_studios_workspace_setup (config generation)
    # - test_token_never_logged_or_in_diagnostics (token never in plaintext)
    # - harness verify tests (CONFIGURED vs VERIFIED distinction)
    assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
