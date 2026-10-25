from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from studio_client import cli
from studio_client.bootstrap import BootstrapError
from studio_client.daemon.skills_bridge import apply_definition_sync, plan_definition_sync
from studio_client.projection_backups import list_projection_backups, restore_projection_backup
from studio_client.skill_sync import SkillSyncConflictError, apply_skill_sync, plan_skill_sync

from tests.client.test_skill_sync import _projection


def test_managed_update_can_restore_all_harness_copies_and_manifest(tmp_path: Path) -> None:
    first = _projection(scope="user", text="Personal version one")
    apply_skill_sync(plan_skill_sync(tmp_path, [first], include_opencode=True))
    paths = [
        tmp_path / ".agents/skills/studio-git-flow/SKILL.md",
        tmp_path / ".claude/skills/studio-git-flow/SKILL.md",
        tmp_path / ".config/opencode/skills/studio-git-flow/SKILL.md",
        tmp_path / ".studio-os/library-skills-manifest.json",
    ]
    before = {path: path.read_bytes() for path in paths}
    second = replace(first, version=4, text="Personal version two")
    apply_skill_sync(plan_skill_sync(tmp_path, [second], include_opencode=True))
    latest = list_projection_backups(tmp_path)[0]
    restored = restore_projection_backup(tmp_path, latest.directory.name)
    assert len(restored) == 4
    assert {path: path.read_bytes() for path in paths} == before
    with pytest.raises(BootstrapError, match="already rolled back"):
        restore_projection_backup(tmp_path, latest.directory.name)


def test_restore_refuses_later_local_edits_before_changing_any_file(tmp_path: Path) -> None:
    first = _projection(text="Version one")
    apply_skill_sync(plan_skill_sync(tmp_path, [first]))
    apply_skill_sync(plan_skill_sync(tmp_path, [replace(first, version=4, text="Version two")]))
    modified = tmp_path / ".claude/skills/studio-git-flow/SKILL.md"
    modified.write_text("Local changes after synchronization", encoding="utf-8")
    paths = [
        modified,
        tmp_path / ".agents/skills/studio-git-flow/SKILL.md",
        tmp_path / ".studio-os/library-skills-manifest.json",
    ]
    before = {path: path.read_bytes() for path in paths}
    with pytest.raises(BootstrapError, match="changed since the backup"):
        restore_projection_backup(tmp_path)
    assert {path: path.read_bytes() for path in paths} == before


@pytest.mark.parametrize("recreated", [False, True])
def test_restore_recovers_retired_managed_files_and_protects_recreated_local_files(
    tmp_path: Path,
    recreated: bool,
) -> None:
    first = _projection()
    apply_skill_sync(plan_skill_sync(tmp_path, [first]))
    apply_skill_sync(plan_skill_sync(tmp_path, [replace(first, deprecated=True)]))
    target = tmp_path / ".agents/skills/studio-git-flow/SKILL.md"
    assert not target.exists()
    if recreated:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Recreated locally", encoding="utf-8")
        with pytest.raises(BootstrapError, match="changed since the backup"):
            restore_projection_backup(tmp_path)
        assert target.read_text() == "Recreated locally"
        return
    restore_projection_backup(tmp_path)
    assert target.is_file()


def test_rule_projection_update_uses_the_same_restore_mechanism(tmp_path: Path) -> None:
    first = replace(_projection(), library_kind="rule", content_schema="studio.library.rule/v1")
    apply_definition_sync(plan_definition_sync(tmp_path, [first]))
    target = tmp_path / ".agents/rules/studio-git-flow.md"
    before = target.read_bytes()
    apply_definition_sync(
        plan_definition_sync(tmp_path, [replace(first, version=4, text="New rule")])
    )
    restore_projection_backup(tmp_path)
    assert target.read_bytes() == before


def test_manifest_changed_after_preview_refuses_apply(tmp_path: Path) -> None:
    apply_skill_sync(plan_skill_sync(tmp_path, [_projection()]))
    plan = plan_skill_sync(tmp_path, [replace(_projection(), version=4)])
    manifest = plan.manifest_path
    manifest.write_text(manifest.read_text() + "\n", encoding="utf-8")
    with pytest.raises(SkillSyncConflictError, match="manifest changed"):
        apply_skill_sync(plan)


def test_crafted_journal_cannot_restore_personal_configuration(tmp_path: Path) -> None:
    apply_skill_sync(plan_skill_sync(tmp_path, [_projection()]))
    journal = list_projection_backups(tmp_path)[0]
    path = journal.directory / "journal.json"
    raw = json.loads(path.read_text())
    raw["entries"][0]["path"] = ".codex/config.toml"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(BootstrapError, match="non-projection"):
        restore_projection_backup(tmp_path)


def test_restore_inventory_is_offline_and_creation_undo_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    apply_skill_sync(plan_skill_sync(tmp_path, [_projection()]))

    def unexpected_config():
        raise AssertionError("restore must be offline")

    monkeypatch.setattr(cli, "_load_config", unexpected_config)
    cli.main(["library", "restore", "--home", str(tmp_path), "--list"])
    assert len(json.loads(capsys.readouterr().out)["backups"]) == 1
    cli.main(["library", "restore", "--home", str(tmp_path)])
    assert len(json.loads(capsys.readouterr().out)["restored"]) == 3
    assert not (tmp_path / ".agents/skills/studio-git-flow/SKILL.md").exists()
