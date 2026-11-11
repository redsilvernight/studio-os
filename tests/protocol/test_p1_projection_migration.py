"""Real pure generator execution, not model behavior or deployed configuration."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pytest
from studio_client import cli
from studio_client.adapters import get_adapter
from studio_client.adapters_check import check_adapters
from studio_client.bootstrap import BootstrapError, _merge_block
from studio_client.canonical import (
    AGENTS_BEGIN_MARKER,
    AGENTS_END_MARKER,
    agents_rules_current,
    build_offline_resolved,
    canonical_agent_keys,
    merge_agents_rules,
    render_agents_rules_block,
)


def _root(tmp_path: Path) -> Path:
    rules = tmp_path / ".agents/rules"
    rules.mkdir(parents=True)
    (rules / "x.md").write_text(
        '---\nname: x\nstable_key: x\napplies_to: ["src/**"]\n---\n\n# Safety\nKeep secrets.\n',
        encoding="utf-8",
    )
    return tmp_path


def _legacy(*, external: bool = False) -> str:
    begin = "<!-- BEGIN SYNCED CLAUDE RULES -->" if external else AGENTS_BEGIN_MARKER
    end = "<!-- END SYNCED CLAUDE RULES -->" if external else AGENTS_END_MARKER
    return (
        f'{begin}\n# Claude rules imported for Codex\n\n## x — applies to ["src/**"]'
        f"\n\n# Safety\nKeep secrets.\n{end}"
    )


@pytest.mark.parametrize("layout", ["none", "canonical", "legacy", "two", "between", "around"])
def test_migration_and_twice_generation(tmp_path: Path, layout: str) -> None:
    root = _root(tmp_path)
    block = render_agents_rules_block(root).rstrip("\n")
    texts = {
        "none": "user header\n",
        "canonical": block,
        "legacy": _legacy(),
        "two": _legacy() + "\n\n" + _legacy(external=True),
        "between": _legacy() + "\n\nuser between\n\n" + _legacy(external=True),
        "around": "user before\n" + _legacy() + "\n" + _legacy(external=True) + "\nuser after",
    }
    original = texts[layout]
    updated = merge_agents_rules(root, original)
    assert updated.count(AGENTS_BEGIN_MARKER) == 1
    assert "SYNCED CLAUDE RULES" not in updated
    for fragment in ("user header\n", "\n\nuser between\n\n", "user before\n", "\nuser after"):
        if fragment in original:
            assert fragment in updated
    assert merge_agents_rules(root, updated) == updated
    assert agents_rules_current(root, updated)
    assert "Keep secrets." not in updated
    assert "`.agents/rules/`" in updated


def test_block_is_stable_across_rule_versions(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / ".studio").mkdir()
    (root / ".studio/studio-protocol.md").write_text("# Protocol v1\n", encoding="utf-8")
    before = render_agents_rules_block(root)
    (root / ".studio/studio-protocol.md").write_text(
        "# Protocol v2\nmore\n", encoding="utf-8"
    )
    (root / ".agents/rules/x.md").write_text(
        '---\nname: x\nstable_key: x\napplies_to: ["lib/**"]\n---\n\n# Safety\nNew text.\n',
        encoding="utf-8",
    )
    assert render_agents_rules_block(root) == before
    assert ".studio/studio-protocol.md" in before
    text = "intro\n\n" + before + "outro\n"
    assert merge_agents_rules(root, text) == text


@pytest.mark.parametrize(
    "bad",
    [
        "<!-- BEGIN OTHER RULES -->\nuser\n<!-- END OTHER RULES -->",
        "<!-- BEGIN SYNCED CLAUDE RULES -->\nuser\n<!-- END SYNCED CLAUDE RULES -->",
        "<!-- BEGIN GENERATED RULES from .agents/rules -->\nunterminated",
        "<!-- END GENERATED RULES -->",
        _legacy().replace("Keep secrets.", "Keep secrets.\nuser content"),
        _legacy().split("\n", 1)[1].rsplit("\n", 1)[0]
        + "\n# Claude rules imported for Codex\n\nuser unknown block",
    ],
)
def test_ambiguous_content_refused_before_any_cli_write(tmp_path: Path, bad: str) -> None:
    root = _root(tmp_path)
    original = "personal instructions\n" + bad
    (root / "AGENTS.md").write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="AGENTS.md"):
        merge_agents_rules(root, original)
    assert not agents_rules_current(root, original)
    with pytest.raises(SystemExit):
        cli._rules_sync(argparse.Namespace(repo_root=str(root), overwrite=True, json=True), None)
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == original
    assert not (root / ".claude").exists()


def test_changed_rule_and_duplicate_detection(tmp_path: Path) -> None:
    root = _root(tmp_path)
    original = merge_agents_rules(root, "user\n")
    rule = root / ".agents/rules/x.md"
    rule.write_text(rule.read_text(encoding="utf-8").replace("src/**", "lib/**"), encoding="utf-8")
    updated = merge_agents_rules(root, original)
    assert updated == original
    assert updated.startswith("user\n")
    assert merge_agents_rules(root, updated) == updated
    (root / "AGENTS.md").write_text(updated + updated, encoding="utf-8")
    assert not agents_rules_current(root, updated + updated)
    result = check_adapters(root)
    assert any("duplicated" in f["error"] for f in result.failures)


def test_orphaned_known_copy_preserves_surroundings(tmp_path: Path) -> None:
    root = _root(tmp_path)
    orphan = _legacy().split("\n", 1)[1].rsplit("\n", 1)[0]
    updated = merge_agents_rules(root, "before\n" + orphan + "\nafter")
    assert updated.startswith("before\n") and updated.endswith("\nafter")
    assert updated.count(AGENTS_BEGIN_MARKER) == 1


def test_bootstrap_and_rules_sync_share_migration(tmp_path: Path) -> None:
    root = _root(tmp_path)
    original = "before\n" + _legacy() + "\nuser between\n" + _legacy(external=True) + "\nafter"
    expected = merge_agents_rules(root, original)
    assert (
        _merge_block(
            original,
            render_agents_rules_block(root),
            (AGENTS_BEGIN_MARKER, AGENTS_END_MARKER),
            repo_root=root,
        )
        == expected
    )
    (root / "AGENTS.md").write_text(original, encoding="utf-8")
    args = argparse.Namespace(repo_root=str(root), overwrite=True, json=True)
    cli._rules_sync(args, None)
    first = (root / "AGENTS.md").read_bytes()
    cli._rules_sync(args, None)
    assert (root / "AGENTS.md").read_bytes() == first
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == expected
    assert not check_adapters(root).failures
    with pytest.raises(BootstrapError):
        _merge_block(
            "<!-- BEGIN BAD RULES -->", "", (AGENTS_BEGIN_MARKER, AGENTS_END_MARKER), repo_root=root
        )


def test_three_harness_candidates_are_coherent(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source / ".agents", tmp_path / ".agents")
    for adapter_id in ("claude-code", "codex", "opencode"):
        for key in canonical_agent_keys(tmp_path):
            result = get_adapter(adapter_id).translate(build_offline_resolved(tmp_path, key))
            for artifact in result.artifacts:
                target = tmp_path / artifact.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(artifact.content, encoding="utf-8")
    cli.main(["adapters", "sync", "--repo-root", str(tmp_path), "--overwrite"])
    first = check_adapters(tmp_path)
    assert first.checked == 84 and not first.failures
    cli.main(["adapters", "sync", "--repo-root", str(tmp_path), "--overwrite"])
    assert check_adapters(tmp_path) == first
