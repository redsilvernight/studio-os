from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client.harness.service import HarnessServiceError
from studio_contracts.local.common import LocalErrorCode
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessPreviewRequest,
    HarnessRollbackRequest,
    HarnessState,
    HarnessStatusRequest,
)
from studio_contracts.local.workspace import WorkspaceScope

from tests.harness.support import WORKSPACE_ID, Rig, make_rig


def _preview(rig: Rig, adapter_id: str):
    return rig.service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter_id)
    )


def _apply(rig: Rig, plan):
    return rig.service.apply(
        HarnessApplyRequest(plan_id=plan.plan_id, plan_hash=plan.plan_hash, confirmed=True)
    )


def _state(rig: Rig, adapter_id: str) -> HarnessState:
    return rig.service.status(
        HarnessStatusRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter_id)
    ).state


@pytest.mark.parametrize("adapter_id", ["claude-code", "opencode"], ids=["claude", "opencode"])
def test_a_claude_alone(adapter_id: str, tmp_path: Path) -> None:
    """Scenario A: one harness configured, the other untouched."""
    rig = make_rig(tmp_path)
    assert _apply(rig, _preview(rig, adapter_id)).state is HarnessState.CONFIGURED
    other = "opencode" if adapter_id == "claude-code" else "claude-code"
    assert _state(rig, other) is HarnessState.DETECTED
    assert rig.user_entry(other) is None


def test_two_harnesses_same_workspace_independent_configs(tmp_path: Path) -> None:
    """Scenario C: independent machines, backups and rollbacks."""
    rig = make_rig(tmp_path)
    claude = _apply(rig, _preview(rig, "claude-code"))
    opencode = _apply(rig, _preview(rig, "opencode"))
    assert claude.rollback_id != opencode.rollback_id
    claude_machine, opencode_machine = rig.provisioner.active
    rig.service.rollback(HarnessRollbackRequest(rollback_id=claude.rollback_id, confirmed=True))
    assert rig.provisioner.revoked == [claude_machine]
    assert rig.provisioner.active == [opencode_machine]
    assert _state(rig, "claude-code") is HarnessState.DETECTED
    assert _state(rig, "opencode") is HarnessState.CONFIGURED


def test_no_harnesses_works(tmp_path: Path) -> None:
    """Scenario D: nothing installed, nothing provisioned, detect still answers."""
    rig = make_rig(tmp_path, claude=False, opencode=False)
    result = rig.service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID))
    assert {status.state.value for status in result.harnesses} == {"not_detected"}
    with pytest.raises(HarnessServiceError):
        _preview(rig, "claude-code")
    assert rig.provisioner.created == []


def test_concurrency_preview_then_external_modification_then_apply(tmp_path: Path) -> None:
    """§26: a user config changed after the preview is never silently overwritten."""
    rig = make_rig(tmp_path)
    plan = _preview(rig, "claude-code")
    external = '{"mcpServers": {"studio-os": {"type": "http", "url": "https://other/mcp"}}}'
    rig.claude_config.write_text(external, encoding="utf-8")
    with pytest.raises(HarnessServiceError) as refused:
        _apply(rig, plan)
    assert refused.value.error.code is LocalErrorCode.INVALID_REQUEST
    assert (refused.value.error.details or {}).get("reason") == "changed_since_preview"
    assert rig.claude_config.read_text(encoding="utf-8") == external
    assert rig.provisioner.created == []


def test_concurrency_two_previews_only_one_apply_wins(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    first = _preview(rig, "claude-code")
    second = _preview(rig, "claude-code")
    _apply(rig, first)
    with pytest.raises(HarnessServiceError) as refused:
        _apply(rig, second)
    assert (refused.value.error.details or {}).get("reason") == "changed_since_preview"
    assert len(rig.provisioner.active) == 1
    assert _preview(rig, "claude-code").changes == []


def test_backups_are_local_only_and_bounded(tmp_path: Path) -> None:
    """§32: at most 10 backups per adapter and folder, rollback still works."""
    rig = make_rig(tmp_path)
    for _ in range(15):
        applied = _apply(rig, _preview(rig, "claude-code"))
        rig.service.rollback(
            HarnessRollbackRequest(rollback_id=applied.rollback_id, confirmed=True)
        )
    assert len(list(rig.backups_root.rglob("manifest.json"))) <= 10
    assert rig.provisioner.active == []


def test_no_network_transmission_of_backups(tmp_path: Path) -> None:
    """§32: backups stay local and never hold the credential."""
    rig = make_rig(tmp_path)
    _apply(rig, _preview(rig, "opencode"))
    [machine_id] = rig.provisioner.active
    token = rig.provisioner.tokens[machine_id]
    manifests = list(rig.backups_root.rglob("manifest.json"))
    assert manifests
    for path in rig.backups_root.rglob("*"):
        if path.is_file():
            assert token not in path.read_text(encoding="utf-8", errors="replace")
    json.loads(manifests[0].read_text(encoding="utf-8"))
