"""Projection source: what bootstrap and adapters project from (P40).

A `ProjectionBundle` is the harness-neutral input of `bootstrap.plan_files`:
resolved agent definitions, rule bodies with their `applies_to`, skill
sources and the optional protocol text. `bundle_from_repo` reads the
canonical `.agents/` files (authoring path); `bundle_from_resolved` derives
the same shape from Library resolutions, never touching `.agents/` and never
carrying a `user`-scope resource into a repository.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from studio_contracts.library import LibraryKind, LibraryScope, LibraryStatus
from studio_contracts.resolution import ResolvedAgentDefinition, ResolvedRule, ResolvedSkill

from studio_client.canonical import (
    build_offline_resolved,
    canonical_agent_keys,
    canonical_rule_keys,
    canonical_skill_keys,
    load_rule_meta,
    load_skill_source,
)

PROTOCOL_RULE_KEY = "studio-protocol"
_FRONTMATTER_START = "---\n"


@dataclass(frozen=True)
class ProjectionBundle:
    agents: dict[str, ResolvedAgentDefinition] = field(default_factory=dict)
    rules: dict[str, tuple[list[str], str]] = field(default_factory=dict)
    skills: dict[str, str] = field(default_factory=dict)
    protocol: str | None = None


def bundle_from_repo(repo_root: Path | str) -> ProjectionBundle:
    root = Path(repo_root)
    protocol_path = root / ".agents" / "rules" / f"{PROTOCOL_RULE_KEY}.md"
    return ProjectionBundle(
        agents={key: build_offline_resolved(root, key) for key in canonical_agent_keys(root)},
        rules={key: load_rule_meta(root, key) for key in canonical_rule_keys(root)},
        skills={key: load_skill_source(root, key) for key in canonical_skill_keys(root)},
        protocol=protocol_path.read_text(encoding="utf-8") if protocol_path.is_file() else None,
    )


def bundle_from_resolved(definitions: Iterable[ResolvedAgentDefinition]) -> ProjectionBundle:
    agents: dict[str, ResolvedAgentDefinition] = {}
    rules: dict[str, tuple[list[str], str]] = {}
    skills: dict[str, str] = {}
    protocol: str | None = None
    for definition in sorted(definitions, key=lambda item: item.agent.stable_key):
        if definition.agent.scope is LibraryScope.USER:
            continue
        agents[definition.agent.stable_key] = definition
        for rule in definition.rules:
            if rule.scope is LibraryScope.USER:
                continue
            if rule.stable_key == PROTOCOL_RULE_KEY:
                protocol = _rule_text(rule)
            else:
                rules[rule.stable_key] = (_applies_to(rule), _rule_text(rule))
        for skill in definition.skills:
            if skill.scope is not LibraryScope.USER:
                skills[skill.stable_key] = _skill_source(skill)
    return ProjectionBundle(agents=agents, rules=rules, skills=skills, protocol=protocol)


async def fetch_projection_bundle(client: Any, project_id: UUID | None) -> ProjectionBundle:
    """Library-side bundle: every visible active agent definition resolved
    over HTTP (project context applies locks and User > Project > Studio
    precedence server-side)."""
    resources = await client.list_library_resources(
        kind=LibraryKind.AGENT_DEFINITION.value, project_id=project_id, limit=500
    )
    keys = sorted(
        {
            resource.stable_key
            for resource in resources
            if resource.status is LibraryStatus.ACTIVE and resource.scope is not LibraryScope.USER
        }
    )
    return bundle_from_resolved(
        [await client.resolve_agent(key, project_id=project_id) for key in keys]
    )


def _rule_text(rule: ResolvedRule) -> str:
    text = rule.content.get("text")
    if not isinstance(text, str):
        raise ValueError(f"resolved rule {rule.stable_key!r} has no text content")
    return text


def _applies_to(rule: ResolvedRule) -> list[str]:
    globs = rule.content.get("applies_to", [])
    if not isinstance(globs, list) or not all(isinstance(glob, str) for glob in globs):
        raise ValueError(f"resolved rule {rule.stable_key!r}: applies_to must be a list of globs")
    return list(globs)


def _skill_source(skill: ResolvedSkill) -> str:
    text = skill.content.get("text")
    if not isinstance(text, str):
        raise ValueError(f"resolved skill {skill.stable_key!r} has no text content")
    if text.startswith(_FRONTMATTER_START):
        return text
    description = " ".join((skill.title or skill.stable_key).split())
    return (
        f"{_FRONTMATTER_START}name: {json.dumps(skill.stable_key, ensure_ascii=False)}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n---\n\n{text}"
    )
