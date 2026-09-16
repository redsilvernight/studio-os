"""Tests for the deterministic Graphify update policy engine.

The engine (`graphify_update_policy.py`) is canonically global -- shipped
once next to `~/.claude/scripts/graphify_incremental_update.py`, not
duplicated per project -- so it is loaded here by path rather than as a
`scripts.*` package import. This project (Studio OS) only carries its own
`.graphify-update.toml`; the engine that reads it lives outside the repo.

Covers the general acceptance scenarios: AST always wins for native code,
an explicitly excluded generated index is never sent to Gemini, skill
copies are never extracted, milestone-only documents require --milestone,
and nothing in this list can be bypassed by naming the file explicitly via
--files (apply_policy in graphify_incremental_update.py runs
unconditionally over whatever file list it is given).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GLOBAL_ENGINE = Path.home() / ".claude" / "scripts" / "graphify_update_policy.py"

if not GLOBAL_ENGINE.exists():
    pytest.skip(
        f"global policy engine not present on this machine: {GLOBAL_ENGINE}",
        allow_module_level=True,
    )

_spec = importlib.util.spec_from_file_location("graphify_update_policy", GLOBAL_ENGINE)
assert _spec is not None and _spec.loader is not None
_policy_engine = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _policy_engine
_spec.loader.exec_module(_policy_engine)
classify, load_policy, parse_policy = (
    _policy_engine.classify,
    _policy_engine.load_policy,
    _policy_engine.parse_policy,
)

SAMPLE_TOML = """
[semantic.allowed]
patterns = ["docs/TECH/**"]

[semantic.milestone_only]
patterns = ["README.md"]

[exclude.generated]
patterns = ["docs/DECISIONS.md"]

[exclude.skill_copies]
patterns = [".claude/skills/graphify/**", ".agents/skills/graphify/**"]

[exclude.transient]
patterns = ["**/*_REPORT.md"]

[ast]
exclude = ["generated/**"]
"""


def test_native_code_change_takes_the_ast_path() -> None:
    policy = parse_policy(SAMPLE_TOML)
    decision = classify(policy, "services/api/src/studio_api/routers/decisions.py", is_code=True)
    assert decision.action == "ast"


def test_generated_index_never_calls_gemini() -> None:
    policy = parse_policy(SAMPLE_TOML)
    decision = classify(policy, "docs/DECISIONS.md", is_code=False)
    assert decision.action == "skip"
    assert "generated" in decision.reason


def test_skill_copy_is_never_extracted() -> None:
    policy = parse_policy(SAMPLE_TOML)
    for path in (
        ".claude/skills/graphify/SKILL.md",
        ".agents/skills/graphify/references/hooks.md",
    ):
        decision = classify(policy, path, is_code=False)
        assert decision.action == "skip"
        assert "skill copy" in decision.reason


def test_allowed_document_is_processed_immediately() -> None:
    policy = parse_policy(SAMPLE_TOML)
    decision = classify(policy, "docs/TECH/09_OBSIDIAN_GRAPHIFY.md", is_code=False)
    assert decision.action == "semantic"


def test_milestone_only_document_requires_the_flag() -> None:
    policy = parse_policy(SAMPLE_TOML)

    without_flag = classify(policy, "README.md", is_code=False, milestone=False)
    assert without_flag.action == "skip"
    assert "milestone" in without_flag.reason

    with_flag = classify(policy, "README.md", is_code=False, milestone=True)
    assert with_flag.action == "semantic"


def test_transient_report_is_excluded() -> None:
    policy = parse_policy(SAMPLE_TOML)
    decision = classify(policy, "docs/ROADMAP_STEP4_BREAKDOWN_REPORT.md", is_code=False)
    assert decision.action == "skip"
    assert "transient" in decision.reason


def test_default_deny_for_unlisted_document() -> None:
    policy = parse_policy(SAMPLE_TOML)
    decision = classify(policy, "docs/some_new_note.md", is_code=False)
    assert decision.action == "skip"
    assert "default deny" in decision.reason


def test_ast_exclude_pattern_skips_even_native_code() -> None:
    policy = parse_policy(SAMPLE_TOML)
    decision = classify(policy, "generated/models.py", is_code=True)
    assert decision.action == "skip"


def test_no_policy_file_returns_none() -> None:
    assert load_policy(Path(r"C:\definitely\not\a\real\project")) is None


def test_real_project_policy_excludes_decisions_md_and_skill_copies() -> None:
    policy = load_policy(PROJECT_ROOT)
    assert policy is not None
    assert classify(policy, "docs/DECISIONS.md", is_code=False).action == "skip"
    assert classify(policy, ".claude/skills/graphify/SKILL.md", is_code=False).action == "skip"
    assert (
        classify(
            policy,
            "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/09_OBSIDIAN_GRAPHIFY.md",
            is_code=False,
        ).action
        == "semantic"
    )
