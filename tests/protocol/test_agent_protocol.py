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
        "studio_prepare_context",
        "studio_claim_resources",
        "studio_start_work",
        "studio_handoff",
        "studio_update_task",
        "studio_log_ai_work",
        "studio_sync",
        "studio_coordinate",
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
        "studio_handoff",
        "studio_log_ai_work",
        "studio_prepare_context",
        "studio_get_ai_work",
        "studio_release_resource",
        "studio_release_task",
        "studio_end_session",
        "studio_start_work",
        "studio_sync",
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


def test_rule_file_exists_and_within_token_budget() -> None:
    text = _read(RULE)
    assert len(text.encode("utf-8")) <= 1500, "permanent protocol exceeds its byte budget"


def test_rule_covers_seven_reflexes_without_tool_catalog() -> None:
    text = _read(RULE)
    for marker in (
        "studio_prepare_context",
        "additional_available",
        "omitted_for_budget",
        "studio_add_decision",
        "studio_start_work",
        "studio_handoff",
        "studio-task",
        "studio_discover_definitions",
        "studio_resolve_agent",
        "subagent",
    ):
        assert marker in text, f"rule missing reflex marker: {marker}"
    assert "studio-workflow" not in text
    assert "studio-handoff" not in text
    assert "TECH/07" not in text
    assert len(re.findall(r"studio_[a-z_]+", text)) <= 10, "rule must not catalog tools"


def test_skills_exist_with_frontmatter() -> None:
    for name, path in SKILLS.items():
        text = _read(path)
        assert text.startswith("---\n"), f"{name}: missing frontmatter"
        assert f"name: {name}" in text, f"{name}: frontmatter name mismatch"
        assert "description:" in text, f"{name}: frontmatter description missing"


def test_canonical_files_name_no_model_or_harness() -> None:
    for path in (RULE, *SKILLS.values()):
        lowered = _read(path).lower()
        for token in FORBIDDEN_IDENTITY:
            assert token.lower() not in lowered, f"{path.name} leaks {token!r}"


def test_skills_only_reference_real_mcp_tools() -> None:
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


def test_context_skill_teaches_progressive_disclosure() -> None:
    text = _read(SKILLS["studio-context"])
    for marker in ("why", "matched_terms", "additional_available", "omitted_for_budget"):
        assert marker in text, f"studio-context missing {marker}"


def test_readonly_intent_precedes_task_ids() -> None:
    rule = _read(RULE)
    task = _read(SKILLS["studio-task"])
    assert "Explicit read-only intent is decisive" in rule
    assert rule.index("Explicit read-only intent") < rule.index("Mutable tracked work")
    assert "even if a task ID or agent ID is supplied" in rule
    assert task.index("Explicit read-only intent is decisive") < task.index(
        "Tracked work with mutations authorized"
    )


def test_handoff_skill_defines_resume_packet() -> None:
    text = _read(SKILLS["studio-handoff"])
    for marker in ("DONE", "STATE", "CHANGED", "TESTS", "NEXT", "BLOCKERS"):
        assert marker in text, f"studio-handoff missing {marker}"
    # L3: handoff.close is out of scope; studio_handoff is the single-call closer
    assert "studio_handoff" in text
    assert "studio_start_work" in text  # Resume uses start_work


def test_decision_skill_uses_resolve_primitives() -> None:
    text = _read(SKILLS["studio-decision"])
    assert "studio_add_decision" in text
    assert "studio_accept_decision" in text
    assert "studio_supersede_decision" in text


def test_cross_harness_resume_uses_start_work_and_handoff() -> None:
    """A fresh agent (possibly another harness) resumes a task using
    L2/L3 composites: start_work → work → handoff. The skill text
    should reference these two tools as the canonical flow."""
    text = _read(SKILLS["studio-task"])
    assert "studio_start_work" in text
    assert "studio_handoff" in text
    assert "Explicit read-only intent is decisive" in text

    text = _read(SKILLS["studio-handoff"])
    assert "studio_handoff" in text
    # Resume flow: Agent B uses studio_start_work to claim + resume
    assert "studio_start_work" in text


def test_skills_teach_sync_checkpoints_and_handoff_signal() -> None:
    task = _read(SKILLS["studio-task"])
    for marker in ("studio_sync", "next_cursor", "ack", "coordination_text", "quoted data"):
        assert marker in task, f"studio-task missing {marker}"
    handoff = _read(SKILLS["studio-handoff"])
    for marker in ("coordination.handoff", "coordination_text", "studio_sync"):
        assert marker in handoff, f"studio-handoff missing {marker}"
    assert "Never call `studio_sync` afterward with its" in task
    assert "studio_sync(agent_id=..., task_id=...)" in task
    assert "Never call `studio_sync` afterward with its" in handoff
    assert "session_not_found" in handoff
