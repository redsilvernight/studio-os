"""Harness projection renderers: rule files, the `AGENTS.md`/`CLAUDE.md` managed
blocks and skill files, all derived from a Library bundle
(`projection_source.ProjectionBundle`). Pure: no network, no DB, no subprocess,
no repository read.
"""

from __future__ import annotations

import re

import yaml

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)


def _glob_list(globs: list[str]) -> str:
    return "[" + ", ".join(f'"{g}"' for g in globs) + "]"


def render_claude_rule(stable_key: str, applies_to: list[str], body: str) -> str:
    """`.claude/rules/<key>.md` projection: harness `paths` envelope around
    the canonical body (byte-stable)."""
    return f"---\npaths: {_glob_list(applies_to)}\n---\n\n{body}"


AGENTS_BEGIN_MARKER = "<!-- BEGIN GENERATED RULES from .agents/rules -->"
AGENTS_END_MARKER = "<!-- END GENERATED RULES -->"
CLAUDE_BEGIN_MARKER = "<!-- BEGIN STUDIO-OS MANAGED -->"
CLAUDE_END_MARKER = "<!-- END STUDIO-OS MANAGED -->"
_PROTOCOL_RULE_KEY = "studio-protocol"
PROTOCOL_PATH = f".studio/{_PROTOCOL_RULE_KEY}.md"


def render_claude_md_block_from(has_protocol: bool) -> str:
    lines = [
        CLAUDE_BEGIN_MARKER,
        "Règles, skills et agents canoniques : Library Studio OS (projections régénérées).",
    ]
    if has_protocol:
        lines.append(f"@{PROTOCOL_PATH}")
    lines.append(CLAUDE_END_MARKER)
    return "\n".join(lines) + "\n"


def render_agents_rules_block_from(has_protocol: bool) -> str:
    parts = []
    if has_protocol:
        parts.append(f"Read `{PROTOCOL_PATH}` before any task.")
    parts.append(
        "Canonical rules live in the Studio OS Library; before editing a path, read the rules "
        "whose `applies_to` front matter matches it (scopes are not automatic in every harness)."
    )
    return (
        AGENTS_BEGIN_MARKER
        + "\n# Project rules (studio-client)\n\n"
        + "\n\n".join(parts)
        + "\n"
        + AGENTS_END_MARKER
        + "\n"
    )


def legacy_rules_text(rules: dict[str, tuple[list[str], str]]) -> str:
    parts = [
        f"## {key} — applies to {_glob_list(paths)}\n\n{body.rstrip()}"
        for key, (paths, body) in sorted(rules.items())
    ]
    return "# Claude rules imported for Codex\n\n" + "\n\n".join(parts)


def merge_agents_rules_with(block: str, legacy: str, text: str) -> str:
    text = text.replace("\r\n", "\n")
    markers = {
        AGENTS_BEGIN_MARKER: AGENTS_END_MARKER,
        "<!-- BEGIN SYNCED CLAUDE RULES -->": "<!-- END SYNCED CLAUDE RULES -->",
    }
    spans: list[tuple[int, int]] = []
    token_pattern = r"<!-- (?:BEGIN|END) [^\n]*RULES[^\n]* -->"
    tokens = list(re.finditer(token_pattern, text))
    index = 0
    while index < len(tokens):
        begin = tokens[index]
        end_marker = markers.get(begin.group())
        if end_marker is None or index + 1 >= len(tokens):
            raise ValueError(
                "AGENTS.md: unknown owner or unbalanced rules markers; manual review required"
            )
        end_token = tokens[index + 1]
        if end_token.group() != end_marker:
            raise ValueError(
                "AGENTS.md: nested or mismatched rules markers; manual review required"
            )
        body = text[begin.end() : end_token.start()].strip()
        owned = begin.group() == AGENTS_BEGIN_MARKER and body.startswith(
            "# Project rules (studio-client)\n"
        )
        if not owned and body != legacy:
            raise ValueError(
                "AGENTS.md: legacy rules differ from canonical source; "
                "preserve and review before migration"
            )
        spans.append((begin.start(), end_token.end()))
        index += 2
    outside = text
    for start, end in reversed(spans):
        outside = outside[:start] + outside[end:]
    if "# Claude rules imported for Codex" in outside:
        if outside.count(legacy) != 1 or outside.count("# Claude rules imported for Codex") != 1:
            raise ValueError("AGENTS.md: ambiguous orphaned rules; manual review required")
        candidates = [
            match.start()
            for match in re.finditer(re.escape(legacy), text)
            if not any(a <= match.start() < b for a, b in spans)
        ]
        if len(candidates) != 1:
            raise ValueError("AGENTS.md: ambiguous orphaned rules; manual review required")
        start = candidates[0]
        spans.append((start, start + len(legacy)))
    spans.sort()
    block = block.rstrip("\n")
    if not spans:
        separator = "\n\n" if text and not text.endswith("\n") else "\n" if text else ""
        return text + separator + block + "\n"
    for start, end in reversed(spans[1:]):
        text = text[:start] + text[end:]
    start, end = spans[0]
    merged = text[:start] + block + text[end:]
    return merged.rstrip("\n") + "\n" if not text[end:].strip() else merged


def agents_rules_current_with(block: str, legacy: str, text: str) -> bool:
    try:
        return merge_agents_rules_with(block, legacy, text) == text.replace("\r\n", "\n")
    except ValueError:
        return False


_HARNESS_SKILL_DIRS = (".claude", ".codex", ".opencode")

CODEX_OPENAI_POLICY_PATH = "agents/openai.yaml"
CODEX_OPENAI_POLICY_TEXT = "policy:\n  allow_implicit_invocation: false\n"
"""Codex-native equivalent of the `disable-model-invocation` frontmatter flag.

OpenCode honours the frontmatter key verbatim; Codex does not, so a flagged
skill also projects `.codex/skills/<key>/agents/openai.yaml` carrying this
policy (implicit invocation off, explicit `$skill` still allowed). The
`SKILL.md` frontmatter itself stays verbatim in every harness."""


def _skill_disables_model_invocation(source: str) -> bool:
    """True when a `SKILL.md` source carries `disable-model-invocation: true`.

    Covers both bundle shapes: the repo bundle carries the verbatim frontmatter
    and the resolved bundle rebuilds it from `disable_model_invocation`
    (`projection_source._skill_source`), so one parse serves both."""
    match = _FRONTMATTER_RE.match(source)
    if match is None:
        return False
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return False
    return data.get("disable-model-invocation") is True


def skill_projections_from(
    skills: dict[str, str],
    skill_files: dict[str, tuple[tuple[str, str], ...]] | None = None,
) -> dict[str, str]:
    files = skill_files or {}
    projected: dict[str, str] = {}
    for key in sorted(skills):
        for harness in _HARNESS_SKILL_DIRS:
            projected[f"{harness}/skills/{key}/SKILL.md"] = skills[key]
            for relative, text in files.get(key, ()):
                projected[f"{harness}/skills/{key}/{relative}"] = text
        if _skill_disables_model_invocation(skills[key]):
            projected[f".codex/skills/{key}/{CODEX_OPENAI_POLICY_PATH}"] = CODEX_OPENAI_POLICY_TEXT
    return projected
