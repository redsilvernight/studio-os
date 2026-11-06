from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import studio_client.adapters  # noqa: F401
from studio_client.adapters.base import AdapterError, get_adapter, materialize
from studio_client.hook_sync import (
    apply_hook_sync,
    fetch_hook_projections,
    plan_hook_sync,
)
from studio_client.skill_sync import apply_skill_sync, fetch_skill_projections, plan_skill_sync

from .conftest import Actor

RUNTIMES = ("claude-code", "codex", "opencode")


@dataclass
class InstallReport:
    skills: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    hooks_needing_consent: list[str] = field(default_factory=list)
    agents: dict[str, list[str]] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


async def effective_agent_keys(actor: Actor, project_id: UUID | None) -> list[str]:
    keys: set[str] = set()
    for scope, scoped_project in (("studio", None), ("user", None), ("project", project_id)):
        if scope == "project" and project_id is None:
            continue
        rows = await actor.client.list_library_resources(
            kind="agent_definition", scope=scope, project_id=scoped_project, limit=100
        )
        keys |= {r.stable_key for r in rows if r.active_version > 0}
    return sorted(keys)


async def install(
    actor: Actor,
    home: Path,
    project_id: UUID | None = None,
    *,
    consent_hooks: tuple[str, ...] = (),
) -> InstallReport:
    report = InstallReport()
    skills = await fetch_skill_projections(actor.client, project_id)
    skill_plan = plan_skill_sync(home, skills, include_opencode=True)
    apply_skill_sync(skill_plan)
    report.skills = [e.projection.stable_key for e in skill_plan.entries]

    hooks = await fetch_hook_projections(actor.client, project_id)
    hook_plan = plan_hook_sync(home, hooks, consent=consent_hooks)
    apply_hook_sync(hook_plan)
    report.hooks = [e.projection.stable_key for e in hook_plan.entries if e.status == "installed"]
    report.hooks_needing_consent = [e.projection.stable_key for e in hook_plan.needs_consent]

    for runtime in RUNTIMES:
        adapter = get_adapter(runtime)
        report.agents[runtime] = []
        report.warnings[runtime] = []
        for key in await effective_agent_keys(actor, project_id):
            resolved = await actor.client.resolve_agent(key, project_id=project_id)
            try:
                result = adapter.translate(resolved)
            except AdapterError as exc:
                report.errors[f"{runtime}:{key}"] = str(exc.code)
                continue
            materialize(result, home, overwrite=True, managed_dir=adapter.managed_dir)
            report.agents[runtime].append(key)
            report.warnings[runtime] += [f"{key}:{w.code}" for w in result.warnings]
    return report
