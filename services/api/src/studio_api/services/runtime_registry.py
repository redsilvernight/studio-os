from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.library import RuntimeCapabilities
from studio_contracts.runtime import (
    CapabilitySource,
    RuntimeRegistration,
    RuntimeRegistrationCreate,
    RuntimeRegistrationUpdate,
    RuntimeStatus,
)

from studio_api.db.models.machine import MachineModel
from studio_api.db.models.runtime import RuntimeModel
from studio_api.services.authz import (
    Principal,
    ensure_can_write,
    forbidden,
)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "runtime not found")


async def _checked_machine(
    session: AsyncSession, principal: Principal, machine_id: UUID | None
) -> None:
    """Fail-closed machine gate (same shape as P4 bindings): unknown machine
    is 404, another user's machine is 403 — a caller may only ever attach a
    runtime to a machine they own. `None` (remote/cloud runtime) needs no
    check: one abstraction, no per-locus branch."""
    if machine_id is None:
        return
    machine = await session.get(MachineModel, machine_id)
    if machine is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail={"error_code": "runtime_target_not_found"}
        )
    if machine.owner_user_id != principal.user.id:
        raise forbidden("runtime", "attach")


def _is_visible(principal: Principal, runtime: RuntimeModel) -> bool:
    """Runtimes are always per-user private (no shared levels in P6):
    owner-or-admin, 404-masked otherwise — same filter-first shape as `user`
    runtime bindings and private library resources."""
    return principal.role == Role.ADMIN or runtime.owner_user_id == principal.user.id


def to_contract(runtime: RuntimeModel) -> RuntimeRegistration:
    return RuntimeRegistration(
        id=runtime.id,
        owner_user_id=runtime.owner_user_id,
        machine_id=runtime.machine_id,
        harness_ref=runtime.harness_ref,
        provider_ref=runtime.provider_ref,
        model_ref=runtime.model_ref,
        capabilities=RuntimeCapabilities.model_validate(dict(runtime.capabilities or {})),
        capability_source=CapabilitySource(runtime.capability_source),
        runtime_metadata=dict(runtime.runtime_metadata or {}),
        status=RuntimeStatus(runtime.status),
        created_at=runtime.created_at,
        updated_at=runtime.updated_at,
    )


async def register_runtime(
    session: AsyncSession, principal: Principal, data: RuntimeRegistrationCreate
) -> RuntimeModel:
    """Declares one runtime. The owner is always the caller (server-derived,
    never client-supplied); an attached machine must exist and be owned by
    the caller. No secret can be persisted: the contract rejects secret
    metadata keys before this runs, and no credential column exists."""
    ensure_can_write(principal, "runtime")
    await _checked_machine(session, principal, data.machine_id)
    runtime = RuntimeModel(
        owner_user_id=principal.user.id,
        machine_id=data.machine_id,
        harness_ref=data.harness_ref,
        provider_ref=data.provider_ref,
        model_ref=data.model_ref,
        capabilities=data.capabilities.model_dump(mode="json"),
        capability_source=data.capability_source.value,
        runtime_metadata=dict(data.runtime_metadata),
        status=RuntimeStatus.ACTIVE.value,
    )
    session.add(runtime)
    await session.commit()
    await session.refresh(runtime)
    return runtime


async def get_runtime(
    session: AsyncSession, principal: Principal, runtime_id: UUID
) -> RuntimeModel | None:
    """`None` for missing, revoked-or-active alike readable, and for another
    user's runtime alike — the last two map to 404, never a leak. Revoked
    rows stay readable so callers can diagnose a dangling binding."""
    runtime = await session.get(RuntimeModel, runtime_id)
    if runtime is None or not _is_visible(principal, runtime):
        return None
    return runtime


async def list_runtimes(
    session: AsyncSession,
    principal: Principal,
    *,
    status: RuntimeStatus | None = None,
    include_revoked: bool = False,
) -> list[RuntimeModel]:
    """Owner filter-first (admins see all, like private library resources).
    Revoked rows are excluded by default — pass `include_revoked` (or a
    `status` filter) to audit them."""
    conditions = []
    if principal.role != Role.ADMIN:
        conditions.append(RuntimeModel.owner_user_id == principal.user.id)
    if status is not None:
        conditions.append(RuntimeModel.status == status.value)
    elif not include_revoked:
        conditions.append(RuntimeModel.status == RuntimeStatus.ACTIVE.value)
    stmt = select(RuntimeModel).order_by(RuntimeModel.created_at.asc())
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return list((await session.execute(stmt)).scalars().all())


async def update_runtime(
    session: AsyncSession,
    principal: Principal,
    runtime: RuntimeModel,
    data: RuntimeRegistrationUpdate,
    expected_version: int,
) -> RuntimeModel:
    """Mutates descriptors without rotating identity (`id` is stable;
    capability/ref changes never fork a new runtime). Owner-or-admin only.
    Optimistic concurrency (DB rule): a stale `expected_version` fails with
    409 `version_conflict` carrying the server version, never a silent
    overwrite. Re-attaching a machine re-runs the ownership gate;
    `detach_machine` drops the locus (remote/cloud shape) — an explicit
    flag, because an omitted field (`None`) means "leave untouched", not
    "detach". A fully unanchored row (no machine, no refs left) is rejected
    fail-closed."""
    ensure_can_write(principal, "runtime")
    if principal.role != Role.ADMIN and runtime.owner_user_id != principal.user.id:
        raise forbidden("runtime", "update")
    if runtime.version != expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "version_conflict", "server_version": runtime.version},
        )
    if data.detach_machine:
        runtime.machine_id = None
    if data.machine_id is not None:
        await _checked_machine(session, principal, data.machine_id)
        runtime.machine_id = data.machine_id
    for field in ("harness_ref", "provider_ref", "model_ref"):
        value = getattr(data, field)
        if value is not None:
            setattr(runtime, field, value)
    if data.capabilities is not None:
        runtime.capabilities = data.capabilities.model_dump(mode="json")
    if data.runtime_metadata is not None:
        runtime.runtime_metadata = dict(data.runtime_metadata)
    if (
        runtime.machine_id is None
        and runtime.harness_ref is None
        and runtime.provider_ref is None
        and runtime.model_ref is None
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error_code": "invalid_runtime", "reason": "no_anchor_left"},
        )
    runtime.version += 1
    await session.commit()
    await session.refresh(runtime)
    return runtime


async def revoke_runtime(
    session: AsyncSession, principal: Principal, runtime: RuntimeModel
) -> RuntimeModel:
    """Logical revocation (idempotent): the row stays readable but resolves
    as non-live, so bindings toward it fall through instead of silently
    retargeting. Owner-or-admin only. No physical delete exists — history is
    provenance."""
    ensure_can_write(principal, "runtime")
    if principal.role != Role.ADMIN and runtime.owner_user_id != principal.user.id:
        raise forbidden("runtime", "revoke")
    runtime.status = RuntimeStatus.REVOKED.value
    await session.commit()
    await session.refresh(runtime)
    return runtime


async def resolve_effective_target(
    session: AsyncSession, runtime_id: UUID
) -> tuple[RuntimeModel | None, bool]:
    """Acquisition helper for P4 bindings: returns `(row, live)` — `live`
    folds the registry status AND the attached machine liveness (deleted or
    credential-revoked machine = non-live, reusing the Machine
    infrastructure instead of building monitoring). `(None, False)` for a
    missing row. Ownership is checked by the caller (`runtime_bindings`),
    which owns the 403 shape."""
    runtime = await session.get(RuntimeModel, runtime_id)
    if runtime is None or runtime.status != RuntimeStatus.ACTIVE.value:
        return None, False
    if runtime.machine_id is not None:
        machine = await session.get(MachineModel, runtime.machine_id)
        if machine is None or machine.credential_revoked_at is not None:
            return None, False
    return runtime, True
