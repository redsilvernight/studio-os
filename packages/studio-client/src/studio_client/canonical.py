"""Canonical agent definitions (P3): file-authoring source, offline projection.

`.agents/definitions/<stable-key>.md` is the single authoring source for the
four Studio OS agents. This module is pure (no network, no DB, no subprocess):
it parses a definition plus the rule/skill files it references and builds the
same `ResolvedAgentDefinition` shape the Resolution Engine produces at
runtime, so harness adapters project files and Library identically.

Two canonical stores, one precedence rule (P3.2):

* files (`.agents/`) win at *authoring* time — review, diff, anti-drift check;
* the AI Library wins at *resolution* time — `resolve_full` never reads files.

Publishing a file to the Library strips file-only keys (`instructions`,
`triggers`, `edit_policy`, `tools`) and pins versions server-side; see
`to_publish_payload`. Generated harness files always derive from the files,
never from a third manual copy.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from studio_contracts.library import (
    BindingRelation,
    CapabilityRequirement,
    LibraryKind,
    LibraryScope,
    VersionOrigin,
)
from studio_contracts.resolution import (
    Provenance,
    ProvenanceSource,
    ResolvedAgent,
    ResolvedAgentDefinition,
    ResolvedRule,
    ResolvedSkill,
)

AGENT = LibraryKind.AGENT_DEFINITION

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)


def _split_frontmatter(text: str, *, source: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError(f"{source}: missing YAML frontmatter")
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{source}: frontmatter must be a mapping")
    return data, match.group(2).strip() + "\n"


def _namespace(*parts: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, "studio-os:canonical:" + ":".join(parts))


@dataclass(frozen=True)
class CanonicalAgent:
    """An agent definition exactly as authored under `.agents/definitions/`."""

    stable_key: str
    title: str
    summary: str
    intended_use: str
    triggers: tuple[str, ...] = ()
    edit_policy: str = "deny"
    tools: tuple[str, ...] = ()
    requirements: dict[str, Any] = field(default_factory=dict)
    rules: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    instructions: str = ""


def load_definition(repo_root: Path | str, stable_key: str) -> CanonicalAgent:
    """Parse `.agents/definitions/<stable-key>.md`. No model, provider or
    harness reference is allowed here — the file is rejected otherwise."""
    path = Path(repo_root) / ".agents" / "definitions" / f"{stable_key}.md"
    data, body = _split_frontmatter(path.read_text(encoding="utf-8"), source=str(path))
    if data.get("stable_key", stable_key) != stable_key:
        raise ValueError(f"{path}: stable_key mismatch")
    for forbidden in ("model", "provider", "harness"):
        if forbidden in data:
            raise ValueError(f"{path}: {forbidden!r} does not belong in canonical definitions")
    return CanonicalAgent(
        stable_key=stable_key,
        title=str(data.get("title") or stable_key),
        summary=str(data.get("summary") or ""),
        intended_use=str(data.get("intended_use") or ""),
        triggers=tuple(str(t) for t in data.get("triggers") or ()),
        edit_policy=str(data.get("edit_policy") or "deny"),
        tools=tuple(str(t) for t in data.get("tools") or ()),
        requirements=dict(data.get("requirements") or {}),
        rules=tuple(str(r) for r in data.get("rules") or ()),
        skills=tuple(str(s) for s in data.get("skills") or ()),
        instructions=body,
    )


def load_rule_text(repo_root: Path | str, stable_key: str) -> str:
    """Body (frontmatter stripped) of the canonical rule `.agents/rules/`."""
    path = Path(repo_root) / ".agents" / "rules" / f"{stable_key}.md"
    _, body = _split_frontmatter(path.read_text(encoding="utf-8"), source=str(path))
    return body


def load_skill_text(repo_root: Path | str, stable_key: str) -> str:
    """Body (frontmatter stripped) of the canonical skill `.agents/skills/`."""
    path = Path(repo_root) / ".agents" / "skills" / stable_key / "SKILL.md"
    _, body = _split_frontmatter(path.read_text(encoding="utf-8"), source=str(path))
    return body


def _prov(key: str, relation: BindingRelation | None = None) -> Provenance:
    return Provenance(
        source=ProvenanceSource.ACTIVE_POINTER,
        resource_id=_namespace("resource", key),
        stable_key=key,
        scope=LibraryScope.STUDIO,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        relation=relation,
    )


def build_offline_resolved(repo_root: Path | str, stable_key: str) -> ResolvedAgentDefinition:
    """Authoring-time effective snapshot: the canonical agent plus the exact
    rule/skill texts it references, as version 1 / ACTIVE / STUDIO. Deterministic:
    same files always yield the same definition. Runtime resolution
    (`resolve_full`) remains the only version-truthful path."""
    root = Path(repo_root)
    agent = load_definition(root, stable_key)
    rules = [
        ResolvedRule(
            resource_id=_namespace("resource", key),
            stable_key=key,
            scope=LibraryScope.STUDIO,
            version=1,
            version_origin=VersionOrigin.ACTIVE,
            title=key,
            content={
                "content_schema": "studio.library.rule/v1",
                "text": load_rule_text(root, key),
            },
            paths=[],
        )
        for key in agent.rules
    ]
    skills = [
        ResolvedSkill(
            resource_id=_namespace("resource", key),
            stable_key=key,
            scope=LibraryScope.STUDIO,
            version=1,
            version_origin=VersionOrigin.ACTIVE,
            title=key,
            content={
                "content_schema": "studio.library.skill/v1",
                "text": load_skill_text(root, key),
            },
            provenance=_prov(key, BindingRelation.USES_SKILL),
        )
        for key in agent.skills
    ]
    content: dict[str, object] = {
        "content_schema": "studio.library.agent_definition/v1",
        "summary": agent.summary,
        "intended_use": agent.intended_use,
        # File-only keys: never published to the Library (extra="forbid"
        # there), carried here so adapters project one source.
        "instructions": agent.instructions,
        "triggers": list(agent.triggers),
        "edit_policy": agent.edit_policy,
        "tools": list(agent.tools),
    }
    resolved_agent = ResolvedAgent(
        resource_id=_namespace("resource", f"agent:{stable_key}"),
        kind=AGENT,
        stable_key=stable_key,
        scope=LibraryScope.STUDIO,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        title=agent.title,
        content=content,
        provenance=_prov(f"agent:{stable_key}"),
    )
    requirements = CapabilityRequirement.model_validate(agent.requirements)
    return ResolvedAgentDefinition(
        agent=resolved_agent,
        rules=rules,
        skills=skills,
        requirements=requirements,
    )


def to_publish_payload(agent: CanonicalAgent) -> tuple[dict[str, object], list[tuple[str, str]]]:
    """Split a canonical agent into a Library-publishable content dict plus
    `(kind, stable_key)` pin pairs. Versions are pinned server-side at publish
    time (active versions), never invented here — the returned pairs carry no
    version."""
    content: dict[str, object] = {
        "content_schema": "studio.library.agent_definition/v1",
        "summary": agent.summary,
        "intended_use": agent.intended_use,
    }
    pins = [("rule", key) for key in agent.rules] + [("skill", key) for key in agent.skills]
    return content, pins


def canonical_agent_keys(repo_root: Path | str) -> list[str]:
    """Stable keys of every canonical definition, sorted."""
    directory = Path(repo_root) / ".agents" / "definitions"
    return sorted(p.stem for p in directory.glob("*.md"))


def canonical_rule_keys(repo_root: Path | str) -> list[str]:
    """Stable keys of every Library-projectable canonical rule, sorted.

    Only files whose frontmatter carries `applies_to` qualify: the P1
    bootstrap protocol rule (`.agents/rules/studio-protocol.md`) is a
    harness bootstrap text, not a Library rule, and is guarded by its own
    budget test instead."""
    keys = []
    for path in sorted((Path(repo_root) / ".agents" / "rules").glob("*.md")):
        try:
            data, _ = _split_frontmatter(path.read_text(encoding="utf-8"), source=str(path))
        except ValueError:
            continue
        if isinstance(data.get("applies_to"), list):
            keys.append(path.stem)
    return keys


def load_rule_meta(repo_root: Path | str, stable_key: str) -> tuple[list[str], str]:
    """`(applies_to, body)` of the canonical rule `.agents/rules/`."""
    path = Path(repo_root) / ".agents" / "rules" / f"{stable_key}.md"
    data, body = _split_frontmatter(path.read_text(encoding="utf-8"), source=str(path))
    applies_to = data.get("applies_to") or []
    if not isinstance(applies_to, list) or not all(isinstance(g, str) for g in applies_to):
        raise ValueError(f"{path}: applies_to must be a list of globs")
    return list(applies_to), body


def _glob_list(globs: list[str]) -> str:
    return "[" + ", ".join(f'"{g}"' for g in globs) + "]"


def render_claude_rule(stable_key: str, applies_to: list[str], body: str) -> str:
    """`.claude/rules/<key>.md` projection: harness `paths` envelope around
    the canonical body (byte-stable)."""
    return f"---\npaths: {_glob_list(applies_to)}\n---\n\n{body}"


AGENTS_BEGIN_MARKER = "<!-- BEGIN GENERATED RULES from .agents/rules -->"
AGENTS_END_MARKER = "<!-- END GENERATED RULES -->"


def render_agents_rules_block(repo_root: Path | str) -> str:
    """The AGENTS.md rules section, generated from `.agents/rules/`."""
    parts = []
    for key in canonical_rule_keys(repo_root):
        applies_to, body = load_rule_meta(repo_root, key)
        parts.append(f"## {key} — applies to {_glob_list(applies_to)}\n\n{body.rstrip()}")
    return (
        AGENTS_BEGIN_MARKER
        + "\n# Claude rules imported for Codex\n\n"
        + "\n\n".join(parts)
        + "\n"
        + AGENTS_END_MARKER
        + "\n"
    )
