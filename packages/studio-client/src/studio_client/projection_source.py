"""Projection source: what bootstrap and adapters project from (P40).

A `ProjectionBundle` is the harness-neutral input of `bootstrap.plan_files`:
resolved agent definitions, rule bodies with their `applies_to`, skill
sources and the optional protocol text. `bundle_from_resolved` derives it
from Library resolutions and never carries a `user`-scope resource into a
repository.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from studio_contracts.library import LibraryKind, LibraryScope, LibraryStatus
from studio_contracts.resolution import ResolvedAgentDefinition, ResolvedRule, ResolvedSkill

PROTOCOL_RULE_KEY = "studio-protocol"
_FRONTMATTER_START = "---\n"


@dataclass(frozen=True)
class ProjectionBundle:
    agents: dict[str, ResolvedAgentDefinition] = field(default_factory=dict)
    rules: dict[str, tuple[list[str], str]] = field(default_factory=dict)
    skills: dict[str, str] = field(default_factory=dict)
    skill_files: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    protocol: str | None = None


def bundle_from_resolved(definitions: Iterable[ResolvedAgentDefinition]) -> ProjectionBundle:
    agents: dict[str, ResolvedAgentDefinition] = {}
    rules: dict[str, tuple[list[str], str]] = {}
    skills: dict[str, str] = {}
    skill_files: dict[str, tuple[tuple[str, str], ...]] = {}
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
                skill_files[skill.stable_key] = _resolved_skill_files(skill)
    return ProjectionBundle(
        agents=agents, rules=rules, skills=skills, skill_files=skill_files, protocol=protocol
    )


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
    bundle = bundle_from_resolved(
        [await client.resolve_agent(key, project_id=project_id) for key in keys]
    )
    if bundle.protocol is None:
        bundle = replace(bundle, protocol=await _fetch_protocol(client))
    return bundle


async def _fetch_protocol(client: Any) -> str | None:
    """Text of the active Studio-scope `studio-protocol` rule, which no agent
    has to bind to be projected."""
    for resource in await client.list_library_resources(
        kind=LibraryKind.RULE.value, scope=LibraryScope.STUDIO.value, limit=500
    ):
        if (
            resource.stable_key == PROTOCOL_RULE_KEY
            and resource.status is LibraryStatus.ACTIVE
            and resource.active_version
        ):
            for version in await client.list_library_versions(resource.id):
                if version.version == resource.active_version:
                    text = version.content.get("text")
                    return text if isinstance(text, str) else None
    return None


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
    flag = (
        "disable-model-invocation: true\n" if skill.content.get("disable_model_invocation") else ""
    )
    return (
        f"{_FRONTMATTER_START}name: {json.dumps(skill.stable_key, ensure_ascii=False)}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n{flag}---\n\n{text}"
    )


def _resolved_skill_files(skill: ResolvedSkill) -> tuple[tuple[str, str], ...]:
    """Auxiliary `references/` files carried by a resolved skill (`files[]`).

    `skill/v1` content shape: a list of `{path, text}` objects. Anything
    else is ignored here (the Library equivalence gate reports it as
    `unresolved`); only string `path`/`text` pairs are projected."""
    raw = skill.content.get("files")
    if not isinstance(raw, list):
        return ()
    files: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        path, text = entry.get("path"), entry.get("text")
        if isinstance(path, str) and isinstance(text, str):
            files.append((path, text))
    return tuple(files)
