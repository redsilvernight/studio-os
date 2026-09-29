"""P3 bundle sync — init/check/diff/sync, conflicts, idempotence (no DB)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client.bundle_sync import (
    BundleSyncConflictError,
    apply_bundle_sync,
    check_bundle,
    diff_bundle_plan,
    init_bundle,
)

REPO = Path(__file__).resolve().parents[2]


def test_bundle_init_creates_plan_without_writing(tmp_path: Path) -> None:
    plan = init_bundle(tmp_path)
    assert plan.repo_root == tmp_path.resolve()
    assert plan.entries
    assert plan.manifest_path == tmp_path / ".studio-os" / "bundle-manifest.json"
    assert not plan.manifest_path.exists()


def test_bundle_check_reports_missing_files(tmp_path: Path) -> None:
    plan, failures = check_bundle(tmp_path)
    assert plan.missing
    assert failures
    assert any("missing:" in f for f in failures)


def test_bundle_sync_writes_files_and_manifest(tmp_path: Path) -> None:
    plan = init_bundle(tmp_path)
    result = apply_bundle_sync(plan)
    assert result.written
    assert result.manifest_path.exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["files"]


def test_bundle_sync_is_idempotent(tmp_path: Path) -> None:
    plan = init_bundle(tmp_path)
    result1 = apply_bundle_sync(plan)
    assert result1.written

    plan2 = init_bundle(tmp_path)
    result2 = apply_bundle_sync(plan2)
    assert not result2.written
    assert not result2.backups


def test_bundle_sync_backs_up_locally_modified(tmp_path: Path) -> None:
    plan = init_bundle(tmp_path)
    apply_bundle_sync(plan)

    for entry in plan.entries:
        if entry.target.kind == "rule":
            entry.target.path.write_text("# user modified\n", encoding="utf-8")
            break

    plan2 = init_bundle(tmp_path)
    assert plan2.locally_modified

    with pytest.raises(BundleSyncConflictError):
        apply_bundle_sync(plan2)

    result = apply_bundle_sync(plan2, overwrite=True)
    assert result.backups
    assert result.written


def test_bundle_diff_shows_changes(tmp_path: Path) -> None:
    plan = init_bundle(tmp_path)
    diff = diff_bundle_plan(plan)
    assert diff
    assert "---" in diff
    assert "+++" in diff


def test_bundle_diff_empty_after_sync(tmp_path: Path) -> None:
    plan = init_bundle(tmp_path)
    apply_bundle_sync(plan)

    plan2 = init_bundle(tmp_path)
    diff = diff_bundle_plan(plan2)
    assert not diff


def test_bundle_manifest_hashes_match_content(tmp_path: Path) -> None:
    plan = init_bundle(tmp_path)
    apply_bundle_sync(plan)

    manifest = json.loads(plan.manifest_path.read_text(encoding="utf-8"))
    for row in manifest["files"]:
        content = (tmp_path / row["path"]).read_text(encoding="utf-8")
        import hashlib

        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert digest == row["sha256"]


def test_bundle_claude_md_managed_block(tmp_path: Path) -> None:
    plan = init_bundle(tmp_path)
    apply_bundle_sync(plan)

    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    text = claude_md.read_text(encoding="utf-8")
    assert "<!-- BEGIN STUDIO-OS MANAGED -->" in text
    assert "<!-- END STUDIO-OS MANAGED -->" in text


def test_bundle_claude_md_preserves_user_content(tmp_path: Path) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# My Project\n\nUser content here.\n", encoding="utf-8")

    plan = init_bundle(tmp_path)
    apply_bundle_sync(plan, overwrite=True)

    text = claude_md.read_text(encoding="utf-8")
    assert "# My Project" in text
    assert "User content here." in text
    assert "<!-- BEGIN STUDIO-OS MANAGED -->" in text


def test_bundle_check_passes_after_sync(tmp_path: Path) -> None:
    plan = init_bundle(tmp_path)
    apply_bundle_sync(plan)

    _, failures = check_bundle(tmp_path)
    assert not failures
