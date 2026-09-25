from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from studio_client.harness import service as service_module
from studio_client.harness.fsafe import FsError
from studio_client.harness.redaction import fingerprint
from studio_client.harness.service import HarnessServiceError, latest_rollback_id
from studio_contracts.local.common import LocalErrorCode
from studio_contracts.local.harness import (
    ChangeScope,
    HarnessApplyRequest,
    HarnessPreviewRequest,
    HarnessRollbackRequest,
    HarnessState,
    HarnessStatusRequest,
)
from studio_contracts.local.workspace import WorkspaceScope

from tests.harness.support import (
    MCP_URL,
    OPENCODE_CONFIG,
    ORIGIN,
    WORKSPACE_ID,
    Rig,
    install_fake,
    make_rig,
    restarted,
)

CLAUDE = "claude-code"
OPENCODE = "opencode"


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def _preview(rig: Rig, adapter: str = CLAUDE, *, renew: bool = False):
    return rig.service.preview(
        HarnessPreviewRequest(workspace_id=WORKSPACE_ID, adapter_id=adapter, renew=renew)
    )


def _apply(rig: Rig, plan):
    return rig.service.apply(
        HarnessApplyRequest(plan_id=plan.plan_id, plan_hash=plan.plan_hash, confirmed=True)
    )


def _configure(rig: Rig, adapter: str = CLAUDE, *, renew: bool = False):
    return _apply(rig, _preview(rig, adapter, renew=renew))


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


def _token(rig: Rig, adapter: str = CLAUDE) -> str:
    entry = rig.user_entry(adapter)
    assert entry is not None
    return str(entry["headers"]["Authorization"]).removeprefix("Bearer ")


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


@pytest.mark.parametrize("adapter,target", [(CLAUDE, ".claude.json"), (OPENCODE, OPENCODE_CONFIG)])
def test_preview_writes_nothing_and_describes_the_user_entry(
    rig: Rig, adapter: str, target: str
) -> None:
    plan = _preview(rig, adapter)
    assert list(rig.root.iterdir()) == []
    assert list(rig.home.iterdir()) == []
    assert _backup_dirs(rig) == []
    assert rig.provisioner.created == []
    assert plan.requires_confirmation is True
    [change] = plan.changes
    assert change.scope is ChangeScope.USER
    assert change.target == target
    assert change.kind.value == "create"
    assert change.before_hash is None
    assert change.after_hash


def test_preview_is_refused_when_the_feature_is_disabled(rig: Rig) -> None:
    rig.flags["enabled"] = False
    with pytest.raises(HarnessServiceError) as refused:
        _preview(rig)
    assert refused.value.error.code is LocalErrorCode.FEATURE_DISABLED


@pytest.mark.parametrize("adapter", [CLAUDE, OPENCODE])
def test_apply_provisions_a_dedicated_machine_and_writes_its_credential(
    rig: Rig, adapter: str
) -> None:
    result = _configure(rig, adapter)
    assert result.state is HarnessState.CONFIGURED
    assert result.rollback_id is not None
    [(origin, name, machine_id)] = rig.provisioner.created
    assert origin == ORIGIN
    assert name.startswith("TEST-HOST · ")
    token = _token(rig, adapter)
    assert token == rig.provisioner.tokens[machine_id]
    assert rig.user_entry(adapter)["url"] == MCP_URL
    record = rig.credentials.get(adapter, ORIGIN)
    assert record is not None and record.machine_id == machine_id
    assert record.credential_sha256 == fingerprint(token)
    assert rig.credentials.pending() == []
    assert _state(rig, adapter) is HarnessState.CONFIGURED


def test_claude_is_configured_only_through_its_cli(rig: Rig) -> None:
    rig.claude_config.write_text(json.dumps({"theme": "dark", "numStartups": 3}), "utf-8")
    _configure(rig)
    assert [call[:4] for call in rig.cli.calls] == [("mcp", "add-json", "--scope", "user")]
    data = json.loads(rig.claude_config.read_text("utf-8"))
    assert data["theme"] == "dark" and data["numStartups"] == 3


def test_opencode_edit_preserves_comments_and_settings(rig: Rig) -> None:
    rig.opencode_config.parent.mkdir(parents=True)
    original = (
        '{\n  // keep me\n  "theme": "tokyonight",\n'
        '  "mcp": {\n    "other": {"type": "local"},\n  },\n}\n'
    )
    rig.opencode_config.write_text(original, "utf-8")
    _configure(rig, OPENCODE)
    text = rig.opencode_config.read_text("utf-8")
    assert "// keep me" in text
    assert '"theme": "tokyonight"' in text
    assert '"other"' in text


def test_apply_needs_a_previewed_plan(rig: Rig) -> None:
    with pytest.raises(HarnessServiceError) as refused:
        rig.service.apply(HarnessApplyRequest(plan_id="plan-x", plan_hash="0" * 64, confirmed=True))
    assert refused.value.error.code is LocalErrorCode.PLAN_EXPIRED
    assert rig.provisioner.created == []


def test_apply_refuses_a_hash_that_does_not_match_the_preview(rig: Rig) -> None:
    plan = _preview(rig)
    with pytest.raises(HarnessServiceError) as refused:
        rig.service.apply(
            HarnessApplyRequest(plan_id=plan.plan_id, plan_hash="f" * 64, confirmed=True)
        )
    assert _reason(refused.value) == "plan_hash_mismatch"
    assert rig.provisioner.created == []


def test_a_plan_is_one_shot(rig: Rig) -> None:
    plan = _preview(rig)
    _apply(rig, plan)
    with pytest.raises(HarnessServiceError) as refused:
        _apply(rig, plan)
    assert refused.value.error.code is LocalErrorCode.PLAN_EXPIRED
    assert len(rig.provisioner.created) == 1


def test_an_expired_plan_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(tmp_path)
    plan = _preview(rig)
    later = plan.expires_at.replace(year=plan.expires_at.year + 1)
    monkeypatch.setattr(rig.service, "_clock", lambda: later)
    with pytest.raises(HarnessServiceError) as refused:
        _apply(rig, plan)
    assert refused.value.error.code is LocalErrorCode.PLAN_EXPIRED
    assert rig.provisioner.created == []


def test_apply_refuses_when_the_user_entry_changed_after_the_preview(rig: Rig) -> None:
    rig.opencode_config.parent.mkdir(parents=True)
    rig.opencode_config.write_text('{"mcp": {}}\n', "utf-8")
    plan = _preview(rig, OPENCODE)
    rig.opencode_config.write_text(
        '{"mcp": {"studio-os": {"type": "remote", "url": "https://other/mcp"}}}\n', "utf-8"
    )
    with pytest.raises(HarnessServiceError) as refused:
        _apply(rig, plan)
    assert _reason(refused.value) == "changed_since_preview"
    assert rig.provisioner.created == []
    assert _backup_dirs(rig) == []


def test_second_configure_is_a_no_op(rig: Rig) -> None:
    first = _configure(rig)
    token = _token(rig)
    plan = _preview(rig)
    assert plan.changes == []
    second = _apply(rig, plan)
    assert second.applied == [] and second.rollback_id is None
    assert second.state is HarnessState.CONFIGURED
    assert _token(rig) == token
    assert len(rig.provisioner.created) == 1
    assert len(_backup_dirs(rig)) == 1
    assert first.rollback_id


def test_renew_replaces_the_credential_and_revokes_the_old_machine(rig: Rig) -> None:
    _configure(rig)
    [(_, _, old_machine)] = rig.provisioner.created
    old_token = _token(rig)
    plan = _preview(rig, renew=True)
    [change] = plan.changes
    assert change.kind.value == "modify"
    _apply(rig, plan)
    assert _token(rig) != old_token
    assert rig.provisioner.revoked == [old_machine]
    assert len(rig.provisioner.active) == 1
    assert rig.credentials.get(CLAUDE, ORIGIN).machine_id == rig.provisioner.active[0]


def test_a_hand_written_credential_is_replaced_by_a_dedicated_one(rig: Rig) -> None:
    rig.claude_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "studio-os": {
                        "type": "http",
                        "url": MCP_URL,
                        "headers": {"Authorization": "Bearer desktop-credential"},
                    }
                }
            }
        ),
        "utf-8",
    )
    status = rig.service.status(HarnessStatusRequest(workspace_id=WORKSPACE_ID, adapter_id=CLAUDE))
    assert status.state is HarnessState.DETECTED
    plan = _preview(rig)
    [change] = plan.changes
    assert "not kept for rollback" in change.summary
    assert _apply(rig, plan).state is HarnessState.CONFIGURED
    assert _token(rig) != "desktop-credential"
    assert rig.provisioner.revoked == []  # never ours to revoke
    for backup in _backup_dirs(rig):
        for path in backup.iterdir():
            assert b"desktop-credential" not in path.read_bytes()


def test_a_project_entry_is_migrated_to_the_user_configuration(rig: Rig) -> None:
    (rig.root / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "studio-os": {
                        "type": "http",
                        "url": MCP_URL,
                        "headers": {"Authorization": "Bearer ${STUDIO_MCP_MACHINE_TOKEN}"},
                    },
                    "other": {"command": "x"},
                }
            }
        ),
        "utf-8",
    )
    plan = _preview(rig)
    assert [change.scope for change in plan.changes] == [ChangeScope.USER, ChangeScope.WORKSPACE]
    _apply(rig, plan)
    data = json.loads((rig.root / ".mcp.json").read_text("utf-8"))
    assert "studio-os" not in data["mcpServers"]
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert _state(rig) is HarnessState.CONFIGURED


def test_rollback_removes_the_entry_and_revokes_the_machine(rig: Rig) -> None:
    applied = _configure(rig, OPENCODE)
    [(_, _, machine_id)] = rig.provisioner.created
    result = _rollback(rig, applied.rollback_id)
    assert result.restored == applied.applied
    assert rig.user_entry(OPENCODE) is None
    assert rig.provisioner.revoked == [machine_id]
    assert rig.credentials.get(OPENCODE, ORIGIN) is None
    assert result.state is HarnessState.DETECTED


def test_rollback_restores_a_previous_entry_without_secret(rig: Rig) -> None:
    rig.opencode_config.parent.mkdir(parents=True)
    rig.opencode_config.write_text(
        json.dumps(
            {
                "mcp": {
                    "studio-os": {
                        "type": "remote",
                        "url": MCP_URL,
                        "headers": {"Authorization": "Bearer {env:STUDIO_TOKEN}"},
                    }
                }
            }
        ),
        "utf-8",
    )
    before = rig.user_entry(OPENCODE)
    applied = _configure(rig, OPENCODE)
    assert rig.user_entry(OPENCODE) != before
    _rollback(rig, applied.rollback_id)
    assert rig.user_entry(OPENCODE) == before


def test_rollback_of_a_migration_restores_the_project_file(rig: Rig) -> None:
    original = b'{\r\n\t"mcpServers": {"studio-os": {"type": "http", "url": "x"}}\r\n}\r\n'
    (rig.root / ".mcp.json").write_bytes(original)
    applied = _configure(rig)
    assert (rig.root / ".mcp.json").read_bytes() != original
    _rollback(rig, applied.rollback_id)
    assert (rig.root / ".mcp.json").read_bytes() == original
    assert rig.user_entry(CLAUDE) is None


def test_rollback_by_latest_alias_and_after_a_restart(rig: Rig) -> None:
    _configure(rig)
    result = _rollback(restarted(rig), latest_rollback_id(WORKSPACE_ID, CLAUDE))
    assert result.restored
    assert rig.user_entry(CLAUDE) is None
    assert len(rig.provisioner.revoked) == 1


def test_rollback_conflict_when_the_credential_changed_after_apply(rig: Rig) -> None:
    applied = _configure(rig, OPENCODE)
    data = json.loads(rig.opencode_config.read_text("utf-8"))
    data["mcp"]["studio-os"]["headers"]["Authorization"] = "Bearer someone-else"
    rig.opencode_config.write_text(json.dumps(data), "utf-8")
    snapshot = rig.opencode_config.read_bytes()
    with pytest.raises(HarnessServiceError) as refused:
        _rollback(rig, applied.rollback_id)
    assert _reason(refused.value) == "rollback_conflict"
    assert rig.opencode_config.read_bytes() == snapshot, "nothing restored blindly"
    assert rig.provisioner.revoked == []


def test_a_rollback_can_only_run_once(rig: Rig) -> None:
    applied = _configure(rig)
    _rollback(rig, applied.rollback_id)
    with pytest.raises(HarnessServiceError) as refused:
        _rollback(rig, applied.rollback_id)
    assert _reason(refused.value) == "already_rolled_back"


def test_rollback_of_an_unknown_id_is_refused(rig: Rig) -> None:
    for rollback_id in ("rb-" + "0" * 32, "latest:" + str(uuid4()) + ":" + CLAUDE, "nope"):
        with pytest.raises(HarnessServiceError) as refused:
            _rollback(rig, rollback_id)
        assert _reason(refused.value) == "rollback_unknown"


def test_backup_impossible_means_nothing_is_provisioned(rig: Rig) -> None:
    plan = _preview(rig)
    rig.backups_root.write_text("i am a file, not a directory")
    with pytest.raises(HarnessServiceError):
        _apply(rig, plan)
    assert rig.provisioner.created == []
    assert rig.user_entry(CLAUDE) is None


@pytest.mark.parametrize(
    "reason,code",
    [
        ("credential_forbidden", LocalErrorCode.PERMISSION_DENIED),
        ("desktop_unauthenticated", LocalErrorCode.SECRET_REVOKED),
        ("credential_unreachable", LocalErrorCode.INTERNAL_ERROR),
    ],
)
def test_a_provisioning_failure_writes_nothing(rig: Rig, reason: str, code: LocalErrorCode) -> None:
    rig.provisioner.fail_create = reason
    with pytest.raises(HarnessServiceError) as refused:
        _configure(rig)
    assert refused.value.error.code is code
    assert _reason(refused.value) == reason
    assert rig.user_entry(CLAUDE) is None


def test_a_failed_cli_revokes_the_new_machine(rig: Rig) -> None:
    rig.cli.fail = True
    with pytest.raises(HarnessServiceError) as refused:
        _configure(rig)
    assert _reason(refused.value) == "cli_failed"
    [(_, _, machine_id)] = rig.provisioner.created
    assert rig.provisioner.revoked == [machine_id]
    assert rig.credentials.get(CLAUDE, ORIGIN) is None
    assert rig.credentials.pending() == []


def test_an_unreachable_revocation_is_retried_later(rig: Rig) -> None:
    rig.cli.fail = True
    rig.provisioner.fail_revoke = "credential_unreachable"
    with pytest.raises(HarnessServiceError):
        _configure(rig)
    [(_, _, machine_id)] = rig.provisioner.created
    assert [item.machine_id for item in rig.credentials.pending()] == [machine_id]
    rig.provisioner.fail_revoke = None
    rig.cli.fail = False
    _preview(rig)
    assert rig.provisioner.revoked == [machine_id]
    assert rig.credentials.pending() == []


def test_a_workspace_write_that_fails_restores_and_revokes(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = b'{"mcpServers": {"studio-os": {"type": "http", "url": "x"}}}\n'
    (rig.root / ".mcp.json").write_bytes(original)
    plan = _preview(rig)

    def boom(path: Path, data: bytes) -> None:
        raise FsError("io_error", "disk full")

    monkeypatch.setattr(service_module, "atomic_write", boom)
    with pytest.raises(HarnessServiceError):
        _apply(rig, plan)
    assert (rig.root / ".mcp.json").read_bytes() == original
    assert [path.name for path in rig.root.iterdir()] == [".mcp.json"]
    assert rig.user_entry(CLAUDE) is None
    assert rig.provisioner.active == []


def test_a_failed_restore_is_reported_and_stays_restorable(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = b'{"mcpServers": {"studio-os": {"type": "http", "url": "x"}}}\n'
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
    _rollback(rig, latest_rollback_id(WORKSPACE_ID, CLAUDE))
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


def test_read_only_user_config_is_refused_at_apply_and_revoked(rig: Rig) -> None:
    import os
    import stat

    rig.opencode_config.parent.mkdir(parents=True)
    rig.opencode_config.write_text("{}\n", "utf-8")
    os.chmod(rig.opencode_config, stat.S_IREAD)
    try:
        with pytest.raises(HarnessServiceError) as refused:
            _configure(rig, OPENCODE)
        assert refused.value.error.code is LocalErrorCode.PERMISSION_DENIED
        assert rig.provisioner.active == []
    finally:
        os.chmod(rig.opencode_config, stat.S_IWRITE | stat.S_IREAD)


def test_incompatible_harness_is_never_overwritten(rig: Rig) -> None:
    install_fake(rig.bin_dir, "claude", "9.0.0 (Claude Code)")
    with pytest.raises(HarnessServiceError) as refused:
        _preview(rig)
    assert refused.value.error.code is LocalErrorCode.PROVIDER_INCOMPATIBLE
    assert _state(rig) is HarnessState.INCOMPATIBLE


def test_retention_keeps_only_the_newest_backups(rig: Rig) -> None:
    for _ in range(13):
        _configure(rig, renew=True)
    assert len(_backup_dirs(rig)) == 10
    assert len(rig.provisioner.active) == 1


def test_errors_never_carry_paths_or_secrets(rig: Rig) -> None:
    (rig.root / ".mcp.json").write_text('{"broken": ')
    with pytest.raises(HarnessServiceError) as refused:
        _preview(rig)
    text = refused.value.error.model_dump_json()
    assert str(rig.root) not in text
    statuses = rig.service.detect(WorkspaceScope(workspace_id=WORKSPACE_ID))
    assert str(rig.root) not in statuses.model_dump_json()
