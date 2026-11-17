"""Real pure generator execution, not model behavior or deployed configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
from studio_client import bootstrap
from studio_client.adapters_check import check_adapters
from studio_client.bootstrap import BootstrapError, _merge_block, make_manifest
from studio_client.canonical import (
    AGENTS_BEGIN_MARKER,
    AGENTS_END_MARKER,
    PROTOCOL_PATH,
    agents_rules_current_with,
    legacy_rules_text,
    merge_agents_rules_with,
    render_agents_rules_block_from,
)
from studio_client.projection_source import ProjectionBundle

from tests.library_bundle import sample_bundle

RULES = {"x": (["src/**"], "# Safety\nKeep secrets.\n")}
BLOCK = render_agents_rules_block_from(False)
LEGACY = legacy_rules_text(RULES)


def _merge(text: str) -> str:
    return merge_agents_rules_with(BLOCK, LEGACY, text)


def _current(text: str) -> bool:
    return agents_rules_current_with(BLOCK, LEGACY, text)


def _legacy(*, external: bool = False) -> str:
    begin = "<!-- BEGIN SYNCED CLAUDE RULES -->" if external else AGENTS_BEGIN_MARKER
    end = "<!-- END SYNCED CLAUDE RULES -->" if external else AGENTS_END_MARKER
    return (
        f'{begin}\n# Claude rules imported for Codex\n\n## x — applies to ["src/**"]'
        f"\n\n# Safety\nKeep secrets.\n{end}"
    )


@pytest.mark.parametrize("layout", ["none", "canonical", "legacy", "two", "between", "around"])
def test_migration_and_twice_generation(layout: str) -> None:
    texts = {
        "none": "user header\n",
        "canonical": BLOCK.rstrip("\n"),
        "legacy": _legacy(),
        "two": _legacy() + "\n\n" + _legacy(external=True),
        "between": _legacy() + "\n\nuser between\n\n" + _legacy(external=True),
        "around": "user before\n" + _legacy() + "\n" + _legacy(external=True) + "\nuser after",
    }
    original = texts[layout]
    updated = _merge(original)
    assert updated.count(AGENTS_BEGIN_MARKER) == 1
    assert "SYNCED CLAUDE RULES" not in updated
    for fragment in ("user header\n", "\n\nuser between\n\n", "user before\n", "\nuser after"):
        if fragment in original:
            assert fragment in updated
    assert _merge(updated) == updated
    assert _current(updated)
    assert "Keep secrets." not in updated
    assert "Studio OS Library" in updated


def test_block_is_stable_and_points_at_the_protocol() -> None:
    before = render_agents_rules_block_from(True)
    assert PROTOCOL_PATH in before
    assert render_agents_rules_block_from(True) == before
    text = "intro\n\n" + before + "outro\n"
    assert merge_agents_rules_with(before, LEGACY, text) == text


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
def test_ambiguous_content_is_refused(bad: str) -> None:
    original = "personal instructions\n" + bad
    with pytest.raises(ValueError, match="AGENTS.md"):
        _merge(original)
    assert not _current(original)


def test_duplicate_block_is_reported_by_the_drift_check(tmp_path: Path) -> None:
    updated = _merge("user\n")
    assert updated.startswith("user\n")
    assert _merge(updated) == updated
    (tmp_path / "AGENTS.md").write_text(updated + updated, encoding="utf-8")
    assert not _current(updated + updated)
    result = check_adapters(tmp_path, ProjectionBundle(rules=RULES))
    assert any("duplicated" in f["error"] for f in result.failures)


def test_orphaned_known_copy_preserves_surroundings() -> None:
    orphan = _legacy().split("\n", 1)[1].rsplit("\n", 1)[0]
    updated = _merge("before\n" + orphan + "\nafter")
    assert updated.startswith("before\n") and updated.endswith("\nafter")
    assert updated.count(AGENTS_BEGIN_MARKER) == 1


def test_bootstrap_shares_the_migration() -> None:
    original = "before\n" + _legacy() + "\nuser between\n" + _legacy(external=True) + "\nafter"
    markers = (AGENTS_BEGIN_MARKER, AGENTS_END_MARKER)
    assert _merge_block(original, BLOCK, markers, legacy=LEGACY) == _merge(original)
    with pytest.raises(BootstrapError):
        _merge_block("<!-- BEGIN BAD RULES -->", "", markers, legacy=LEGACY)


def test_three_harness_projections_are_coherent(tmp_path: Path) -> None:
    bundle = sample_bundle()
    manifest = make_manifest("demo", "Demo", ["claude-code", "codex", "opencode"])
    bootstrap.sync(tmp_path, manifest, bundle, confirm=True)
    first = check_adapters(tmp_path, bundle)
    assert first.checked > 0 and not first.failures
    bootstrap.sync(tmp_path, manifest, bundle, confirm=True)
    assert check_adapters(tmp_path, bundle) == first
