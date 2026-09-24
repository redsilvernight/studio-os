from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.events import EventCreate, EventType
from studio_contracts.library import (
    BindingRelation,
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
    binding_relation_for,
    binding_scope_allows,
    content_validation_errors,
    workflow_validation_errors,
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
    ALL_PROJECTS,
    Principal,
    ProjectAction,
    ensure_can_provision,
    ensure_can_write,
    ensure_project_access,
    ensure_shared_access,
    forbidden,
    has_any_project,
    has_project_access,
)

_LIBRARY_EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "studio-os:library")


def _can_read(principal: Principal, resource: LibraryResourceModel) -> bool:
    """User definitions are owner-or-admin only (DEC-0063); Project ones
    follow their project, Studio ones need at least one project (DEC-0100
    §4/§11, composed by AND)."""
    if resource.scope == "user":
        return principal.role == Role.ADMIN or resource.owner_user_id == principal.user.id
    if resource.project_id is not None:
        return has_project_access(principal, resource.project_id)
    return has_any_project(principal)


def _ensure_scope_access(
    principal: Principal, project_id: UUID | None, is_user_scope: bool, action: ProjectAction
) -> None:
    if is_user_scope:
        return
    if project_id is not None:
        ensure_project_access(principal, project_id, action)
    else:
        ensure_shared_access(principal, action)


def ensure_resource_scope(
    principal: Principal, resource: LibraryResourceModel, action: ProjectAction = "read"
) -> None:
    """Project level of a definition, checked before the User-scope 404
    masking (DEC-0100 §8): Project scope needs its project, Studio scope
    at least one project; User scope keeps its owner-or-admin rule."""
    _ensure_scope_access(principal, resource.project_id, resource.scope == "user", action)


def _read_clause(principal: Principal) -> ColumnElement[bool] | None:
    """SQL twin of `_can_read`; `None` means no filter (admin)."""
    if principal.role == Role.ADMIN:
        return None
    own = and_(
        LibraryResourceModel.scope == "user",
        LibraryResourceModel.owner_user_id == principal.user.id,
    )
    scope = principal.project_scope
    if scope is ALL_PROJECTS:
        return or_(own, LibraryResourceModel.scope != "user")
    if not scope:
        return own
    return or_(
        own,
        and_(LibraryResourceModel.scope == "project", LibraryResourceModel.project_id.in_(scope)),
        LibraryResourceModel.scope == "studio",
    )


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "library resource not found")


async def get_resource(
    session: AsyncSession, principal: Principal, resource_id: UUID
) -> LibraryResourceModel | None:
    """Returns `None` for a missing row and for a User-scope row the caller
    may not see — both map to 404 so no surface leaks another user's
    private existence (DEC-0063 precision 1). A definition of an
    inaccessible project answers 403 first (DEC-0100 §8)."""
    resource = await session.get(LibraryResourceModel, resource_id)
    if resource is None:
        return None
    ensure_resource_scope(principal, resource)
    if not _can_read(principal, resource):
        return None
    return resource


async def find_readable_resource(
    session: AsyncSession, principal: Principal, resource_id: UUID
) -> LibraryResourceModel | None:
    """Resolution lookup: every unreadable row, whatever the reason, is
    masked as missing so resolution keeps its single public 404."""
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
        ensure_project_access(principal, project_id)
        conditions.append(LibraryResourceModel.project_id == project_id)
    if (visible := _read_clause(principal)) is not None:
        conditions.append(visible)
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


async def get_version(
    session: AsyncSession, resource_id: UUID, version: int
) -> LibraryResourceVersionModel | None:
    """Public single-version read for consumers that already hold a resolved
    `(resource_id, version)` (e.g. project context selection) and must not
    load every version of the resource."""
    return await _version_row(session, resource_id, version)


def _invalid_binding(reason: str) -> HTTPException:
    """422 for a structurally invalid Library Binding (P5/DEC-0067).

    Only ever raised after the pin resolved to an existing, visible target
    at an existing version — so it never leaks another user's private
    existence (that stays 404 `pin_not_found`)."""
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error_code": "invalid_binding", "reason": reason},
    )


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
    # P3/DEC-0066: per-kind semantic validation, applied identically to the
    # initial version and every later one. Both callers (`create_resource`,
    # `create_resource_version`) enforce scope/ownership gates before reaching
    # this point, so a 422 here only ever describes the caller's own payload
    # — validation is never an oracle over invisible resources.
    content_errors = content_validation_errors(LibraryKind(resource.kind), dict(content))
    if content_errors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error_code": "invalid_content", "details": content_errors},
        )
    # P11/DEC-0075: static workflow-definition validation, on the submitted
    # content and dependency list only (duplicate participants, unknown/cyclic
    # dependencies, participant agent agreement, static dataflow references).
    # Purely structural, so it runs before any pin lookup and is never an
    # existence oracle; a workflow version is stored only when it is coherent.
    if LibraryKind(resource.kind) == LibraryKind.WORKFLOW:
        workflow_errors = workflow_validation_errors(dict(content), dependencies)
        if workflow_errors:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "invalid_workflow", **workflow_errors[0]},
            )
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
    # P5/DEC-0067: Library Binding validation, after existence/visibility
    # gates (404/409 above) so a 422 only ever describes visible resources.
    source_kind = LibraryKind(resource.kind)
    seen_targets: set[UUID] = set()
    model_profile_count = 0
    for pin in dependencies:
        target = await _resolve_pin(session, principal, pin)
        target_version = await _version_row(session, target.id, pin.version)
        if target_version is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={"error_code": "pin_version_not_found", "stable_key": pin.stable_key},
            )
        expected = binding_relation_for(source_kind, LibraryKind(target.kind))
        if expected is None:
            raise _invalid_binding("forbidden_kind_pair")
        if pin.relation is not None and pin.relation != expected:
            raise _invalid_binding("relation_mismatch")
        if expected == BindingRelation.REQUIRES_MODEL_PROFILE:
            model_profile_count += 1
            if model_profile_count > 1:
                raise _invalid_binding("too_many_model_profiles")
        if target.id in seen_targets:
            raise _invalid_binding("duplicate_binding")
        seen_targets.add(target.id)
        if not binding_scope_allows(
            LibraryScope(resource.scope),
            resource.owner_user_id,
            LibraryScope(target.scope),
            target.owner_user_id,
        ):
            raise _invalid_binding("forbidden_scope")
        session.add(
            LibraryResourceLinkModel(
                from_version_id=version_row.id,
                to_resource_id=target.id,
                to_version=pin.version,
                relation=expected.value,
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


def authorize_write(principal: Principal, resource: LibraryResourceModel) -> None:
    """Project then role check of a definition mutation, run ahead of the
    idempotency replay short-circuit (DEC-0036, DEC-0100 §12)."""
    ensure_resource_scope(principal, resource, "write")
    ensure_can_write(principal, "library")


def authorize_create(principal: Principal, scope: str, project_id: UUID | None) -> None:
    """Project (or shared-data) then role check of a definition creation,
    run ahead of the idempotency replay short-circuit."""
    _ensure_scope_access(principal, project_id, scope == "user", "write")
    if scope == "studio":
        ensure_can_provision(principal, "library")
    else:
        ensure_can_write(principal, "library")


def _ensure_owner_or_admin(principal: Principal, resource: LibraryResourceModel) -> None:
    authorize_write(principal, resource)
    if principal.role == Role.ADMIN:
        return
    if resource.owner_user_id != principal.user.id:
        raise forbidden("library", "write")


async def create_resource(
    session: AsyncSession, principal: Principal, data: LibraryResourceCreate
) -> tuple[LibraryResourceModel, LibraryResourceVersionModel]:
    """Creates the resource row plus draft version 1 (which never activates
    itself — DEC-0064 precision 3)."""
    authorize_create(principal, data.scope.value, data.project_id)
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
    try:
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
    except HTTPException:
        # Atomicity (P5/DEC-0067): a rejected pin/binding must leave neither
        # a partial version row nor partial links behind, whatever the
        # caller's session lifecycle is.
        await session.rollback()
        raise
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
    try:
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
    except HTTPException:
        # Same atomicity as `create_resource`: no partial version/links.
        await session.rollback()
        raise
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
                relation=BindingRelation(link.relation),
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
    """Open to `readonly` (TECH/04): no write gate here. A lock follows its
    project (DEC-0100 §11) and locks on unreadable resources are filtered
    out like the resources themselves (DEC-0063 precision 1)."""
    stmt = select(LibraryProjectLockModel).join(
        LibraryResourceModel,
        LibraryProjectLockModel.resource_id == LibraryResourceModel.id,
    )
    if project_id is not None:
        ensure_project_access(principal, project_id)
        stmt = stmt.where(LibraryProjectLockModel.project_id == project_id)
    elif principal.project_scope is not ALL_PROJECTS:
        stmt = stmt.where(LibraryProjectLockModel.project_id.in_(principal.project_scope))
    if (visible := _read_clause(principal)) is not None:
        stmt = stmt.where(visible)
    return list((await session.execute(stmt)).scalars().all())


async def set_lock(
    session: AsyncSession, principal: Principal, data: LibraryLockCreate
) -> LibraryProjectLockModel:
    authorize_lock(principal, data.project_id)
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


def authorize_lock(principal: Principal, project_id: UUID) -> None:
    """Project then role check of a lock creation, run ahead of the
    idempotency replay short-circuit (DEC-0036, DEC-0100 §12)."""
    ensure_project_access(principal, project_id, "write")
    ensure_can_write(principal, "library")


async def release_lock(
    session: AsyncSession, principal: Principal, lock: LibraryProjectLockModel
) -> LibraryProjectLock:
    """Release by the creating user or an admin (claims pattern). The
    response contract is snapshotted before deletion: reading attributes
    off a deleted, committed row would fail on session expiry."""
    ensure_project_access(principal, lock.project_id, "write")
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
    No endpoint exposes this in P2. An inaccessible `project_id` answers
    403 before any read (DEC-0100 §10)."""
    if project_id is not None:
        ensure_project_access(principal, project_id)
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
