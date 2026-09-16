from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.events import EventCreate, EventType
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryLockCreate,
    LibraryProjectLock,
    LibraryResolution,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersion,
    LibraryVersionCreate,
    VersionOrigin,
)

from studio_api.db.models.library import (
    LibraryProjectLockModel,
    LibraryResourceLinkModel,
    LibraryResourceModel,
    LibraryResourceVersionModel,
)
from studio_api.db.models.project import ProjectModel
from studio_api.services import events as events_service
from studio_api.services.authz import (
    Principal,
    ensure_can_provision,
    ensure_can_write,
    forbidden,
)

_LIBRARY_EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "studio-os:library")


def _can_read(principal: Principal, resource: LibraryResourceModel) -> bool:
    """Studio/Project definitions are shared reads; User definitions are
    owner-or-admin only (DEC-0063)."""
    if resource.scope != "user":
        return True
    return principal.role == Role.ADMIN or resource.owner_user_id == principal.user.id


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "library resource not found")


async def get_resource(
    session: AsyncSession, principal: Principal, resource_id: UUID
) -> LibraryResourceModel | None:
    """Returns `None` for a missing row and for a User-scope row the caller
    may not see — both map to 404 so no surface leaks another user's
    private existence (DEC-0063 precision 1)."""
    resource = await session.get(LibraryResourceModel, resource_id)
    if resource is None or not _can_read(principal, resource):
        return None
    return resource


async def list_resources(
    session: AsyncSession,
    principal: Principal,
    kind: str | None = None,
    scope: str | None = None,
    project_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[LibraryResourceModel]:
    """Collection filters apply before exposure: another user's private rows
    are never counted, listed, or hinted at (DEC-0063 precision 1)."""
    conditions = []
    if kind is not None:
        conditions.append(LibraryResourceModel.kind == kind)
    if scope is not None:
        conditions.append(LibraryResourceModel.scope == scope)
    if project_id is not None:
        conditions.append(LibraryResourceModel.project_id == project_id)
    if principal.role != Role.ADMIN:
        conditions.append(
            or_(
                LibraryResourceModel.scope != "user",
                LibraryResourceModel.owner_user_id == principal.user.id,
            )
        )
    stmt = (
        select(LibraryResourceModel)
        .order_by(LibraryResourceModel.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    if conditions:
        stmt = stmt.where(and_(*conditions))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _resolve_pin(
    session: AsyncSession, principal: Principal, pin: DependencyPin
) -> LibraryResourceModel:
    """A pin names `(kind, stable_key)`; it must resolve to exactly one
    resource visible to the caller, otherwise the dependency is ambiguous
    (409) or unknown (404, same shape as missing — never a leak)."""
    stmt = select(LibraryResourceModel).where(
        LibraryResourceModel.kind == pin.kind.value,
        LibraryResourceModel.stable_key == pin.stable_key,
    )
    rows = (await session.execute(stmt)).scalars().all()
    candidates = [r for r in rows if _can_read(principal, r)]
    if not candidates:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "pin_not_found", "stable_key": pin.stable_key},
        )
    if len(candidates) > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "pin_ambiguous", "stable_key": pin.stable_key},
        )
    return candidates[0]


async def _version_row(
    session: AsyncSession, resource_id: UUID, version: int
) -> LibraryResourceVersionModel | None:
    stmt = select(LibraryResourceVersionModel).where(
        LibraryResourceVersionModel.resource_id == resource_id,
        LibraryResourceVersionModel.version == version,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _create_version_row(
    session: AsyncSession,
    principal: Principal,
    resource: LibraryResourceModel,
    version: int,
    title: str,
    description: str | None,
    content: dict[str, Any],
    dependencies: list[DependencyPin],
) -> LibraryResourceVersionModel:
    version_row = LibraryResourceVersionModel(
        resource_id=resource.id,
        version=version,
        title=title,
        description=description,
        content=dict(content),
        created_by_user_id=principal.user.id,
    )
    session.add(version_row)
    await session.flush()
    for pin in dependencies:
        target = await _resolve_pin(session, principal, pin)
        target_version = await _version_row(session, target.id, pin.version)
        if target_version is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={"error_code": "pin_version_not_found", "stable_key": pin.stable_key},
            )
        session.add(
            LibraryResourceLinkModel(
                from_version_id=version_row.id,
                to_resource_id=target.id,
                to_version=pin.version,
            )
        )
    return version_row


async def _emit_library_event(
    session: AsyncSession,
    principal: Principal,
    event_type: EventType,
    resource: LibraryResourceModel,
    ref: str,
    extra: dict[str, object] | None = None,
) -> None:
    """Server-internal traceability (gate decision): `events` and
    `ai_work_logs` require a non-null `project_id`, so only project-scoped
    resources emit `library.*` events. Studio/User mutations stay auditable
    through the immutable version rows (`created_by_user_id`, `created_at`)
    plus the agent's explicit AIWorkLog (existing task cycle).

    `ref` makes the deterministic `event_id` unique per action: a
    release/re-lock cycle on the same `(resource, version)` must emit again,
    never be swallowed by `create_event`'s get-or-create."""
    if resource.project_id is None:
        return
    await events_service.create_event(
        session,
        EventCreate(
            event_id=uuid.uuid5(
                _LIBRARY_EVENT_NAMESPACE, f"{resource.id}:{event_type.value}:{ref}"
            ),
            event_type=event_type,
            project_id=resource.project_id,
            task_id=None,
            machine_id=principal.machine.id,
            actor_type="user",
            actor_id=principal.user.id,
            client_timestamp=datetime.now(UTC),
            payload={
                "resource_id": str(resource.id),
                "kind": resource.kind,
                "stable_key": resource.stable_key,
                "scope": resource.scope,
                "ref": ref,
                **(extra or {}),
            },
        ),
    )


def _ensure_owner_or_admin(principal: Principal, resource: LibraryResourceModel) -> None:
    ensure_can_write(principal, "library")
    if principal.role == Role.ADMIN:
        return
    if resource.owner_user_id != principal.user.id:
        raise forbidden("library", "write")


async def create_resource(
    session: AsyncSession, principal: Principal, data: LibraryResourceCreate
) -> tuple[LibraryResourceModel, LibraryResourceVersionModel]:
    """Creates the resource row plus draft version 1 (which never activates
    itself — DEC-0064 precision 3)."""
    owner_id: UUID | None = None
    project_id: UUID | None = None
    if data.scope.value == "studio":
        ensure_can_provision(principal, "library")
        if data.project_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "invalid_scope_context"},
            )
    elif data.scope.value == "project":
        ensure_can_write(principal, "library")
        if data.project_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "invalid_scope_context"},
            )
        if await session.get(ProjectModel, data.project_id) is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail={"error_code": "project_not_found"}
            )
        project_id = data.project_id
    else:
        ensure_can_write(principal, "library")
        if data.project_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "invalid_scope_context"},
            )
    # The creator owns the row in every scope (DEC-0063): for User scope it
    # also gates reads, for Studio/Project scopes it gates mutations while
    # reads stay shared.
    owner_id = principal.user.id

    resource = LibraryResourceModel(
        kind=data.kind.value,
        stable_key=data.stable_key,
        scope=data.scope.value,
        status="draft",
        active_version=0,
        owner_user_id=owner_id,
        project_id=project_id,
        created_by_user_id=principal.user.id,
    )
    session.add(resource)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"error_code": "duplicate_stable_key"}
        ) from exc
    version_row = await _create_version_row(
        session,
        principal,
        resource,
        1,
        data.title,
        data.description,
        data.content,
        data.dependencies,
    )
    await session.commit()
    await session.refresh(resource)
    await _emit_library_event(
        session,
        principal,
        EventType.LIBRARY_VERSION_CREATED,
        resource,
        "v1",
        {"version": 1},
    )
    return resource, version_row


async def create_resource_version(
    session: AsyncSession,
    principal: Principal,
    resource: LibraryResourceModel,
    data: LibraryVersionCreate,
) -> LibraryResourceVersionModel:
    """Adds draft version N+1. The resource row is locked (`FOR UPDATE`) so
    two concurrent creators serialize instead of colliding on the
    `(resource_id, version)` unique constraint."""
    _ensure_owner_or_admin(principal, resource)
    locked = (
        await session.execute(
            select(LibraryResourceModel)
            .where(LibraryResourceModel.id == resource.id)
            .with_for_update()
        )
    ).scalar_one()
    max_version = (
        await session.execute(
            select(func.max(LibraryResourceVersionModel.version)).where(
                LibraryResourceVersionModel.resource_id == locked.id
            )
        )
    ).scalar_one()
    next_version = int(max_version or 0) + 1
    version_row = await _create_version_row(
        session,
        principal,
        locked,
        next_version,
        data.title,
        data.description,
        data.content,
        data.dependencies,
    )
    locked.version += 1
    await session.commit()
    await session.refresh(version_row)
    await _emit_library_event(
        session,
        principal,
        EventType.LIBRARY_VERSION_CREATED,
        locked,
        f"v{next_version}",
        {"version": next_version},
    )
    return version_row


async def activate_resource_version(
    session: AsyncSession,
    principal: Principal,
    resource: LibraryResourceModel,
    version: int,
    expected_resource_version: int,
) -> LibraryResourceModel:
    """Explicit activation (DEC-0064 precision 3). Reactivating the already
    active version is a successful no-op."""
    _ensure_owner_or_admin(principal, resource)
    if resource.version != expected_resource_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "version_conflict", "server_version": resource.version},
        )
    if await _version_row(session, resource.id, version) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error_code": "version_not_found"})
    if resource.active_version != version or resource.status != "active":
        resource.active_version = version
        resource.status = "active"
        resource.version += 1
        await session.commit()
        await session.refresh(resource)
        await _emit_library_event(
            session,
            principal,
            EventType.LIBRARY_VERSION_ACTIVATED,
            resource,
            f"v{version}",
            {"version": version},
        )
    return resource


async def deprecate_resource(
    session: AsyncSession,
    principal: Principal,
    resource: LibraryResourceModel,
    expected_resource_version: int,
) -> LibraryResourceModel:
    """Deprecation replaces deletion: the row and its history stay, only the
    status flips. Already deprecated is a successful no-op."""
    _ensure_owner_or_admin(principal, resource)
    if resource.version != expected_resource_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "version_conflict", "server_version": resource.version},
        )
    if resource.status != "deprecated":
        resource.status = "deprecated"
        resource.version += 1
        await session.commit()
        await session.refresh(resource)
        await _emit_library_event(
            session,
            principal,
            EventType.LIBRARY_RESOURCE_DEPRECATED,
            resource,
            f"v{resource.active_version}",
            {"version": resource.active_version},
        )
    return resource


async def list_versions(
    session: AsyncSession, resource_id: UUID
) -> list[LibraryResourceVersionModel]:
    stmt = (
        select(LibraryResourceVersionModel)
        .where(LibraryResourceVersionModel.resource_id == resource_id)
        .order_by(LibraryResourceVersionModel.version.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_lock(session: AsyncSession, lock_id: UUID) -> LibraryProjectLockModel | None:
    return await session.get(LibraryProjectLockModel, lock_id)


async def version_detail(
    session: AsyncSession, version_row: LibraryResourceVersionModel
) -> LibraryVersion:
    """Assembles the contract with its pinned dependencies resolved back to
    `(kind, stable_key, version)` (DEC-0064: no duplicated content, pins
    only)."""
    stmt = select(LibraryResourceLinkModel).where(
        LibraryResourceLinkModel.from_version_id == version_row.id
    )
    pins: list[DependencyPin] = []
    for link in (await session.execute(stmt)).scalars().all():
        target = await session.get(LibraryResourceModel, link.to_resource_id)
        if target is None:  # pragma: no cover - FK guarantees presence
            continue
        pins.append(
            DependencyPin(
                kind=LibraryKind(target.kind),
                stable_key=target.stable_key,
                version=link.to_version,
            )
        )
    return LibraryVersion(
        id=version_row.id,
        resource_id=version_row.resource_id,
        version=version_row.version,
        title=version_row.title,
        description=version_row.description,
        content=dict(version_row.content),
        dependencies=pins,
        created_by_user_id=version_row.created_by_user_id,
        created_at=version_row.created_at,
    )


async def list_locks(
    session: AsyncSession, principal: Principal, project_id: UUID | None = None
) -> list[LibraryProjectLockModel]:
    """Reads stay fully available, including to `readonly` (TECH/04): no
    write gate here. Locks on another user's private resources are filtered
    out like the resources themselves (DEC-0063 precision 1)."""
    stmt = select(LibraryProjectLockModel).join(
        LibraryResourceModel,
        LibraryProjectLockModel.resource_id == LibraryResourceModel.id,
    )
    if project_id is not None:
        stmt = stmt.where(LibraryProjectLockModel.project_id == project_id)
    if principal.role != Role.ADMIN:
        stmt = stmt.where(
            or_(
                LibraryResourceModel.scope != "user",
                LibraryResourceModel.owner_user_id == principal.user.id,
            )
        )
    return list((await session.execute(stmt)).scalars().all())


async def set_lock(
    session: AsyncSession, principal: Principal, data: LibraryLockCreate
) -> LibraryProjectLockModel:
    ensure_can_write(principal, "library")
    if await session.get(ProjectModel, data.project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"error_code": "project_not_found"})
    resource = await session.get(LibraryResourceModel, data.resource_id)
    if resource is None or not _can_read(principal, resource):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail={"error_code": "lock_target_not_found"}
        )
    if await _version_row(session, resource.id, data.locked_version) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail={"error_code": "pin_version_not_found"}
        )
    existing = (
        await session.execute(
            select(LibraryProjectLockModel).where(
                LibraryProjectLockModel.project_id == data.project_id,
                LibraryProjectLockModel.resource_id == data.resource_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"error_code": "already_locked"})
    lock = LibraryProjectLockModel(
        project_id=data.project_id,
        resource_id=data.resource_id,
        locked_version=data.locked_version,
        created_by_user_id=principal.user.id,
    )
    session.add(lock)
    await session.commit()
    await session.refresh(lock)
    await _emit_library_event(
        session,
        principal,
        EventType.LIBRARY_LOCK_SET,
        resource,
        f"lock:{lock.id}",
        {
            "lock_id": str(lock.id),
            "project_id": str(data.project_id),
            "locked_version": data.locked_version,
        },
    )
    return lock


async def release_lock(
    session: AsyncSession, principal: Principal, lock: LibraryProjectLockModel
) -> LibraryProjectLock:
    """Release by the creating user or an admin (claims pattern). The
    response contract is snapshotted before deletion: reading attributes
    off a deleted, committed row would fail on session expiry."""
    ensure_can_write(principal, "library")
    if principal.role != Role.ADMIN and lock.created_by_user_id != principal.user.id:
        raise forbidden("library", "release")
    released = LibraryProjectLock.model_validate(lock)
    resource = await session.get(LibraryResourceModel, lock.resource_id)
    lock_id = lock.id
    lock_project_id = lock.project_id
    locked_version = lock.locked_version
    await session.delete(lock)
    await session.commit()
    if resource is not None:
        await _emit_library_event(
            session,
            principal,
            EventType.LIBRARY_LOCK_RELEASED,
            resource,
            f"lock:{lock_id}:released",
            {
                "lock_id": str(lock_id),
                "project_id": str(lock_project_id),
                "locked_version": locked_version,
            },
        )
    return released


_SCOPE_RANK = {"user": 0, "project": 1, "studio": 2}


class _Unresolvable(Exception):
    """Internal diagnostic only, never serialized to a caller: every case
    maps to the single public 404 `definition_not_found`, so an invisible
    resource stays indistinguishable from a missing one."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _definition_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail={"error_code": "definition_not_found"})


async def resolve_definition(
    session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    stable_key: str,
    project_id: UUID | None = None,
) -> LibraryResolution:
    """Deterministic scope resolution (DEC-0065): filter visible candidates
    first, then shadow `User > Project(project_id) > Studio`, then pick the
    effective version (project lock, else active). Pure read: open to every
    authenticated role, and identical inputs always yield identical outputs.
    No endpoint exposes this in P2."""
    try:
        return await _resolve_inner(session, principal, kind, stable_key, project_id)
    except _Unresolvable:
        raise _definition_not_found() from None


async def _resolve_inner(
    session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    stable_key: str,
    project_id: UUID | None,
) -> LibraryResolution:
    stmt = select(LibraryResourceModel).where(
        LibraryResourceModel.kind == kind.value,
        LibraryResourceModel.stable_key == stable_key,
    )
    if project_id is not None:
        stmt = stmt.where(
            or_(
                LibraryResourceModel.scope != "project",
                LibraryResourceModel.project_id == project_id,
            )
        )
    else:
        stmt = stmt.where(LibraryResourceModel.scope != "project")
    rows = (await session.execute(stmt)).scalars().all()
    visible = sorted(
        (r for r in rows if r.scope in _SCOPE_RANK and _can_read(principal, r)),
        key=lambda r: _SCOPE_RANK[r.scope],
    )
    if not visible:
        raise _Unresolvable("missing_or_invisible_definition")
    effective = visible[0]

    origin = VersionOrigin.ACTIVE
    version_number = effective.active_version
    if project_id is not None:
        lock_stmt = select(LibraryProjectLockModel).where(
            LibraryProjectLockModel.project_id == project_id,
            LibraryProjectLockModel.resource_id == effective.id,
        )
        lock = (await session.execute(lock_stmt)).scalar_one_or_none()
        if lock is not None:
            version_number = lock.locked_version
            origin = VersionOrigin.LOCK
    if version_number <= 0:
        raise _Unresolvable("no_usable_version")
    target = await _version_row(session, effective.id, version_number)
    if target is None:
        raise _Unresolvable("no_usable_version")

    link_stmt = select(LibraryResourceLinkModel).where(
        LibraryResourceLinkModel.from_version_id == target.id
    )
    for link in (await session.execute(link_stmt)).scalars().all():
        dependency = await session.get(LibraryResourceModel, link.to_resource_id)
        if dependency is None or not _can_read(principal, dependency):
            raise _Unresolvable("unresolvable_dependency")
        if await _version_row(session, dependency.id, link.to_version) is None:
            raise _Unresolvable("unresolvable_dependency")

    return LibraryResolution(
        resource_id=effective.id,
        kind=kind,
        stable_key=effective.stable_key,
        scope=LibraryScope(effective.scope),
        version=version_number,
        version_origin=origin,
        deprecated=(effective.status == "deprecated"),
    )
