from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.library import (
    BindingRelation,
    CapabilityRequirement,
    LibraryKind,
    LibraryResolution,
    RuntimeCapabilities,
    check_compatibility,
)
from studio_contracts.resolution import (
    ResolutionFailure,
    RuntimeCandidate,
    select_runtime,
)
from studio_contracts.runtime import (
    RuntimeBinding,
    RuntimeBindingCreate,
    RuntimeLevel,
    RuntimeResolution,
    RuntimeTarget,
)

from studio_api.db.models.library import (
    LibraryResourceLinkModel,
    LibraryResourceModel,
    LibraryResourceVersionModel,
)
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.runtime import RuntimeBindingModel, RuntimeModel
from studio_api.services import library as library_service
from studio_api.services import runtime_registry as registry_service
from studio_api.services.authz import (
    Principal,
    ensure_can_provision,
    ensure_can_write,
    forbidden,
)

_STORED_LEVELS = {
    RuntimeLevel.USER,
    RuntimeLevel.PROJECT_OVERRIDE,
    RuntimeLevel.PROJECT_DEFAULT,
    RuntimeLevel.STUDIO_DEFAULT,
}

_BINDABLE_KINDS = {LibraryKind.AGENT_DEFINITION, LibraryKind.MODEL_PROFILE}


def _invalid_runtime_binding(reason: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_runtime_binding", "reason": reason},
    )


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "runtime binding not found")


def _is_visible(principal: Principal, binding: RuntimeBindingModel) -> bool:
    """`user` bindings are owner-or-admin only (same 404-masking as user
    library resources); shared levels read like project library resources."""
    if binding.level != RuntimeLevel.USER.value:
        return True
    return principal.role == Role.ADMIN or binding.owner_user_id == principal.user.id


async def _checked_target(
    session: AsyncSession, principal: Principal, target: RuntimeTarget
) -> None:
    """Fail-closed target gate: a `runtime_id` reference must be exclusive
    (422 — no inline fields beside it, the Registry is canonical) and name
    an existing registry row (404 `runtime_not_found`) owned by the caller
    (403 — another user's private runtime is never an oracle); an inline
    machine must exist (404) and be owned by the caller (403)."""
    if target.runtime_id is not None:
        if (
            target.machine_id is not None
            or target.harness_ref is not None
            or target.provider_ref is not None
            or target.model_ref is not None
            or target.capabilities != RuntimeCapabilities()
        ):
            raise _invalid_runtime_binding("runtime_id_must_be_exclusive")
        runtime = await session.get(RuntimeModel, target.runtime_id)
        if runtime is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail={"error_code": "runtime_not_found"}
            )
        if runtime.owner_user_id != principal.user.id:
            raise forbidden("runtime", "bind")
        return
    if target.machine_id is None:
        return
    machine = await session.get(MachineModel, target.machine_id)
    if machine is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail={"error_code": "runtime_target_not_found"}
        )
    if machine.owner_user_id != principal.user.id:
        raise forbidden("runtime_binding", "bind")


async def _effective_target(session: AsyncSession, target: RuntimeTarget) -> RuntimeTarget | None:
    """Resolves a stored/session choice to its effective target. A
    `runtime_id` reference is canonical: identity, refs and capabilities
    come from the Registry row (P6/DEC-0070). A revoked/removed runtime —
    like a deleted or credential-revoked machine — is non-live: the level
    falls through to the next one, never a hard error and never a silent
    use of a dead target."""
    if target.runtime_id is not None:
        row, live = await registry_service.resolve_effective_target(session, target.runtime_id)
        if not live or row is None:
            return None
        return RuntimeTarget(
            runtime_id=row.id,
            machine_id=row.machine_id,
            harness_ref=row.harness_ref,
            provider_ref=row.provider_ref,
            model_ref=row.model_ref,
            capabilities=RuntimeCapabilities.model_validate(dict(row.capabilities or {})),
        )
    return await _live_target(session, target)


async def _live_target(session: AsyncSession, target: RuntimeTarget) -> RuntimeTarget | None:
    """A stored choice pointing at a deleted or revoked machine is
    inaccessible: the level falls through to the next one, never a hard
    error and never a silent use of a dead locus."""
    if target.machine_id is None:
        return target
    machine = await session.get(MachineModel, target.machine_id)
    if machine is None or machine.credential_revoked_at is not None:
        return None
    return target


async def create_binding(
    session: AsyncSession, principal: Principal, data: RuntimeBindingCreate
) -> RuntimeBindingModel:
    """Stores one runtime choice. The owner is always the caller
    (server-derived, never client-supplied)."""
    if data.level not in _STORED_LEVELS:
        raise _invalid_runtime_binding("ephemeral_level_not_stored")
    if data.target_kind not in _BINDABLE_KINDS:
        raise _invalid_runtime_binding("unsupported_target_kind")
    project_id: UUID | None = None
    if data.level == RuntimeLevel.USER:
        ensure_can_write(principal, "runtime_binding")
        if data.project_id is not None:
            raise _invalid_runtime_binding("unexpected_project")
    elif data.level in (RuntimeLevel.PROJECT_OVERRIDE, RuntimeLevel.PROJECT_DEFAULT):
        ensure_can_write(principal, "runtime_binding")
        if data.project_id is None:
            raise _invalid_runtime_binding("missing_project")
        if await session.get(ProjectModel, data.project_id) is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail={"error_code": "project_not_found"}
            )
        project_id = data.project_id
    else:
        ensure_can_provision(principal, "runtime_binding")
        if data.project_id is not None:
            raise _invalid_runtime_binding("unexpected_project")
    await _checked_target(session, principal, data.target)
    binding = RuntimeBindingModel(
        level=data.level.value,
        owner_user_id=principal.user.id,
        project_id=project_id,
        target_kind=data.target_kind.value,
        target_stable_key=data.target_stable_key,
        target=data.target.model_dump(mode="json"),
    )
    session.add(binding)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"error_code": "already_bound"}
        ) from exc
    await session.refresh(binding)
    return binding


async def get_binding(
    session: AsyncSession, principal: Principal, binding_id: UUID
) -> RuntimeBindingModel | None:
    """`None` for missing and for another user's private binding alike —
    both map to 404, never a leak."""
    binding = await session.get(RuntimeBindingModel, binding_id)
    if binding is None or not _is_visible(principal, binding):
        return None
    return binding


async def list_bindings(
    session: AsyncSession,
    principal: Principal,
    level: RuntimeLevel | None = None,
    project_id: UUID | None = None,
    kind: LibraryKind | None = None,
    stable_key: str | None = None,
) -> list[RuntimeBindingModel]:
    """Private user bindings of others are filtered before exposure, exactly
    like private library resources."""
    conditions = []
    if level is not None:
        conditions.append(RuntimeBindingModel.level == level.value)
    if project_id is not None:
        conditions.append(RuntimeBindingModel.project_id == project_id)
    if kind is not None:
        conditions.append(RuntimeBindingModel.target_kind == kind.value)
    if stable_key is not None:
        conditions.append(RuntimeBindingModel.target_stable_key == stable_key)
    if principal.role != Role.ADMIN:
        conditions.append(
            or_(
                RuntimeBindingModel.level != RuntimeLevel.USER.value,
                RuntimeBindingModel.owner_user_id == principal.user.id,
            )
        )
    stmt = select(RuntimeBindingModel).order_by(RuntimeBindingModel.created_at.asc())
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return list((await session.execute(stmt)).scalars().all())


async def delete_binding(
    session: AsyncSession, principal: Principal, binding: RuntimeBindingModel
) -> RuntimeBinding:
    """Release rules mirror project locks: user level by owner-or-admin,
    shared project levels by creator-or-admin, studio default by provision
    roles. The response is snapshotted before deletion."""
    if binding.level == RuntimeLevel.USER.value:
        ensure_can_write(principal, "runtime_binding")
        if principal.role != Role.ADMIN and binding.owner_user_id != principal.user.id:
            raise forbidden("runtime_binding", "release")
    elif binding.level in (
        RuntimeLevel.PROJECT_OVERRIDE.value,
        RuntimeLevel.PROJECT_DEFAULT.value,
    ):
        ensure_can_write(principal, "runtime_binding")
        if principal.role != Role.ADMIN and binding.owner_user_id != principal.user.id:
            raise forbidden("runtime_binding", "release")
    else:
        ensure_can_provision(principal, "runtime_binding")
    released = RuntimeBinding.model_validate(binding)
    await session.delete(binding)
    await session.commit()
    return released


def to_contract(binding: RuntimeBindingModel) -> RuntimeBinding:
    return RuntimeBinding.model_validate(binding)


async def _stored_choice(
    session: AsyncSession,
    level: RuntimeLevel,
    kind: LibraryKind,
    stable_key: str,
    owner_id: UUID | None = None,
    project_id: UUID | None = None,
) -> RuntimeTarget | None:
    conditions = [
        RuntimeBindingModel.level == level.value,
        RuntimeBindingModel.target_kind == kind.value,
        RuntimeBindingModel.target_stable_key == stable_key,
    ]
    if owner_id is not None:
        conditions.append(RuntimeBindingModel.owner_user_id == owner_id)
    if project_id is not None:
        conditions.append(RuntimeBindingModel.project_id == project_id)
    row = (
        await session.execute(select(RuntimeBindingModel).where(and_(*conditions)))
    ).scalar_one_or_none()
    if row is None:
        return None
    return RuntimeTarget.model_validate(dict(row.target))


async def load_candidates(
    session: AsyncSession,
    principal: Principal,
    keys: list[tuple[LibraryKind, str]],
    project_id: UUID | None = None,
    session_overrides: Mapping[tuple[LibraryKind, str], RuntimeTarget] | None = None,
) -> list[RuntimeCandidate]:
    """Acquisition shared by P4 selection and the P5 engine: validates session
    overrides explicitly (unknown machine 404, another user's machine
    403) and liveness-checks every stored choice (deleted/revoked machine =
    non-live, never a hard error). Pure selection happens downstream via
    `select_runtime` — this function only loads."""

    overrides = dict(session_overrides or {})
    candidates: list[RuntimeCandidate] = []
    for key_kind, key_name in keys:
        candidate = overrides.get((key_kind, key_name))
        if candidate is not None:
            await _checked_target(session, principal, candidate)
            effective = await _effective_target(session, candidate)
            if effective is not None:
                candidates.append(
                    RuntimeCandidate(
                        level=RuntimeLevel.SESSION,
                        kind=key_kind,
                        stable_key=key_name,
                        target=effective,
                        live=True,
                    )
                )
    for level, scoped in (
        (RuntimeLevel.PROJECT_OVERRIDE, True),
        (RuntimeLevel.USER, False),
        (RuntimeLevel.PROJECT_DEFAULT, True),
        (RuntimeLevel.STUDIO_DEFAULT, False),
    ):
        if scoped and project_id is None:
            continue
        for key_kind, key_name in keys:
            if level == RuntimeLevel.USER:
                stored = await _stored_choice(
                    session, level, key_kind, key_name, owner_id=principal.user.id
                )
            elif scoped:
                stored = await _stored_choice(
                    session, level, key_kind, key_name, project_id=project_id
                )
            else:
                stored = await _stored_choice(session, level, key_kind, key_name)
            if stored is not None:
                effective = await _effective_target(session, stored)
                candidates.append(
                    RuntimeCandidate(
                        level=level,
                        kind=key_kind,
                        stable_key=key_name,
                        target=effective if effective is not None else stored,
                        live=effective is not None,
                    )
                )
    return candidates


async def resolve_runtime(
    session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    stable_key: str,
    project_id: UUID | None = None,
    session_overrides: Mapping[tuple[LibraryKind, str], RuntimeTarget] | None = None,
) -> RuntimeResolution:
    """Single deterministic runtime-choice function (P4/DEC-0068).

    Library failures propagate unchanged (`definition_not_found`, never a
    new code). Level order is total: session > project_override > user >
    project_default > studio_default; within a level the agent key wins over
    its linked model profile key. Inaccessible stored choices (deleted or
    revoked machine) fall through instead of erroring. Compatibility is
    always reported, never silenced. Pure read, no LLM, no provider call."""

    def _library_failure() -> HTTPException:
        return HTTPException(
            status.HTTP_404_NOT_FOUND, detail={"error_code": "definition_not_found"}
        )

    try:
        resolved = await library_service.resolve_definition(
            session, principal, kind, stable_key, project_id
        )
    except HTTPException:
        raise _library_failure() from None
    version_row = (
        await session.execute(
            select(LibraryResourceVersionModel).where(
                LibraryResourceVersionModel.resource_id == resolved.resource_id,
                LibraryResourceVersionModel.version == resolved.version,
            )
        )
    ).scalar_one_or_none()
    if version_row is None:
        raise _library_failure()
    profile_key: tuple[LibraryKind, str] | None = None
    requirements = CapabilityRequirement()
    link_rows = (
        (
            await session.execute(
                select(LibraryResourceLinkModel).where(
                    LibraryResourceLinkModel.from_version_id == version_row.id,
                    LibraryResourceLinkModel.relation
                    == BindingRelation.REQUIRES_MODEL_PROFILE.value,
                )
            )
        )
        .scalars()
        .all()
    )
    if link_rows:
        profile_resource = await session.get(LibraryResourceModel, link_rows[0].to_resource_id)
        if profile_resource is None:
            raise _library_failure()
        profile_version = (
            await session.execute(
                select(LibraryResourceVersionModel).where(
                    LibraryResourceVersionModel.resource_id == profile_resource.id,
                    LibraryResourceVersionModel.version == link_rows[0].to_version,
                )
            )
        ).scalar_one_or_none()
        if profile_version is None:
            raise _library_failure()
        profile_key = (LibraryKind(profile_resource.kind), profile_resource.stable_key)
        requirements = CapabilityRequirement.model_validate(
            dict(profile_version.content.get("requirements", {}))
        )
    keys = [(kind, stable_key)] + ([profile_key] if profile_key is not None else [])
    candidates = await load_candidates(session, principal, keys, project_id, session_overrides)
    try:
        winner = select_runtime(candidates, (kind, stable_key), profile_key)
    except ResolutionFailure as failure:
        # Unreachable via `load_candidates` (one row per key, session dict
        # keys unique): duplicate live candidates would mean a broken
        # uniqueness invariant, never a caller error — fail loud, not silent.
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "runtime_resolution_failed"},
        ) from failure
    if winner is not None:
        return _verdict(
            resolved,
            winner.target,
            winner.level,
            winner.kind,
            winner.stable_key,
            requirements,
        )
    return RuntimeResolution(
        target=None,
        level=None,
        matched_kind=None,
        matched_stable_key=None,
        resource_id=resolved.resource_id,
        version=resolved.version,
        compatible=True,
        unsatisfied=[],
    )


def _verdict(
    resolved: LibraryResolution,
    target: RuntimeTarget,
    level: RuntimeLevel,
    matched_kind: LibraryKind,
    matched_key: str,
    requirements: CapabilityRequirement,
) -> RuntimeResolution:
    capabilities = target.capabilities or RuntimeCapabilities()
    unsatisfied = check_compatibility(requirements, capabilities)
    return RuntimeResolution(
        target=target,
        level=level,
        matched_kind=matched_kind,
        matched_stable_key=matched_key,
        resource_id=resolved.resource_id,
        version=resolved.version,
        compatible=not unsatisfied,
        unsatisfied=unsatisfied,
    )
