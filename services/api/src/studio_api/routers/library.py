from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.library import (
    LibraryActivate,
    LibraryDeprecate,
    LibraryLockCreate,
    LibraryProjectLock,
    LibraryResource,
    LibraryResourceCreate,
    LibraryVersion,
    LibraryVersionCreate,
)

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_LIBRARY_PIN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
    RESP_409_LIBRARY,
    RESP_409_VERSION_CONFLICT,
    RESP_422_LIBRARY_BINDING,
    RESP_422_LIBRARY_CONTENT,
    RESP_422_LIBRARY_SCOPE,
    RESP_422_LIBRARY_WORKFLOW,
    merge_conflict,
    merge_status,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import library as library_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1/library", tags=["library"])
locks_router = APIRouter(prefix="/api/v1/library-locks", tags=["library"])


@router.get(
    "",
    response_model=list[LibraryResource],
    description=(
        "List library definitions, optionally filtered. User-scope rows are "
        "visible to their owner (or an admin) only — collections never "
        "count, list, or hint at another user's private resources."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_library(
    session: DbSession,
    machine: CurrentMachine,
    principal: CurrentPrincipal,
    kind: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
) -> list[LibraryResource]:
    resources = await library_service.list_resources(
        session,
        principal,
        kind=kind,
        scope=scope,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return [LibraryResource.model_validate(r) for r in resources]


@router.post(
    "",
    response_model=LibraryResource,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create a library definition plus its draft version 1 (which never "
        "activates itself). Studio scope requires a privileged role; "
        "project scope requires its `project_id`; user scope is owned by "
        "the caller. Accepts `Idempotency-Key` for safe retries."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **merge_conflict(RESP_409_IDEMPOTENCY, RESP_409_LIBRARY),
        **RESP_404_LIBRARY_PIN,
        **merge_status(
            422,
            RESP_422_LIBRARY_SCOPE,
            RESP_422_LIBRARY_CONTENT,
            RESP_422_LIBRARY_WORKFLOW,
            RESP_422_LIBRARY_BINDING,
        ),
    },
)
async def create_library_resource(
    resource_in: LibraryResourceCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> LibraryResource:
    ensure_can_write(principal, "library")

    async def _create() -> LibraryResource:
        resource, _ = await library_service.create_resource(session, principal, resource_in)
        return LibraryResource.model_validate(resource)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /library",
        LibraryResource,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "/{resource_id}",
    response_model=LibraryResource,
    description=(
        "Get one library definition. A User-scope definition owned by "
        "someone else answers 404, never 403, so its existence cannot be "
        "inferred."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_404_NOT_FOUND},
)
async def get_library_resource(
    resource_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> LibraryResource:
    resource = await library_service.get_resource(session, principal, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "library resource not found")
    return LibraryResource.model_validate(resource)


@router.get(
    "/{resource_id}/versions",
    response_model=list[LibraryVersion],
    description="List all versions of a library definition, oldest first.",
    responses={**RESP_401_UNAUTHORIZED, **RESP_404_NOT_FOUND},
)
async def list_library_versions(
    resource_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> list[LibraryVersion]:
    resource = await library_service.get_resource(session, principal, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "library resource not found")
    rows = await library_service.list_versions(session, resource.id)
    return [await library_service.version_detail(session, row) for row in rows]


@router.post(
    "/{resource_id}/versions",
    response_model=LibraryVersion,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Add draft version N+1 to a library definition. Never moves "
        "`active_version` — activation is a separate explicit call. "
        "Accepts `Idempotency-Key` for safe retries."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_LIBRARY_PIN,
        **merge_conflict(RESP_409_IDEMPOTENCY, RESP_409_LIBRARY),
        **merge_status(
            422, RESP_422_LIBRARY_CONTENT, RESP_422_LIBRARY_WORKFLOW, RESP_422_LIBRARY_BINDING
        ),
    },
)
async def create_library_version(
    resource_id: UUID,
    version_in: LibraryVersionCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> LibraryVersion:
    resource = await library_service.get_resource(session, principal, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "library resource not found")
    ensure_can_write(principal, "library")

    async def _create() -> LibraryVersion:
        row = await library_service.create_resource_version(
            session, principal, resource, version_in
        )
        return await library_service.version_detail(session, row)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /library/{resource_id}/versions",
        LibraryVersion,
        _create,
        status.HTTP_201_CREATED,
    )


@router.post(
    "/{resource_id}/activate",
    response_model=LibraryResource,
    description=(
        "Explicitly move `active_version` (sets status to active). Requires "
        "the current resource `version`; a stale value is rejected with the "
        "live server version. Reactivating the active version is a "
        "successful no-op. Accepts `Idempotency-Key` for safe retries."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_LIBRARY_PIN,
        **merge_conflict(RESP_409_VERSION_CONFLICT, RESP_409_IDEMPOTENCY),
    },
)
async def activate_library_version(
    resource_id: UUID,
    activate_in: LibraryActivate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> LibraryResource:
    resource = await library_service.get_resource(session, principal, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "library resource not found")
    ensure_can_write(principal, "library")

    async def _activate() -> LibraryResource:
        updated = await library_service.activate_resource_version(
            session,
            principal,
            resource,
            activate_in.version,
            activate_in.expected_resource_version,
        )
        return LibraryResource.model_validate(updated)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /library/{resource_id}/activate",
        LibraryResource,
        _activate,
        status.HTTP_200_OK,
    )


@router.post(
    "/{resource_id}/deprecate",
    response_model=LibraryResource,
    description=(
        "Deprecate a library definition (replaces deletion: history and "
        "`active_version` are kept). Requires the current resource "
        "`version`. Already deprecated is a successful no-op. Accepts "
        "`Idempotency-Key` for safe retries of an unseen response."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **merge_conflict(RESP_409_VERSION_CONFLICT, RESP_409_IDEMPOTENCY),
    },
)
async def deprecate_library_resource(
    resource_id: UUID,
    deprecate_in: LibraryDeprecate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> LibraryResource:
    resource = await library_service.get_resource(session, principal, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "library resource not found")
    ensure_can_write(principal, "library")

    async def _deprecate() -> LibraryResource:
        updated = await library_service.deprecate_resource(
            session, principal, resource, deprecate_in.expected_resource_version
        )
        return LibraryResource.model_validate(updated)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /library/{resource_id}/deprecate",
        LibraryResource,
        _deprecate,
        status.HTTP_200_OK,
    )


@locks_router.get(
    "",
    response_model=list[LibraryProjectLock],
    description=(
        "List project version locks, optionally filtered by project. "
        "Read-only for every authenticated machine, including `readonly`; "
        "locks on another user's private resources are filtered out."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_library_locks(
    session: DbSession,
    principal: CurrentPrincipal,
    project_id: UUID | None = Query(default=None),
) -> list[LibraryProjectLock]:
    locks = await library_service.list_locks(session, principal, project_id=project_id)
    return [LibraryProjectLock.model_validate(lock) for lock in locks]


@locks_router.post(
    "",
    response_model=LibraryProjectLock,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Pin `(resource, locked_version)` for a project (canonical resource "
        "UUID, never `stable_key` alone). Accepts `Idempotency-Key` for "
        "safe retries."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **merge_conflict(RESP_409_IDEMPOTENCY, RESP_409_LIBRARY),
    },
)
async def set_library_lock(
    lock_in: LibraryLockCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> LibraryProjectLock:
    ensure_can_write(principal, "library")

    async def _create() -> LibraryProjectLock:
        return LibraryProjectLock.model_validate(
            await library_service.set_lock(session, principal, lock_in)
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /library-locks",
        LibraryProjectLock,
        _create,
        status.HTTP_201_CREATED,
    )


@locks_router.delete(
    "/{lock_id}",
    response_model=LibraryProjectLock,
    description=("Release a project lock. Only the creating user (or an admin) may release it."),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def release_library_lock(
    lock_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> LibraryProjectLock:
    lock = await library_service.get_lock(session, lock_id)
    if lock is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "library lock not found")
    return await library_service.release_lock(session, principal, lock)
