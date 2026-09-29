from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.bootstrap_plan import (
    MAX_BOOTSTRAP_PLAN_AGENTS,
    BootstrapPlan,
    BootstrapPlanArtifact,
    BootstrapPlanRequest,
    content_hash,
    segment_for_scope,
)
from studio_contracts.library import LibraryKind, LibraryScope, VersionOrigin
from studio_contracts.resolution import (
    Provenance,
    ResolvedAgent,
    ResolvedAgentDefinition,
    ResolvedModelProfile,
    ResolvedRule,
    ResolvedSkill,
    RulePath,
)

from studio_api.services import library as library_service
from studio_api.services import resolution as resolution_service
from studio_api.services.authz import Principal, ensure_project_access

_KIND_ORDER = {
    LibraryKind.AGENT_DEFINITION: 0,
    LibraryKind.MODEL_PROFILE: 1,
    LibraryKind.SKILL: 2,
    LibraryKind.RULE: 3,
}
_DISCOVERY_PAGE = 200

ArtifactKey = tuple[UUID, int]


class _Collector:
    def __init__(self) -> None:
        self.artifacts: dict[ArtifactKey, BootstrapPlanArtifact] = {}
        self.required_by: dict[ArtifactKey, set[str]] = {}

    def add(
        self,
        *,
        root_key: str,
        resource_id: UUID,
        kind: LibraryKind,
        stable_key: str,
        scope: LibraryScope,
        version: int,
        version_origin: VersionOrigin,
        deprecated: bool,
        title: str,
        content: dict[str, object],
        provenance: Provenance | None = None,
        paths: list[RulePath] | None = None,
    ) -> None:
        key = (resource_id, version)
        self.required_by.setdefault(key, set()).add(root_key)
        existing = self.artifacts.get(key)
        if existing is None:
            self.artifacts[key] = BootstrapPlanArtifact(
                resource_id=resource_id,
                kind=kind,
                stable_key=stable_key,
                scope=scope,
                segment=segment_for_scope(scope),
                version=version,
                version_origin=version_origin,
                deprecated=deprecated,
                title=title,
                content_hash=content_hash(content),
                provenance=provenance,
                paths=list(paths or []),
            )
            return
        if paths:
            merged = {path.model_dump_json(): path for path in existing.paths}
            merged.update({path.model_dump_json(): path for path in paths})
            existing.paths = [merged[k] for k in sorted(merged)]

    def add_agent(self, root_key: str, agent: ResolvedAgent) -> None:
        self.add(
            root_key=root_key,
            resource_id=agent.resource_id,
            kind=agent.kind,
            stable_key=agent.stable_key,
            scope=agent.scope,
            version=agent.version,
            version_origin=agent.version_origin,
            deprecated=agent.deprecated,
            title=agent.title,
            content=agent.content,
            provenance=agent.provenance,
        )

    def add_skill(self, root_key: str, skill: ResolvedSkill) -> None:
        self.add(
            root_key=root_key,
            resource_id=skill.resource_id,
            kind=LibraryKind.SKILL,
            stable_key=skill.stable_key,
            scope=skill.scope,
            version=skill.version,
            version_origin=skill.version_origin,
            deprecated=skill.deprecated,
            title=skill.title,
            content=skill.content,
            provenance=skill.provenance,
        )

    def add_rule(self, root_key: str, rule: ResolvedRule) -> None:
        self.add(
            root_key=root_key,
            resource_id=rule.resource_id,
            kind=LibraryKind.RULE,
            stable_key=rule.stable_key,
            scope=rule.scope,
            version=rule.version,
            version_origin=rule.version_origin,
            deprecated=rule.deprecated,
            title=rule.title,
            content=rule.content,
            paths=rule.paths,
        )

    def add_profile(self, root_key: str, profile: ResolvedModelProfile) -> None:
        self.add(
            root_key=root_key,
            resource_id=profile.resource_id,
            kind=LibraryKind.MODEL_PROFILE,
            stable_key=profile.stable_key,
            scope=profile.scope,
            version=profile.version,
            version_origin=profile.version_origin,
            deprecated=profile.deprecated,
            title=profile.title,
            content=profile.requirements.model_dump(mode="json"),
            provenance=profile.provenance,
        )

    def add_resolved(self, root_key: str, resolved: ResolvedAgentDefinition) -> None:
        self.add_agent(root_key, resolved.agent)
        for rule in resolved.rules:
            self.add_rule(root_key, rule)
        for skill in resolved.skills:
            self.add_skill(root_key, skill)
        if resolved.model_profile is not None:
            self.add_profile(root_key, resolved.model_profile)
        for composed in resolved.composed_agents:
            self.add_resolved(root_key, composed.resolved)

    def build(self) -> list[BootstrapPlanArtifact]:
        for key, artifact in self.artifacts.items():
            artifact.required_by = sorted(self.required_by[key])
        return sorted(
            self.artifacts.values(),
            key=lambda a: (_KIND_ORDER[a.kind], a.stable_key, str(a.resource_id), a.version),
        )


def _plan_hash(artifacts: list[BootstrapPlanArtifact]) -> str:
    digest = hashlib.sha256()
    for artifact in artifacts:
        digest.update(
            "\x1f".join(
                (
                    artifact.kind.value,
                    artifact.stable_key,
                    artifact.scope.value,
                    str(artifact.version),
                    artifact.content_hash,
                )
            ).encode("utf-8")
        )
        digest.update(b"\x1e")
    return digest.hexdigest()


async def _discover_agent_keys(
    session: AsyncSession, principal: Principal, project_id: UUID
) -> list[str]:
    keys: set[str] = set()
    for scope, scoped_project in (
        (LibraryScope.STUDIO, None),
        (LibraryScope.USER, None),
        (LibraryScope.PROJECT, project_id),
    ):
        rows = await library_service.list_resources(
            session,
            principal,
            kind=LibraryKind.AGENT_DEFINITION.value,
            scope=scope.value,
            project_id=scoped_project,
            limit=_DISCOVERY_PAGE,
        )
        keys.update(row.stable_key for row in rows if row.status == "active")
    return sorted(keys)


async def build_bootstrap_plan(
    session: AsyncSession, principal: Principal, request: BootstrapPlanRequest
) -> BootstrapPlan:
    """Read-only aggregation of `resolve_full` over the selected agents: no
    resolution decision is taken here, and any failure of one agent (missing
    or invisible definition, incompatible stored runtime) fails the whole plan
    with the same public error `POST /resolutions` gives."""

    ensure_project_access(principal, request.project_id)
    if request.agent_keys:
        agent_keys = sorted(set(request.agent_keys))
    else:
        agent_keys = await _discover_agent_keys(session, principal, request.project_id)
        if len(agent_keys) > MAX_BOOTSTRAP_PLAN_AGENTS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error_code": "invalid_resolution_input",
                    "reason": "too_many_agents",
                    "limit": MAX_BOOTSTRAP_PLAN_AGENTS,
                },
            )
    collector = _Collector()
    for agent_key in agent_keys:
        resolved = await resolution_service.resolve_full(
            session,
            principal,
            LibraryKind.AGENT_DEFINITION,
            agent_key,
            request.project_id,
        )
        collector.add_resolved(agent_key, resolved)
    artifacts = collector.build()
    return BootstrapPlan(
        project_id=request.project_id,
        agent_keys=agent_keys,
        artifacts=artifacts,
        plan_hash=_plan_hash(artifacts),
    )
