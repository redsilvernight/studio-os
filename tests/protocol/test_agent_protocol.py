"""P1 minimal agent protocol - canonical rule + four skills (AUDIT P0 follow-up).

Guards: rule token budget, skill structure, harness/model neutrality of the
canonical source, and no drift between skills and the real MCP tool surface.
Canonical files live under `.agents/` (harness-neutral); `.claude/`,
`.codex/`, `.opencode/`, `CLAUDE.md`, `AGENTS.md` are projections only."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RULE = ROOT / ".agents/rules/studio-protocol.md"

SKILLS = {
    "studio-context": ROOT / ".agents/skills/studio-context/SKILL.md",
    "studio-task": ROOT / ".agents/skills/studio-task/SKILL.md",
    "studio-decision": ROOT / ".agents/skills/studio-decision/SKILL.md",
    "studio-handoff": ROOT / ".agents/skills/studio-handoff/SKILL.md",
}

# Skill -> MCP tools it is allowed to name (compositions of existing tools).
SKILL_TOOLS = {
    "studio-context": {
        "studio_prepare_context",
        "studio_resolve_agent",
        "studio_discover_definitions",
        "studio_get_task",
        "studio_get_decisions",
        "studio_get_ai_work",
    },
    "studio-task": {
        "studio_get_active_tasks",
        "studio_get_project_state",
        "studio_get_task",
        "studio_claim_task",
        "studio_claim_resource",
        "studio_start_session",
        "studio_update_task",
        "studio_log_ai_work",
        "studio_release_task",
        "studio_release_resource",
    },
    "studio-decision": {
        "studio_add_decision",
        "studio_accept_decision",
        "studio_supersede_decision",
        "studio_get_decisions",
        "studio_get_review_queue",
        "studio_prepare_context",
    },
    "studio-handoff": {
        "studio_log_ai_work",
        "studio_release_resource",
        "studio_release_task",
        "studio_end_session",
        "studio_emit_event",
        "studio_prepare_context",
        "studio_get_ai_work",
    },
}

FORBIDDEN_IDENTITY = (
    "opus",
    "sonnet",
    "haiku",
    "gpt-",
    "kimi",
    "qwen",
    "anthropic",
    "openai",
    "claude-code",
    "claude_code",
    ".claude/",
    ".codex/",
    ".opencode/",
    "CLAUDE.md",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_rule_file_exists_and_within_token_budget():
    text = _read(RULE)
    approx_tokens = len(text) // 4
    assert 150 <= approx_tokens <= 250, f"rule ~{approx_tokens} tokens, want 150-250"


def test_rule_covers_seven_reflexes_without_tool_catalog():
    text = _read(RULE)
    for marker in (
        "studio_prepare_context",
        "additional_available",
        "omitted_for_budget",
        "studio_add_decision",
        "studio-handoff",
        "studio_discover_definitions",
        "studio_resolve_agent",
        "subagent",
    ):
        assert marker in text, f"rule missing reflex marker: {marker}"
    assert "TECH/07" not in text
    assert len(re.findall(r"studio_[a-z_]+", text)) <= 10, "rule must not catalog tools"


def test_skills_exist_with_frontmatter():
    for name, path in SKILLS.items():
        text = _read(path)
        assert text.startswith("---\n"), f"{name}: missing frontmatter"
        assert f"name: {name}" in text, f"{name}: frontmatter name mismatch"
        assert "description:" in text, f"{name}: frontmatter description missing"


def test_canonical_files_name_no_model_or_harness():
    for path in (RULE, *SKILLS.values()):
        lowered = _read(path).lower()
        for token in FORBIDDEN_IDENTITY:
            assert token.lower() not in lowered, f"{path.name} leaks {token!r}"


def test_skills_only_reference_real_mcp_tools():
    server = _read(ROOT / "services/mcp/src/studio_mcp/server.py")
    real_tools = set(re.findall(r'"(studio_[a-z_]+)"', server))
    assert len(real_tools) >= 44, "expected at least the 44 known MCP tools"
    for name, path in SKILLS.items():
        mentioned = set(re.findall(r"studio_[a-z_]+", _read(path)))
        unknown = mentioned - real_tools
        assert not unknown, f"{name} references unknown tools: {sorted(unknown)}"
        allowed = SKILL_TOOLS[name]
        outside = mentioned - allowed
        assert not outside, f"{name} references out-of-scope tools: {sorted(outside)}"


def test_context_skill_teaches_progressive_disclosure():
    text = _read(SKILLS["studio-context"])
    for marker in ("why", "matched_terms", "additional_available", "omitted_for_budget"):
        assert marker in text, f"studio-context missing {marker}"


def test_handoff_skill_defines_resume_packet():
    text = _read(SKILLS["studio-handoff"])
    for marker in ("DONE", "STATE", "CHANGED", "TESTS", "NEXT", "BLOCKERS"):
        assert marker in text, f"studio-handoff missing {marker}"
    assert "handoff.close" in text  # explicitly out of scope in P1


def test_decision_skill_uses_resolve_primitives():
    text = _read(SKILLS["studio-decision"])
    assert "studio_add_decision" in text
    assert "studio_accept_decision" in text
    assert "studio_supersede_decision" in text
