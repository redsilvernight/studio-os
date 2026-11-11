"""Deterministic Library-shaped fixtures for projection tests.

Replaces the repository `.agents/` files as the input of `bootstrap.plan_files`,
`adapters_check.check_adapters` and the harness adapters: tests build a
`ProjectionBundle` (or one `ResolvedAgentDefinition`) in memory, exactly the
shape `projection_source.fetch_projection_bundle` returns from the server.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from studio_client.projection_source import ProjectionBundle, bundle_from_resolved
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

PROTOCOL_TEXT = "# Studio Protocol\n\nStudio OS is the persistent memory.\n"


def _id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, "studio-os:test-library:" + ":".join(parts))


def _provenance(key: str, relation: BindingRelation | None = None) -> Provenance:
    return Provenance(
        source=ProvenanceSource.ACTIVE_POINTER,
        resource_id=_id("resource", key),
        stable_key=key,
        scope=LibraryScope.STUDIO,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        relation=relation,
    )


def make_rule(
    key: str,
    text: str,
    *,
    applies_to: Sequence[str] = ("**",),
    scope: LibraryScope = LibraryScope.STUDIO,
) -> ResolvedRule:
    return ResolvedRule(
        resource_id=_id("resource", key),
        stable_key=key,
        scope=scope,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        title=key,
        content={
            "content_schema": "studio.library.rule/v2",
            "text": text,
            "applies_to": list(applies_to),
        },
        paths=[],
    )


def make_skill(
    key: str,
    text: str,
    *,
    files: Mapping[str, str] | None = None,
    scope: LibraryScope = LibraryScope.STUDIO,
) -> ResolvedSkill:
    content: dict[str, object] = {"content_schema": "studio.library.skill/v2", "text": text}
    if files:
        content["files"] = [{"path": path, "text": body} for path, body in files.items()]
    return ResolvedSkill(
        resource_id=_id("resource", key),
        stable_key=key,
        scope=scope,
        version=1,
        version_origin=VersionOrigin.ACTIVE,
        title=key,
        content=content,
        provenance=_provenance(key, BindingRelation.USES_SKILL),
    )


def make_agent(
    key: str,
    *,
    title: str | None = None,
    summary: str = "Reviews a change.",
    intended_use: str = "Use after an implementation.",
    instructions: str = "Review the diff and report.\n",
    triggers: Sequence[str] = ("review",),
    edit_policy: str = "deny",
    tools: Sequence[str] = ("Read", "Grep"),
    requirements: Mapping[str, object] | None = None,
    rules: Sequence[ResolvedRule] = (),
    skills: Sequence[ResolvedSkill] = (),
    scope: LibraryScope = LibraryScope.STUDIO,
) -> ResolvedAgentDefinition:
    return ResolvedAgentDefinition(
        agent=ResolvedAgent(
            resource_id=_id("resource", f"agent:{key}"),
            kind=LibraryKind.AGENT_DEFINITION,
            stable_key=key,
            scope=scope,
            version=1,
            version_origin=VersionOrigin.ACTIVE,
            title=title or key,
            content={
                "content_schema": "studio.library.agent_definition/v2",
                "summary": summary,
                "intended_use": intended_use,
                "instructions": instructions,
                "triggers": list(triggers),
                "edit_policy": edit_policy,
                "tools": list(tools),
            },
            provenance=_provenance(f"agent:{key}"),
        ),
        rules=list(rules),
        skills=list(skills),
        requirements=CapabilityRequirement.model_validate(
            dict(requirements or {"reasoning": "medium"})
        ),
    )


def sample_definitions() -> list[ResolvedAgentDefinition]:
    """Three agents sharing rules and skills (with reference files; one skill
    disables model invocation)."""
    testing = make_rule("testing", "Run the tests.\n", applies_to=("tests/**",))
    contracts = make_rule(
        "contracts", "# Contract Discipline\n\nVersion every contract.\n", applies_to=("**/*.py",)
    )
    change = make_skill(
        "contract-change",
        "---\nname: contract-change\ndescription: Change a contract.\n---\n\nSteps.\n",
        files={"references/notes.md": "Notes.\n"},
    )
    task = make_skill(
        "studio-task",
        "---\nname: studio-task\ndescription: Tracked work.\n---\n\nCycle.\n",
        files={"references/completion.md": "Completion.\n", "references/roles.md": "Roles.\n"},
    )
    migration = make_skill(
        "alembic-migration",
        "---\nname: alembic-migration\ndescription: Write a migration.\n"
        "disable-model-invocation: true\n---\n\nMigrate.\n",
    )
    return [
        make_agent("studio-tester", rules=[testing, contracts], skills=[change, task, migration]),
        make_agent("sync-debugger", rules=[testing]),
        make_agent("contract-guardian", rules=[contracts]),
    ]


def sample_bundle(*, protocol: str | None = PROTOCOL_TEXT) -> ProjectionBundle:
    bundle = bundle_from_resolved(sample_definitions())
    return ProjectionBundle(
        agents=bundle.agents,
        rules=bundle.rules,
        skills=bundle.skills,
        skill_files=bundle.skill_files,
        protocol=protocol,
    )
