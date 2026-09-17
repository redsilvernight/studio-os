from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.library import BindingRelation, LibraryKind, LibraryScope, VersionOrigin
from studio_contracts.resolution import (
    AgentResolutionSnapshot,
    NodeBinding,
    ResolutionErrorCode,
    ResolutionFailure,
    ResolutionNode,
    ResolvedAgentDefinition,
    RuntimeCandidate,
    resolve_agent,
)
from studio_contracts.runtime import RuntimeTarget

from studio_api.db.models.library import (
    LibraryResourceLinkModel,
    LibraryResourceVersionModel,
)
from studio_api.services import library as library_service
from studio_api.services import runtime_bindings as runtime_service
from studio_api.services.authz import Principal


def _definition_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail={"error_code": "definition_not_found"})


def _map_failure(failure: ResolutionFailure) -> HTTPException:
    """Public HTTP mapping for pure P5 failures.

    Dependency failures stay behind the unified `definition_not_found`
    (DEC-0065 §2: no oracle over invisible resources). The caller's own
    runtime choice and malformed snapshots are explicit 422s — they only
    ever describe data the caller already supplied or could read."""

    code = failure.error.error_code
    if code in (
        ResolutionErrorCode.DEFINITION_NOT_FOUND,
        ResolutionErrorCode.UNRESOLVABLE_DEPENDENCY,
    ):
        return _definition_not_found()
    if code == ResolutionErrorCode.RUNTIME_INCOMPATIBLE:
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error_code": "runtime_incompatible", **failure.error.details},
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_resolution_input", **failure.error.details},
    )


async def _version_row(
    session: AsyncSession, resource_id: UUID, version: int
) -> LibraryResourceVersionModel | None:
    stmt = select(LibraryResourceVersionModel).where(
        LibraryResourceVersionModel.resource_id == resource_id,
        LibraryResourceVersionModel.version == version,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _load_node(
    session: AsyncSession,
    principal: Principal,
    resource_id: UUID,
    version_number: int,
    origin: VersionOrigin,
) -> ResolutionNode:
    """Loads one visible resource version plus its binding edges.

    Visibility is enforced per target (`get_resource` masks another user's
    private rows as 404); any missing or invisible dependency maps to the
    public `definition_not_found`, exactly like P2's depth-1 check."""

    resource = await library_service.get_resource(session, principal, resource_id)
    if resource is None:
        raise _definition_not_found()
    row = await _version_row(session, resource.id, version_number)
    if row is None:
        raise _definition_not_found()
    link_stmt = select(LibraryResourceLinkModel).where(
        LibraryResourceLinkModel.from_version_id == row.id
    )
    bindings: list[NodeBinding] = []
    for link in (await session.execute(link_stmt)).scalars().all():
        target = await library_service.get_resource(session, principal, link.to_resource_id)
        if target is None:
            raise _definition_not_found()
        if await _version_row(session, target.id, link.to_version) is None:
            raise _definition_not_found()
        try:
            relation = BindingRelation(link.relation)
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "invalid_resolution_input", "reason": "unknown_relation"},
            ) from None
        bindings.append(
            NodeBinding(
                relation=relation,
                target_resource_id=target.id,
                target_version=link.to_version,
            )
        )
    return ResolutionNode(
        resource_id=resource.id,
        kind=LibraryKind(resource.kind),
        stable_key=resource.stable_key,
        scope=LibraryScope(resource.scope),
        version=version_number,
        version_origin=origin,
        deprecated=(resource.status == "deprecated"),
        title=row.title,
        content=dict(row.content),
        bindings=bindings,
    )


async def resolve_full(
    session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    stable_key: str,
    project_id: UUID | None = None,
    session_overrides: Mapping[tuple[LibraryKind, str], RuntimeTarget] | None = None,
) -> ResolvedAgentDefinition:
    """P5 acquisition + pure assembly (no endpoint exposes this in P5).

    Root selection stays P2's truth (`resolve_definition`: shadowing, lock vs
    active); runtime acquisition stays P4's (`load_candidates`: validation +
    liveness).     This function only loads, builds the snapshot and delegates
    every logical decision to the pure `resolve_agent` core."""

    resolved = await library_service.resolve_definition(
        session, principal, kind, stable_key, project_id
    )
    root = await _load_node(
        session, principal, resolved.resource_id, resolved.version, resolved.version_origin
    )
    nodes: list[ResolutionNode] = []
    for binding in root.bindings:
        node = await _load_node(
            session,
            principal,
            binding.target_resource_id,
            binding.target_version,
            VersionOrigin.PIN,
        )
        nodes.append(node)
        if node.kind == LibraryKind.SKILL:
            for sub_binding in node.bindings:
                nodes.append(
                    await _load_node(
                        session,
                        principal,
                        sub_binding.target_resource_id,
                        sub_binding.target_version,
                        VersionOrigin.PIN,
                    )
                )
    profile_key: tuple[LibraryKind, str] | None = None
    for binding in root.bindings:
        if binding.relation == BindingRelation.REQUIRES_MODEL_PROFILE:
            target = next(
                (node for node in nodes if node.resource_id == binding.target_resource_id),
                None,
            )
            if target is not None:
                profile_key = (target.kind, target.stable_key)
    keys = [(kind, stable_key)] + ([profile_key] if profile_key is not None else [])
    candidates: list[RuntimeCandidate] = await runtime_service.load_candidates(
        session, principal, keys, project_id, session_overrides
    )
    snapshot = AgentResolutionSnapshot(agent=root, nodes=nodes, runtime_candidates=candidates)
    try:
        return resolve_agent(snapshot)
    except ResolutionFailure as failure:
        raise _map_failure(failure) from None
