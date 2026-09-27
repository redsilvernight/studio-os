from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.library import LibraryKind
from studio_contracts.runtime import RuntimeBinding, RuntimeBindingCreate, RuntimeLevel

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_404_RUNTIME,
    RESP_409_IDEMPOTENCY,
    RESP_409_RUNTIME_BINDING,
    RESP_422_RUNTIME,
    merge_conflict,
    merge_status,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import runtime_bindings as bindings_service

router = APIRouter(prefix="/api/v1/runtime-bindings", tags=["runtime-bindings"])


@router.get(
    "",
    response_model=list[RuntimeBinding],
    description=(
        "List stored runtime choices, optionally filtered. Another user's "
        "`user`-level bindings are filtered out before exposure — "
        "collections never count, list, or hint at them. Project levels "
        "need their project, the studio default at least one project; a "
        "`project_id` the caller cannot access answers `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_runtime_bindings(
    session: DbSession,
    principal: CurrentPrincipal,
    level: RuntimeLevel | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
    kind: LibraryKind | None = Query(default=None),
    stable_key: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
) -> list[RuntimeBinding]:
    bindings = await bindings_service.list_bindings(
        session,
        principal,
        level=level,
        project_id=project_id,
        kind=kind,
        stable_key=stable_key,
    )
    return [bindings_service.to_contract(b) for b in bindings[offset : offset + limit]]


@router.post(
    "",
    response_model=RuntimeBinding,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Store one runtime choice for a logical `(kind, stable_key)` key. "
        "The owner is always the caller (server-derived). Only the four "
        "stored levels persist — `session` is ephemeral and rejected here "
        "(`ephemeral_level_not_stored`); pass it to the resolution call "
        "instead. Accepts `Idempotency-Key` for safe retries."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_RUNTIME,
        **merge_conflict(RESP_409_IDEMPOTENCY, RESP_409_RUNTIME_BINDING),
        **merge_status(422, RESP_422_RUNTIME),
    },
)
async def create_runtime_binding(
    binding_in: RuntimeBindingCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> RuntimeBinding:
    bindings_service.authorize_create(principal, binding_in.level, binding_in.project_id)

    async def _create() -> RuntimeBinding:
        binding = await bindings_service.create_binding(session, principal, binding_in)
        return bindings_service.to_contract(binding)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /runtime-bindings",
        RuntimeBinding,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "/{binding_id}",
    response_model=RuntimeBinding,
    description=(
        "Get one stored runtime choice. Another user's `user`-level binding "
        "answers 404, never 403, so its existence cannot be inferred."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_404_NOT_FOUND},
)
async def get_runtime_binding(
    binding_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> RuntimeBinding:
    binding = await bindings_service.get_binding(session, principal, binding_id)
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "runtime binding not found")
    return bindings_service.to_contract(binding)


@router.delete(
    "/{binding_id}",
    response_model=RuntimeBinding,
    description=(
        "Release a stored runtime choice (snapshot returned). Release rules "
        "mirror project locks: `user` level by owner-or-admin, shared "
        "project levels by creator-or-admin, `studio_default` by privileged "
        "roles. Naturally idempotent — no `Idempotency-Key` needed."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def delete_runtime_binding(
    binding_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> RuntimeBinding:
    binding = await bindings_service.get_binding(session, principal, binding_id)
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "runtime binding not found")
    return await bindings_service.delete_binding(session, principal, binding)
