from __future__ import annotations

import json
from pathlib import Path

from studio_client.adapters.base import AdapterArtifact, classify_artifact_state
from studio_client.drift import (
    classify_state,
    dump_manifest_v2,
    hash_text,
    load_managed_hashes,
)


def test_classify_state_covers_four_states() -> None:
    assert classify_state(None, "desired", None) == "missing"
    assert classify_state("desired", "desired", None) == "current"
    assert classify_state("old", "new", hash_text("old")) == "outdated"
    assert classify_state("edited", "new", hash_text("old")) == "locally_modified"
    assert classify_state("edited", "new", None) == "locally_modified"


def test_load_managed_hashes_accepts_v1_skills_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "skills": [{"stable_key": "studio-git-flow", "sha256": "abc"}],
            }
        ),
        encoding="utf-8",
    )
    assert load_managed_hashes(manifest) == {("skill", "studio-git-flow"): "abc"}


def test_load_managed_hashes_accepts_v2_multi_kind_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "items": [
                    {"kind": "rule", "stable_key": "studio-x", "sha256": "r"},
                    {"kind": "agent", "stable_key": "studio-y", "sha256": "a"},
                    {"kind": "workflow", "stable_key": "studio-z", "sha256": "w"},
                    {"kind": "block", "stable_key": "agents-md", "sha256": "b"},
                ],
            }
        ),
        encoding="utf-8",
    )
    hashes = load_managed_hashes(manifest)
    assert hashes[("rule", "studio-x")] == "r"
    assert hashes[("workflow", "studio-z")] == "w"
    assert len(hashes) == 4


def test_load_managed_hashes_rejects_invalid_manifest(tmp_path: Path) -> None:
    assert load_managed_hashes(tmp_path / "absent.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("not json", encoding="utf-8")
    assert load_managed_hashes(broken) == {}


def test_dump_manifest_v2_is_deterministic() -> None:
    text = dump_manifest_v2(
        [
            {"kind": "skill", "stable_key": "b", "sha256": "2"},
            {"kind": "agent", "stable_key": "a", "sha256": "1"},
        ]
    )
    payload = json.loads(text)
    assert payload["schema_version"] == 2
    assert [row["stable_key"] for row in payload["items"]] == ["a", "b"]


def test_classify_artifact_state_reuses_skill_taxonomy() -> None:
    artifact = AdapterArtifact(path=".claude/agents/x.md", content="new")
    assert classify_artifact_state(None, artifact, None) == "missing"
    assert classify_artifact_state("new", artifact, None) == "current"
    assert classify_artifact_state("old", artifact, hash_text("old")) == "outdated"
    assert classify_artifact_state("edited", artifact, hash_text("old")) == "locally_modified"


def test_skill_sync_plan_target_keeps_outdated_distinction(tmp_path: Path) -> None:
    from studio_client.skill_sync import _plan_target

    home = tmp_path / "home"
    target_dir = home / ".agents" / "skills" / "studio-x"
    target_dir.mkdir(parents=True)
    (target_dir / "SKILL.md").write_text("old", encoding="utf-8")
    outdated = _plan_target(home, "studio-x", "agents", "new", hash_text("old"))
    assert outdated.state == "outdated"
    edited = _plan_target(home, "studio-x", "agents", "new", hash_text("other"))
    assert edited.state == "locally_modified"
