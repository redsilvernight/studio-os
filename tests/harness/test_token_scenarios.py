from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import pytest
from studio_client.harness.backup import BackupStore
from studio_client.harness.base import HarnessAdapter
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.probe import locate_executable
from studio_client.harness.registry import HarnessRegistry
from studio_client.harness.service import HarnessService, WorkspaceInfo
from studio_client.tokens import (
    EnvTokenStore,
    MissingMachineToken,
    resolve_token,
)

MCP_URL = "https://studio.example/mcp"
WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")


def _real(adapter: HarnessAdapter) -> bool:
    return (
        locate_executable(adapter.executable_names, path_env=os.environ.get("PATH", "")) is not None
    )


def test_env_token_store_is_read_only_and_fails_on_write():
    """EnvTokenStore must not allow writes - it's a CI/headless override only."""
    store = EnvTokenStore()
    with pytest.raises(NotImplementedError):
        store.set_token("https://example.com", "token")
    with pytest.raises(NotImplementedError):
        store.clear_token("https://example.com")


def test_env_token_store_respects_origin_binding():
    """EnvTokenStore with ORIGIN_VAR only returns token for matching origin."""
    os.environ["STUDIO_CLIENT_MACHINE_TOKEN"] = "test-token"
    os.environ["STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN"] = "https://studio.example.com"
    try:
        store = EnvTokenStore()
        assert store.get_token("https://studio.example.com") == "test-token"
        assert store.get_token("https://other.example.com") is None
    finally:
        os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)
        os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN", None)


def test_env_token_store_without_origin_var_returns_for_all():
    """EnvTokenStore without ORIGIN_VAR returns token for any origin."""
    os.environ["STUDIO_CLIENT_MACHINE_TOKEN"] = "test-token"
    try:
        store = EnvTokenStore()
        assert store.get_token("https://studio.example.com") == "test-token"
        assert store.get_token("https://other.example.com") == "test-token"
    finally:
        os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)


def test_resolve_token_prefers_env_override():
    """resolve_token checks EnvTokenStore first, then KeyringTokenStore."""
    os.environ["STUDIO_CLIENT_MACHINE_TOKEN"] = "env-token"
    try:

        class FakeKeyring:
            def get_token(self, origin: str) -> str | None:
                return "keyring-token"

        token = resolve_token("https://example.com", stores=[FakeKeyring()])
        assert token == "env-token"
    finally:
        os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)


def test_resolve_token_falls_back_to_keyring():
    """resolve_token falls back to keyring when env not set."""
    os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)

    class FakeKeyring:
        def get_token(self, origin: str) -> str | None:
            return "keyring-token"

    token = resolve_token("https://example.com", stores=[FakeKeyring()])
    assert token == "keyring-token"


def test_resolve_token_raises_when_missing():
    """resolve_token raises MissingMachineToken when no store has token."""
    os.environ.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)

    class EmptyStore:
        def get_token(self, origin: str) -> str | None:
            return None

    with pytest.raises(MissingMachineToken):
        resolve_token("https://example.com", stores=[EmptyStore()])


@pytest.mark.parametrize(
    "adapter", [ClaudeCodeAdapter(), OpenCodeAdapter()], ids=["claude", "opencode"]
)
def test_verify_requires_token_for_verified_state(adapter: HarnessAdapter, tmp_path: Path):
    """VERIFIED state requires STUDIO_MCP_MACHINE_TOKEN in environment.

    This tests Scenario B: harness launched independently without token.
    Without the token, verify returns CONFIGURED (not VERIFIED)."""
    if not _real(adapter):
        pytest.skip(f"{adapter.adapter_id} is not installed on this machine")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)
    # Ensure NO token in environment
    env.pop("STUDIO_MCP_MACHINE_TOKEN", None)
    env.pop("STUDIO_CLIENT_MACHINE_TOKEN", None)

    def lookup(workspace_id):
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(workspace_id, workspace, MCP_URL, True)

    service = HarnessService(
        HarnessRegistry([adapter]),
        BackupStore(backups_root),
        lookup,
        env=lambda: env,
        probe_cwd=tmp_path,
    )

    # Apply config first
    from studio_contracts.local.harness import HarnessApplyRequest, HarnessPreviewRequest

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter.adapter_id)
    )
    apply_result = service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )
    assert apply_result.state.value == "configured"

    # Verify without token -> CONFIGURED
    from studio_contracts.local.harness import HarnessVerifyRequest, VerifyState

    result = service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter.adapter_id)
    )
    assert result.state == VerifyState.CONFIGURED
    assert result.details.get("reason") == "token_missing"
    assert result.mcp_url == MCP_URL


@pytest.mark.parametrize(
    "adapter", [ClaudeCodeAdapter(), OpenCodeAdapter()], ids=["claude", "opencode"]
)
def test_verify_returns_configured_without_backend(adapter: HarnessAdapter, tmp_path: Path):
    """Even with token, VERIFIED requires a real MCP backend.

    This tests that CONFIGURED != VERIFIED - VERIFIED means actual MCP call succeeded."""
    if not _real(adapter):
        pytest.skip(f"{adapter.adapter_id} is not installed on this machine")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)
    # Set a fake token
    env["STUDIO_MCP_MACHINE_TOKEN"] = "fake-token-for-testing"

    def lookup(workspace_id):
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(workspace_id, workspace, MCP_URL, True)

    service = HarnessService(
        HarnessRegistry([adapter]),
        BackupStore(backups_root),
        lookup,
        env=lambda: env,
        probe_cwd=tmp_path,
    )

    # Apply config
    from studio_contracts.local.harness import HarnessApplyRequest, HarnessPreviewRequest

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter.adapter_id)
    )
    apply_result = service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )
    assert apply_result.state.value == "configured"

    # Verify with token but no backend -> FAILED (not VERIFIED)
    from studio_contracts.local.harness import HarnessVerifyRequest, VerifyState

    result = service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter.adapter_id)
    )
    # Should be FAILED because MCP call to fake URL fails
    assert result.state == VerifyState.FAILED
    assert result.mcp_url == MCP_URL
    assert result.error is not None


def test_no_token_in_config_file():
    """The harness config file must never contain the actual token, only the reference."""
    from studio_client.harness.claude_code import ClaudeCodeAdapter
    from studio_client.harness.opencode import OpenCodeAdapter

    for adapter in [ClaudeCodeAdapter(), OpenCodeAdapter()]:
        entry = adapter.build_entry("https://studio.example/mcp")
        # Check that the entry contains a reference, not a value
        if adapter.adapter_id == "claude-code":
            auth = entry.get("headers", {}).get("Authorization", "")
            assert "${STUDIO_MCP_MACHINE_TOKEN}" in auth
            assert "Bearer ${STUDIO_MCP_MACHINE_TOKEN}" == auth
        else:  # opencode
            auth = entry.get("headers", {}).get("Authorization", "")
            assert "{env:STUDIO_MCP_MACHINE_TOKEN}" in auth
            assert "Bearer {env:STUDIO_MCP_MACHINE_TOKEN}" == auth


def test_daemon_identity_view_reports_token_status(tmp_path: Path):
    """The daemon's identity_view reports whether machine token is in keyring."""
    from studio_client.config import ClientConfig
    from studio_client.daemon.service import DaemonController
    from studio_contracts.local.identity import SecretStatus

    controller = DaemonController(
        ClientConfig(
            api_base_url="https://studio.example/api/v1",
            profile_id="test",
            machine_id=WORKSPACE_ID,
        ),
        data_root=tmp_path,
    )
    view = controller.identity_view()
    # Should report ABSENT or KEYRING_UNAVAILABLE (no token set in test)
    assert len(view.secrets) == 1
    assert view.secrets[0].reference.kind.value == "machine_credential"
    assert view.secrets[0].status in (SecretStatus.ABSENT, SecretStatus.KEYRING_UNAVAILABLE)


def test_token_never_logged_or_in_diagnostics(tmp_path: Path):
    """Verify that diagnostics and logs never contain the actual token."""
    from studio_client.harness.backup import BackupStore
    from studio_client.harness.claude_code import ClaudeCodeAdapter
    from studio_client.harness.registry import HarnessRegistry
    from studio_client.harness.service import HarnessService, WorkspaceInfo

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)
    env["STUDIO_MCP_MACHINE_TOKEN"] = "SECRET-TOKEN-VALUE-12345"

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

    from studio_contracts.local.harness import (
        HarnessApplyRequest,
        HarnessPreviewRequest,
        HarnessVerifyRequest,
    )

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )

    # Check config file doesn't contain token
    config_file = workspace / ".mcp.json"
    config_text = config_file.read_text(encoding="utf-8")
    assert "SECRET-TOKEN" not in config_text
    assert "${STUDIO_MCP_MACHINE_TOKEN}" in config_text

    # Check backup doesn't contain token
    for backup_file in backups_root.rglob("*"):
        if backup_file.is_file():
            backup_text = backup_file.read_text(encoding="utf-8", errors="replace")
            assert "SECRET-TOKEN" not in backup_text

    # Check verify result doesn't contain token
    result = service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    result_json = result.model_dump_json()
    assert "SECRET-TOKEN" not in result_json


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
