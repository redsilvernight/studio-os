"""Canonical agent definitions (P3): file-authoring source, offline projection.

`.agents/definitions/<stable-key>.md` is the single authoring source for the
four Studio OS agents. This module is pure (no network, no DB, no subprocess):
it parses a definition plus the rule/skill files it references and builds the
same `ResolvedAgentDefinition` shape the Resolution Engine produces at
runtime, so harness adapters project files and Library identically.

Two canonical stores, one precedence rule (P3.2):

* files (`.agents/`) win at *authoring* time — review, diff, anti-drift check;
* the AI Library wins at *resolution* time — `resolve_full` never reads files.

Runtime fusion (P4/AIB-D, DEC-0168): `build_merged_resolved` takes an
injected `LibrarySnapshot` — project files win per piece when present,
Library entries fill the gaps, anything missing on both sides fails
exactly like the offline path. This module stays pure: the snapshot is
pre-fetched by the caller (see `StudioApiClient.fetch_library_snapshot`).

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


@dataclass(frozen=True)
class LibrarySnapshot:
    """One agent definition resolved from the AI Library (`resolve_full`
    over HTTP), reduced to the harness-projection surface: agent head,
    rules, skills, requirements. Built by the caller via
    `LibrarySnapshot.from_resolved`, never fetched here — this module
    stays pure (no network, no DB, no subprocess)."""

    agent: ResolvedAgent
    rules: dict[str, ResolvedRule]
    skills: dict[str, ResolvedSkill]
    requirements: CapabilityRequirement

    @classmethod
    def from_resolved(cls, resolved: ResolvedAgentDefinition) -> LibrarySnapshot:
        """Reduce a `resolve_full` answer to the merge surface. Entries
        without usable text are rejected: a half-present Library piece
        must fail loudly, never project an empty harness file."""
        rules = {}
        for rule in resolved.rules:
            text = rule.content.get("text")
            if not isinstance(text, str):
                raise ValueError(f"library snapshot: rule {rule.stable_key!r} has no text content")
            rules[rule.stable_key] = rule
        skills = {}
        for skill in resolved.skills:
            text = skill.content.get("text")
            if not isinstance(text, str):
                raise ValueError(
                    f"library snapshot: skill {skill.stable_key!r} has no text content"
                )
            skills[skill.stable_key] = skill
        return cls(
            agent=resolved.agent,
            rules=rules,
            skills=skills,
            requirements=resolved.requirements,
        )


def _resolved_rule(
    key: str,
    text: str,
    *,
    resource_id: uuid.UUID,
    scope: LibraryScope,
    version: int,
    version_origin: VersionOrigin,
    title: str | None = None,
    paths: list[Any] | None = None,
) -> ResolvedRule:
    return ResolvedRule(
        resource_id=resource_id,
        stable_key=key,
        scope=scope,
        version=version,
        version_origin=version_origin,
        title=title if title is not None else key,
        content={
            "content_schema": "studio.library.rule/v1",
            "text": text,
        },
        paths=paths if paths is not None else [],
    )


def _resolved_skill(
    key: str,
    text: str,
    *,
    resource_id: uuid.UUID,
    scope: LibraryScope,
    version: int,
    version_origin: VersionOrigin,
    title: str | None = None,
    provenance: Provenance | None = None,
) -> ResolvedSkill:
    return ResolvedSkill(
        resource_id=resource_id,
        stable_key=key,
        scope=scope,
        version=version,
        version_origin=version_origin,
        title=title if title is not None else key,
        content={
            "content_schema": "studio.library.skill/v1",
            "text": text,
        },
        provenance=provenance if provenance is not None else _prov(key, BindingRelation.USES_SKILL),
    )


def _resolved_agent_head(
    agent: CanonicalAgent,
    *,
    resource_id: uuid.UUID,
    scope: LibraryScope,
    version: int,
    version_origin: VersionOrigin,
    provenance: Provenance,
) -> ResolvedAgent:
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
    return ResolvedAgent(
        resource_id=resource_id,
        kind=AGENT,
        stable_key=agent.stable_key,
        scope=scope,
        version=version,
        version_origin=version_origin,
        title=agent.title,
        content=content,
        provenance=provenance,
    )


def build_offline_resolved(repo_root: Path | str, stable_key: str) -> ResolvedAgentDefinition:
    """Authoring-time effective snapshot: the canonical agent plus the exact
    rule/skill texts it references, as version 1 / ACTIVE / STUDIO. Deterministic:
    same files always yield the same definition. Runtime resolution
    (`resolve_full`) remains the only version-truthful path."""
    root = Path(repo_root)
    agent = load_definition(root, stable_key)
    rules = [
        _resolved_rule(
            key,
            load_rule_text(root, key),
            resource_id=_namespace("resource", key),
            scope=LibraryScope.STUDIO,
            version=1,
            version_origin=VersionOrigin.ACTIVE,
        )
        for key in agent.rules
    ]
    skills = [
        _resolved_skill(
            key,
            load_skill_text(root, key),
            resource_id=_namespace("resource", key),
            scope=LibraryScope.STUDIO,
            version=1,
            version_origin=VersionOrigin.ACTIVE,
        )
        for key in agent.skills
    ]
    resolved_agent = _resolved_agent_head(
        agent,
        resource_id=_namespace("resource", f"agent:{stable_key}"),
        scope=LibraryScope.STUDIO,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        provenance=_prov(f"agent:{stable_key}"),
    )
    requirements = CapabilityRequirement.model_validate(agent.requirements)
    return ResolvedAgentDefinition(
        agent=resolved_agent,
        rules=rules,
        skills=skills,
        requirements=requirements,
    )


def _file_or_library_text(
    root: Path,
    kind: str,
    key: str,
    library: LibrarySnapshot,
) -> tuple[str, ResolvedRule | ResolvedSkill | None]:
    """Project file text win, Library entry second. A corrupt project file
    (`ValueError`) always raises — it must never silently fall back. Only a
    missing file (`FileNotFoundError`) falls back; missing on both sides
    raises the same `FileNotFoundError` the offline path raises."""
    loader = load_rule_text if kind == "rule" else load_skill_text
    try:
        return loader(root, key), None
    except FileNotFoundError:
        pass
    if kind == "rule":
        entry: ResolvedRule | ResolvedSkill | None = library.rules.get(key)
    else:
        entry = library.skills.get(key)
    if entry is None:
        path = root / ".agents" / ("rules" if kind == "rule" else "skills")
        raise FileNotFoundError(
            f"{path}: no project file and no Library entry for {key!r}"
        ) from None
    text = entry.content.get("text")
    if not isinstance(text, str):  # pragma: no cover - guarded by from_resolved
        raise ValueError(f"library snapshot: {kind} {key!r} has no text content")
    return text, entry


def build_merged_resolved(
    repo_root: Path | str,
    stable_key: str,
    *,
    library: LibrarySnapshot | None = None,
) -> ResolvedAgentDefinition:
    """Runtime fusion (P4/AIB-D, DEC-0168): the project `.agents/` authoring
    source merged with a pre-fetched `LibrarySnapshot`, per piece. Project
    files win when present (review/diff/anti-drift source); Library entries
    fill the gaps, so a near-empty repo (manifest + managed blocks) still
    resolves the studio resources. `library=None` is the strict offline
    path, identical to `build_offline_resolved`. Library-backed pieces
    carry their real identity and provenance (version-truthful);
    Library-backed heads default the file-only keys the Library never
    carries (`instructions`, `triggers`, `edit_policy`, `tools`). This
    function never re-decides versions (DEC-0144): it only picks whole
    pieces from the two sources."""
    if library is None:
        return build_offline_resolved(repo_root, stable_key)
    if library.agent.stable_key != stable_key:
        raise ValueError(
            f"library snapshot is for {library.agent.stable_key!r}, not {stable_key!r}"
        )
    root = Path(repo_root)
    try:
        agent = load_definition(root, stable_key)
    except FileNotFoundError:
        agent = None
    if agent is None:
        head_source = CanonicalAgent(
            stable_key=stable_key,
            title=library.agent.title,
            summary=str(library.agent.content.get("summary") or ""),
            intended_use=str(library.agent.content.get("intended_use") or ""),
        )
        keys_rules = list(library.rules)
        keys_skills = list(library.skills)
        resolved_agent = _resolved_agent_head(
            head_source,
            resource_id=library.agent.resource_id,
            scope=library.agent.scope,
            version=library.agent.version,
            version_origin=library.agent.version_origin,
            provenance=library.agent.provenance,
        )
        requirements = library.requirements
    else:
        keys_rules = list(agent.rules)
        keys_skills = list(agent.skills)
        resolved_agent = _resolved_agent_head(
            agent,
            resource_id=_namespace("resource", f"agent:{stable_key}"),
            scope=LibraryScope.STUDIO,
            version=1,
            version_origin=VersionOrigin.ACTIVE,
            provenance=_prov(f"agent:{stable_key}"),
        )
        requirements = CapabilityRequirement.model_validate(agent.requirements)
    rules = []
    for key in keys_rules:
        text, entry = _file_or_library_text(root, "rule", key, library)
        if entry is None:
            rules.append(
                _resolved_rule(
                    key,
                    text,
                    resource_id=_namespace("resource", key),
                    scope=LibraryScope.STUDIO,
                    version=1,
                    version_origin=VersionOrigin.ACTIVE,
                )
            )
        else:
            assert isinstance(entry, ResolvedRule)
            rules.append(
                _resolved_rule(
                    key,
                    text,
                    resource_id=entry.resource_id,
                    scope=entry.scope,
                    version=entry.version,
                    version_origin=entry.version_origin,
                    title=entry.title,
                    paths=list(entry.paths),
                )
            )
    skills = []
    for key in keys_skills:
        text, entry = _file_or_library_text(root, "skill", key, library)
        if entry is None:
            skills.append(
                _resolved_skill(
                    key,
                    text,
                    resource_id=_namespace("resource", key),
                    scope=LibraryScope.STUDIO,
                    version=1,
                    version_origin=VersionOrigin.ACTIVE,
                )
            )
        else:
            assert isinstance(entry, ResolvedSkill)
            skills.append(
                _resolved_skill(
                    key,
                    text,
                    resource_id=entry.resource_id,
                    scope=entry.scope,
                    version=entry.version,
                    version_origin=entry.version_origin,
                    title=entry.title,
                    provenance=entry.provenance,
                )
            )
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
