from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.library import LibraryKind, LibraryScope, ResourceDependencyPin
from studio_contracts.profiles import resolve_profile
from studio_contracts.work_profile_pack import WorkProfilePackPreview, WorkProfilePackRequest

from studio_api.services import library as library_service
from studio_api.services import resolution as resolution_service
from studio_api.services.authz import Principal, ensure_project_access


async def preview_work_profile_pack(
    session: AsyncSession, principal: Principal, request: WorkProfilePackRequest
) -> WorkProfilePackPreview:
    if request.project_id is not None:
        ensure_project_access(principal, request.project_id, "read")
    refs = [request.pack.base, *request.pack.adaptations]
    for index, ref in enumerate(refs):
        row = await library_service.get_resource(session, principal, ref.resource_id)
        if row is None or row.kind != ref.kind.value or row.stable_key != ref.stable_key:
            raise HTTPException(404, detail={"error_code": "pin_not_found"})
        if await library_service.get_version(session, row.id, ref.version) is None:
            raise HTTPException(404, detail={"error_code": "pin_version_not_found"})
        if index == 0 and row.scope != LibraryScope.STUDIO.value:
            raise HTTPException(422, detail={"error_code": "pack_base_must_be_studio"})
    definition = await resolution_service.resolve_full(
        session,
        principal,
        LibraryKind.AGENT_DEFINITION,
        request.pack.profile.agent_stable_key,
        request.project_id,
    )
    pending = [definition]
    observed: dict[tuple[UUID, int], ResourceDependencyPin] = {}
    too_large = False
    while pending:
        current = pending.pop()
        agent = current.agent
        identity = (agent.resource_id, agent.version)
        if identity in observed:
            continue
        observed[identity] = ResourceDependencyPin(
            resource_id=agent.resource_id,
            kind=agent.kind,
            stable_key=agent.stable_key,
            version=agent.version,
        )
        if len(observed) > 17:
            too_large = True
            break
        pending.extend(child.resolved for child in current.composed_agents)
    expected = {(ref.resource_id, ref.version) for ref in refs}
    actual = {(ref.resource_id, ref.version) for ref in observed.values()}
    root = refs[-1]
    matches = (
        expected == actual
        and definition.agent.resource_id == root.resource_id
        and definition.agent.version == root.version
    )
    profile = resolve_profile(request.pack.profile, definition, request.machine_policy)
    return WorkProfilePackPreview(
        accepted=matches and profile.accepted and not too_large,
        profile=profile,
        observed=sorted(observed.values(), key=lambda ref: (str(ref.resource_id), ref.version))[
            :17
        ],
        issues=["composition_too_large"]
        if too_large
        else ([] if matches else ["composition_mismatch"]),
    )
