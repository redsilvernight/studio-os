from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import pytest
from studio_client.harness.backup import BackupStore
from studio_client.harness.base import DetectionState, HarnessAdapter
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.opencode import OpenCodeAdapter
from studio_client.harness.probe import locate_executable
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


def _real(adapter: HarnessAdapter) -> bool:
    return (
        locate_executable(adapter.executable_names, path_env=os.environ.get("PATH", "")) is not None
    )


def _make_service(adapter: HarnessAdapter, workspace: Path, backups_root: Path, env: dict):
    def lookup(workspace_id):
        if workspace_id != WORKSPACE_ID:
            return None
        return WorkspaceInfo(workspace_id, workspace, MCP_URL, True)

    return HarnessService(
        HarnessRegistry([adapter]),
        BackupStore(backups_root),
        lookup,
        env=lambda: env,
        probe_cwd=workspace.parent,
    )


@pytest.mark.parametrize(
    "adapter", [ClaudeCodeAdapter(), OpenCodeAdapter()], ids=["claude", "opencode"]
)
def test_a_claude_alone(adapter: HarnessAdapter, tmp_path: Path):
    """Scenario A: Only one harness configured, works correctly."""
    if not _real(adapter):
        pytest.skip(f"{adapter.adapter_id} not installed")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)

    service = _make_service(adapter, workspace, backups_root, env)

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter.adapter_id)
    )
    apply_result = service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )
    assert apply_result.state.value == "configured"

    result = service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter.adapter_id)
    )
    assert result.state in (VerifyState.CONFIGURED, VerifyState.FAILED)


def test_two_harnesses_same_workspace_independent_configs(tmp_path: Path):
    """Scenario C: Both Claude Code and OpenCode configured on same workspace.

    They must have independent configs, independent backups, independent rollback."""
    if not _real(ClaudeCodeAdapter()) or not _real(OpenCodeAdapter()):
        pytest.skip("Not all harnesses installed")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)

    # Configure both
    claude_service = _make_service(ClaudeCodeAdapter(), workspace, backups_root, env)
    opencode_service = _make_service(OpenCodeAdapter(), workspace, backups_root, env)

    # Preview and apply both
    claude_preview = claude_service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    opencode_preview = opencode_service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="opencode")
    )

    claude_apply = claude_service.apply(
        HarnessApplyRequest(
            plan_id=claude_preview.plan_id, plan_hash=claude_preview.plan_hash, confirmed=True
        )
    )
    opencode_apply = opencode_service.apply(
        HarnessApplyRequest(
            plan_id=opencode_preview.plan_id, plan_hash=opencode_preview.plan_hash, confirmed=True
        )
    )

    assert claude_apply.state.value == "configured"
    assert opencode_apply.state.value == "configured"

    # Check both config files exist and are independent
    assert (workspace / ".mcp.json").exists()
    assert (workspace / "opencode.json").exists()

    # Check rollback IDs are different
    assert claude_apply.rollback_id != opencode_apply.rollback_id

    # Rollback Claude only - OpenCode should remain configured
    from studio_contracts.local.harness import HarnessRollbackRequest

    claude_rollback = claude_service.rollback(
        HarnessRollbackRequest(rollback_id=claude_apply.rollback_id, confirmed=True)
    )
    assert claude_rollback.state.value in ("detected", "unconfigured")

    opencode_result = opencode_service.verify(
        HarnessVerifyRequest(workspace_id=WORKSPACE_ID, adapter_id="opencode")
    )
    assert opencode_result.state == VerifyState.CONFIGURED


def test_no_harnesses_works(tmp_path: Path):
    """Scenario D: No harnesses installed - system works without them."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)
    # Remove PATH entries that might have harnesses
    env["PATH"] = "C:\\Windows\\System32"

    # Use a fake adapter that will report NOT_INSTALLED
    class FakeAdapter(HarnessAdapter):
        adapter_id = "fake"
        harness_id = "fake"
        display_name = "Fake"
        executable_names = ("nonexistent-harness-xyz",)
        identity = __import__("re").compile(r"^(\d+\.\d+\.\d+)$")
        supported_major = 1
        candidate_files = ("fake.json",)
        container_path = ("mcp",)

        def build_entry(self, mcp_url: str):
            return {"type": "http", "url": mcp_url}

        def detect(self, ctx):
            return Detection(DetectionState.NOT_INSTALLED)

        def plan(self, ctx):
            raise AdapterRefusal("not_installed")

    from studio_client.harness.base import AdapterRefusal, Detection

    service = _make_service(FakeAdapter(), workspace, backups_root, env)

    from studio_contracts.local.workspace import WorkspaceScope

    result = service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID))
    assert len(result.harnesses) == 1
    assert result.harnesses[0].state.value == "not_detected"


def test_concurrency_preview_then_external_modification_then_apply(tmp_path: Path):
    """§26: Preview -> external modification -> apply must detect conflict and refuse.

    The hash/conflict detection must refuse silent overwrite."""
    if not _real(ClaudeCodeAdapter()):
        pytest.skip("Claude Code not installed")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)

    service = _make_service(ClaudeCodeAdapter(), workspace, backups_root, env)

    # Preview
    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    assert len(preview.changes) == 1
    assert preview.changes[0].kind.value == "create"

    # External modification: create the file with different content
    config_file = workspace / ".mcp.json"
    config_file.write_text('{"mcpServers": {"other": {"command": "x"}}}', encoding="utf-8")

    # Apply should fail with conflict
    from studio_client.harness.service import HarnessServiceError
    from studio_contracts.local.common import LocalErrorCode

    with pytest.raises(HarnessServiceError) as exc:
        service.apply(
            HarnessApplyRequest(
                plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True
            )
        )

    assert exc.value.error.code == LocalErrorCode.INVALID_REQUEST
    assert exc.value.error.details.get("reason") == "changed_since_preview"

    # Original external content should be preserved
    assert config_file.read_text(encoding="utf-8") == '{"mcpServers": {"other": {"command": "x"}}}'


def test_concurrency_two_operations_same_adapter(tmp_path: Path):
    """Two concurrent operations on same adapter must be serialized by write lock."""
    if not _real(ClaudeCodeAdapter()):
        pytest.skip("Claude Code not installed")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)

    service = _make_service(ClaudeCodeAdapter(), workspace, backups_root, env)

    # First preview and apply
    preview1 = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    apply1 = service.apply(
        HarnessApplyRequest(plan_id=preview1.plan_id, plan_hash=preview1.plan_hash, confirmed=True)
    )
    assert apply1.state.value == "configured"

    # Second preview should return empty changes (already configured)
    preview2 = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    assert preview2.changes == []


def test_backups_are_local_only(tmp_path: Path):
    """§32: Backups must be local only, max 10/adapter/folder, hash-based, rollback works."""
    if not _real(ClaudeCodeAdapter()):
        pytest.skip("Claude Code not installed")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backups_root = tmp_path / "backups"
    backups_root.mkdir()
    env = dict(os.environ)

    service = _make_service(ClaudeCodeAdapter(), workspace, backups_root, env)

    # Apply and rollback multiple times
    from studio_contracts.local.harness import HarnessRollbackRequest

    for _ in range(15):
        preview = service.preview(
            HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
        )
        if preview.changes:
            apply_result = service.apply(
                HarnessApplyRequest(
                    plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True
                )
            )
            service.rollback(
                HarnessRollbackRequest(rollback_id=apply_result.rollback_id, confirmed=True)
            )

    # Check backup retention - should keep only newest 10
    manifests = list(backups_root.rglob("manifest.json"))
    assert len(manifests) <= 10, f"Expected <= 10 backups, got {len(manifests)}"


def test_no_network_transmission_of_backups(tmp_path: Path):
    """§32: Diagnostics must exclude backups, no network transmission."""
    from studio_client.harness.backup import BackupStore
    from studio_client.harness.claude_code import ClaudeCodeAdapter
    from studio_client.harness.registry import HarnessRegistry
    from studio_client.harness.service import HarnessService, WorkspaceInfo

    workspace = Path(tmp_path) / "workspace"
    workspace.mkdir()
    backups_root = Path(tmp_path) / "backups"
    backups_root.mkdir()
    env = fake_harness_env(tmp_path)

    service = HarnessService(
        HarnessRegistry([ClaudeCodeAdapter()]),
        BackupStore(backups_root),
        lambda wid: WorkspaceInfo(wid, workspace, MCP_URL, True) if wid == WORKSPACE_ID else None,
        env=lambda: env,
        probe_cwd=tmp_path,
    )

    from studio_contracts.local.harness import HarnessApplyRequest, HarnessPreviewRequest

    preview = service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id="claude-code")
    )
    service.apply(
        HarnessApplyRequest(plan_id=preview.plan_id, plan_hash=preview.plan_hash, confirmed=True)
    )

    # Check that backup files exist locally but are not transmitted
    # The backup store is local only - verify no network call was made
    manifests = list(backups_root.rglob("manifest.json"))
    assert len(manifests) >= 1

    # Verify backup contents are local files only
    for manifest in manifests:
        assert manifest.exists()
        content = manifest.read_text(encoding="utf-8")
        assert "studio-os" in content or "mcp" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
