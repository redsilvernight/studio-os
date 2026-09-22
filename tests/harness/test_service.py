from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.harness import service as service_module
from studio_client.harness.fsafe import FsError
from studio_client.harness.service import HarnessServiceError, latest_rollback_id
from studio_contracts.local.common import LocalErrorCode
from studio_contracts.local.harness import (
    HarnessApplyRequest,
    HarnessPreviewRequest,
    HarnessRollbackRequest,
    HarnessState,
    HarnessStatusRequest,
)
from studio_contracts.local.workspace import WorkspaceScope

from tests.harness.support import WORKSPACE_ID, Rig, install_fake, make_rig

CLAUDE = "claude-code"
OPENCODE = "opencode"


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def _preview(rig: Rig, adapter: str = CLAUDE):
    return rig.service.preview(HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter))


def _apply(rig: Rig, plan):
    return rig.service.apply(
        HarnessApplyRequest(plan_id=plan.plan_id, plan_hash=plan.plan_hash, confirmed=True)
    )


def _rollback(rig: Rig, rollback_id: str):
    return rig.service.rollback(HarnessRollbackRequest(rollback_id=rollback_id, confirmed=True))


def _reason(error: HarnessServiceError) -> str | None:
    return (error.error.details or {}).get("reason")


def _backup_dirs(rig: Rig) -> list[Path]:
    if not rig.backups_root.exists():
        return []
    return sorted(path for path in rig.backups_root.glob("*/*/rb-*") if path.is_dir())


def _state(rig: Rig, adapter: str = CLAUDE) -> HarnessState:
    return rig.service.status(
        HarnessStatusRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter)
    ).state


def test_detect_lists_both_harnesses_with_state_and_version(rig: Rig) -> None:
    result = rig.service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID))
    by_id = {status.adapter_id: status for status in result.harnesses}
    assert set(by_id) == {CLAUDE, OPENCODE}
    assert by_id[CLAUDE].state is HarnessState.DETECTED
    assert by_id[CLAUDE].detected_version == "2.1.272"
    assert by_id[OPENCODE].detected_version == "1.18.31"
    assert by_id[CLAUDE].capabilities == ["mcp.config"]


def test_detect_reports_not_detected_without_error_leak(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, claude=False, opencode=False)
    result = rig.service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID))
    for status in result.harnesses:
        assert status.state is HarnessState.NOT_DETECTED
        assert status.error is not None
        assert status.error.code is LocalErrorCode.PROVIDER_NOT_INSTALLED
        assert status.capabilities == []


def test_detect_works_even_when_the_feature_is_disabled(rig: Rig) -> None:
    rig.flags["enabled"] = False
    assert rig.service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID)).harnesses


def test_unknown_workspace_and_adapter_are_refused(rig: Rig) -> None:
    with pytest.raises(HarnessServiceError) as unknown_workspace:
        rig.service.detect(WorkspaceScope(workspace_id=uuid4()))
    assert unknown_workspace.value.error.code is LocalErrorCode.WORKSPACE_CONFIG_MISSING
    with pytest.raises(HarnessServiceError) as unknown_adapter:
        _preview(rig, "nope")
    assert _reason(unknown_adapter.value) == "adapter_unknown"


def test_preview_writes_nothing_and_describes_the_change(rig: Rig) -> None:
    plan = _preview(rig)
    assert list(rig.root.iterdir()) == []
    assert _backup_dirs(rig) == []
    assert plan.requires_confirmation is True
    [change] = plan.changes
    assert change.target == ".mcp.json"
    assert change.kind.value == "create"
    assert change.before_hash is None
    assert change.after_hash
    assert "studio-os" in change.summary.lower() or "studi" in change.summary.lower()


def test_preview_is_refused_when_the_feature_is_disabled(rig: Rig) -> None:
    rig.flags["enabled"] = False
    with pytest.raises(HarnessServiceError) as refused:
        _preview(rig)
    assert refused.value.error.code is LocalErrorCode.FEATURE_DISABLED


def test_apply_writes_backs_up_and_reports_configured(rig: Rig) -> None:
    (rig.root / ".mcp.json").write_text('{"mcpServers": {"other": {"command": "x"}}}\n')
    original = (rig.root / ".mcp.json").read_bytes()
    plan = _preview(rig)
    result = _apply(rig, plan)
    assert result.state is HarnessState.CONFIGURED
    assert result.applied == [change.change_id for change in plan.changes]
    assert result.rollback_id is not None
    assert len(_backup_dirs(rig)) == 1
    data = json.loads((rig.root / ".mcp.json").read_text())
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert "studio-os" in data["mcpServers"]
    backup_bytes = [path.read_bytes() for path in _backup_dirs(rig)[0].glob("*.bak")]
    assert backup_bytes == [original]


def test_apply_needs_a_previewed_plan(rig: Rig) -> None:
    with pytest.raises(HarnessServiceError) as refused:
        rig.service.apply(HarnessApplyRequest(plan_id="plan-x", plan_hash="0" * 64, confirmed=True))
    assert refused.value.error.code is LocalErrorCode.PLAN_EXPIRED
    assert not (rig.root / ".mcp.json").exists()


def test_apply_refuses_a_hash_that_does_not_match_the_preview(rig: Rig) -> None:
    plan = _preview(rig)
    with pytest.raises(HarnessServiceError) as refused:
        rig.service.apply(
            HarnessApplyRequest(plan_id=plan.plan_id, plan_hash="f" * 64, confirmed=True)
        )
    assert _reason(refused.value) == "plan_hash_mismatch"
    assert not (rig.root / ".mcp.json").exists()


def test_a_plan_is_one_shot(rig: Rig) -> None:
    plan = _preview(rig)
    _apply(rig, plan)
    with pytest.raises(HarnessServiceError) as refused:
        _apply(rig, plan)
    assert refused.value.error.code is LocalErrorCode.PLAN_EXPIRED


def test_an_expired_plan_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path)
    plan = _preview(rig)
    later = plan.expires_at.replace(year=plan.expires_at.year + 1)
    monkeypatch.setattr(service_module, "_now", lambda: later)
    monkeypatch.setattr(rig.service, "_clock", lambda: later)
    with pytest.raises(HarnessServiceError) as refused:
        _apply(rig, plan)
    assert refused.value.error.code is LocalErrorCode.PLAN_EXPIRED
    assert not (rig.root / ".mcp.json").exists()


def test_apply_refuses_when_the_file_changed_after_the_preview(rig: Rig) -> None:
    (rig.root / ".mcp.json").write_text("{}\n")
    plan = _preview(rig)
    (rig.root / ".mcp.json").write_text('{"theme": "light"}\n')
    with pytest.raises(HarnessServiceError) as refused:
        _apply(rig, plan)
    assert _reason(refused.value) == "changed_since_preview"
    assert (rig.root / ".mcp.json").read_text() == '{"theme": "light"}\n'
    assert _backup_dirs(rig) == []


def test_second_configure_is_a_no_op_without_extra_backups(rig: Rig) -> None:
    first = _apply(rig, _preview(rig))
    assert first.applied
    before = (rig.root / ".mcp.json").read_bytes()
    second_plan = _preview(rig)
    assert second_plan.changes == []
    second = _apply(rig, second_plan)
    assert second.applied == []
    assert second.rollback_id is None
    assert second.state is HarnessState.CONFIGURED
    assert (rig.root / ".mcp.json").read_bytes() == before
    assert len(_backup_dirs(rig)) == 1


def test_rollback_restores_the_original_bytes(rig: Rig) -> None:
    original = b'{\r\n\t"theme": "dark",\r\n\t"mcpServers": {}\r\n}\r\n'
    (rig.root / ".mcp.json").write_bytes(original)
    applied = _apply(rig, _preview(rig))
    assert (rig.root / ".mcp.json").read_bytes() != original
    result = _rollback(rig, applied.rollback_id)
    assert (rig.root / ".mcp.json").read_bytes() == original
    assert result.restored == applied.applied
    assert result.state is HarnessState.DETECTED


def test_rollback_of_a_created_file_removes_it(rig: Rig) -> None:
    applied = _apply(rig, _preview(rig, OPENCODE))
    assert (rig.root / "opencode.json").exists()
    _rollback(rig, applied.rollback_id)
    assert not (rig.root / "opencode.json").exists()


def test_rollback_by_latest_alias_and_after_a_restart(rig: Rig) -> None:
    _apply(rig, _preview(rig))
    alias = latest_rollback_id(WORKSPACE_ID, CLAUDE)
    result = _rollback(make_rig_sharing(rig), alias)
    assert result.restored
    assert not (rig.root / ".mcp.json").exists()


def make_rig_sharing(rig: Rig) -> Rig:
    from studio_client.harness.backup import BackupStore
    from studio_client.harness.registry import HarnessRegistry
    from studio_client.harness.service import HarnessService, WorkspaceInfo

    from tests.harness.support import MCP_URL

    service = HarnessService(
        HarnessRegistry(),
        BackupStore(rig.backups_root),
        lambda workspace_id: WorkspaceInfo(workspace_id, rig.root, MCP_URL, True),
        env=lambda: rig.env,
        probe_cwd=rig.root.parent,
    )
    return Rig(rig.root, rig.bin_dir, rig.backups_root, rig.env, service, rig.flags)


def test_rollback_conflict_when_the_user_edited_after_apply(rig: Rig) -> None:
    applied = _apply(rig, _preview(rig))
    edited = (rig.root / ".mcp.json").read_text() + "\n"
    edited = edited.replace('"mcpServers"', '"mcpServers"')  # keep valid JSON
    data = json.loads(edited)
    data["theme"] = "user-added-after"
    (rig.root / ".mcp.json").write_text(json.dumps(data))
    snapshot = (rig.root / ".mcp.json").read_bytes()
    with pytest.raises(HarnessServiceError) as refused:
        _rollback(rig, applied.rollback_id)
    assert _reason(refused.value) == "rollback_conflict"
    assert refused.value.error.code is LocalErrorCode.INVALID_REQUEST
    assert (rig.root / ".mcp.json").read_bytes() == snapshot, "nothing restored blindly"


def test_a_rollback_can_only_run_once(rig: Rig) -> None:
    applied = _apply(rig, _preview(rig))
    _rollback(rig, applied.rollback_id)
    with pytest.raises(HarnessServiceError) as refused:
        _rollback(rig, applied.rollback_id)
    assert _reason(refused.value) == "already_rolled_back"


def test_rollback_of_an_unknown_id_is_refused(rig: Rig) -> None:
    for rollback_id in ("rb-" + "0" * 32, "latest:" + str(uuid4()) + ":" + CLAUDE, "nope"):
        with pytest.raises(HarnessServiceError) as refused:
            _rollback(rig, rollback_id)
        assert _reason(refused.value) == "rollback_unknown"


def test_backup_impossible_means_nothing_is_written(rig: Rig, tmp_path: Path) -> None:
    (rig.root / ".mcp.json").write_text("{}\n")
    plan = _preview(rig)
    blocker = rig.backups_root
    blocker.parent.mkdir(exist_ok=True)
    blocker.write_text("i am a file, not a directory")
    with pytest.raises(HarnessServiceError):
        _apply(rig, plan)
    assert (rig.root / ".mcp.json").read_text() == "{}\n"


def test_an_interrupted_write_leaves_the_original_and_no_temp_file(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = b'{"theme": "dark"}\n'
    (rig.root / ".mcp.json").write_bytes(original)
    plan = _preview(rig)

    def boom(path: Path, data: bytes) -> None:
        raise FsError("io_error", "disk full")

    monkeypatch.setattr(service_module, "atomic_write", boom)
    with pytest.raises(HarnessServiceError):
        _apply(rig, plan)
    assert (rig.root / ".mcp.json").read_bytes() == original
    assert [path.name for path in rig.root.iterdir()] == [".mcp.json"]


def test_a_write_that_does_not_verify_is_restored(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = b'{"theme": "dark"}\n'
    (rig.root / ".mcp.json").write_bytes(original)
    plan = _preview(rig)
    real_write = service_module.atomic_write
    calls = {"count": 0}

    def corrupting(path: Path, data: bytes) -> None:
        calls["count"] += 1
        real_write(path, data if calls["count"] > 1 else b'{"corrupted": true}')

    monkeypatch.setattr(service_module, "atomic_write", corrupting)
    with pytest.raises(HarnessServiceError):
        _apply(rig, plan)
    assert (rig.root / ".mcp.json").read_bytes() == original


def test_a_failed_restore_is_reported_and_stays_restorable(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = b'{"theme": "dark"}' + chr(10).encode()
    (rig.root / ".mcp.json").write_bytes(original)
    plan = _preview(rig)
    real_write = service_module.atomic_write
    calls = {"count": 0}

    def failing_restore(path: Path, data: bytes) -> None:
        calls["count"] += 1
        if calls["count"] > 1:
            raise FsError("io_error", "cannot restore")
        real_write(path, data)

    monkeypatch.setattr(service_module, "atomic_write", failing_restore)
    monkeypatch.setattr(
        service_module, "_map_state", lambda detection: (HarnessState.DETECTED, None)
    )
    with pytest.raises(HarnessServiceError) as failure:
        _apply(rig, plan)
    assert failure.value.error.details == {"reason": "restore_failed"}
    monkeypatch.undo()
    assert (rig.root / ".mcp.json").read_bytes() != original
    rig.service.rollback(
        HarnessRollbackRequest(rollback_id=latest_rollback_id(WORKSPACE_ID, CLAUDE), confirmed=True)
    )
    assert (rig.root / ".mcp.json").read_bytes() == original


@pytest.mark.parametrize("adapter,name", [(CLAUDE, ".mcp.json"), (OPENCODE, "opencode.json")])
def test_an_out_of_range_number_fails_closed_for_every_harness(
    rig: Rig, adapter: str, name: str
) -> None:
    content = ('{"n": ' + "9" * 5000 + "}").encode()
    (rig.root / name).write_bytes(content)
    statuses = rig.service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID)).harnesses
    assert {status.adapter_id for status in statuses} == {CLAUDE, OPENCODE}
    with pytest.raises(HarnessServiceError):
        _preview(rig, adapter)
    assert (rig.root / name).read_bytes() == content


def test_read_only_config_is_refused_at_preview(rig: Rig) -> None:
    import os
    import stat

    path = rig.root / ".mcp.json"
    path.write_text("{}\n")
    os.chmod(path, stat.S_IREAD)
    try:
        with pytest.raises(HarnessServiceError) as refused:
            _preview(rig)
        assert refused.value.error.code is LocalErrorCode.PERMISSION_DENIED
    finally:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def test_incompatible_harness_is_never_overwritten(rig: Rig) -> None:
    install_fake(rig.bin_dir, "claude", "9.0.0 (Claude Code)")
    (rig.root / ".mcp.json").write_text("{}\n")
    with pytest.raises(HarnessServiceError) as refused:
        _preview(rig)
    assert refused.value.error.code is LocalErrorCode.PROVIDER_INCOMPATIBLE
    assert _state(rig) is HarnessState.INCOMPATIBLE
    assert (rig.root / ".mcp.json").read_text() == "{}\n"


def test_retention_keeps_only_the_newest_backups(rig: Rig) -> None:
    for round_number in range(13):
        (rig.root / ".mcp.json").write_text(json.dumps({"n": round_number}))
        _apply(rig, _preview(rig))
    assert len(_backup_dirs(rig)) == 10


def test_errors_never_carry_paths_or_secrets(rig: Rig) -> None:
    rig.env["STUDIO_MCP_MACHINE_TOKEN"] = "sk-SECRET-VALUE-123456"
    (rig.root / ".mcp.json").write_text('{"broken": ')
    with pytest.raises(HarnessServiceError) as refused:
        _preview(rig)
    text = refused.value.error.model_dump_json()
    assert str(rig.root) not in text
    assert "SECRET-VALUE" not in text
    statuses = rig.service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID))
    assert str(rig.root) not in statuses.model_dump_json()
