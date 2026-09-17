from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.runtime import (
    RuntimeRegistration,
    RuntimeRegistrationCreate,
    RuntimeRegistrationUpdateRequest,
    RuntimeStatus,
)

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_404_RUNTIME,
    RESP_409_IDEMPOTENCY,
    RESP_409_VERSION_CONFLICT,
    RESP_422_RUNTIME,
    merge_conflict,
    merge_status,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import runtime_registry as registry_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1/runtimes", tags=["runtimes"])


@router.get(
    "",
    response_model=list[RuntimeRegistration],
    description=(
        "List runtimes declared by the caller. Runtimes are always "
        "per-user private: another user's rows are filtered out before "
        "exposure. Revoked rows are excluded by default."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_runtimes(
    session: DbSession,
    principal: CurrentPrincipal,
    status: RuntimeStatus | None = Query(default=None),
    include_revoked: bool = Query(default=False),
) -> list[RuntimeRegistration]:
    runtimes = await registry_service.list_runtimes(
        session, principal, status=status, include_revoked=include_revoked
    )
    return [registry_service.to_contract(r) for r in runtimes]


@router.post(
    "",
    response_model=RuntimeRegistration,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Declare one runtime (generic — never provider-specific). The owner "
        "is always the caller (server-derived); an attached machine must "
        "exist and be owned by the caller. Refs are open chains, never a "
        "vendor catalog. Secret-looking metadata keys are rejected. "
        "Accepts `Idempotency-Key` for safe retries."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_RUNTIME,
        **RESP_409_IDEMPOTENCY,
        **merge_status(422, RESP_422_RUNTIME),
    },
)
async def register_runtime(
    runtime_in: RuntimeRegistrationCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> RuntimeRegistration:
    ensure_can_write(principal, "runtime")

    async def _create() -> RuntimeRegistration:
        runtime = await registry_service.register_runtime(session, principal, runtime_in)
        return registry_service.to_contract(runtime)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /runtimes",
        RuntimeRegistration,
        _create,
        status.HTTP_201_CREATED,
    )


@router.get(
    "/{runtime_id}",
    response_model=RuntimeRegistration,
    description=(
        "Get one declared runtime. Another user's runtime answers 404, "
        "never 403, so its existence cannot be inferred. Revoked rows stay "
        "readable (diagnostics)."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_404_NOT_FOUND},
)
async def get_runtime(
    runtime_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> RuntimeRegistration:
    runtime = await registry_service.get_runtime(session, principal, runtime_id)
    if runtime is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "runtime not found")
    return registry_service.to_contract(runtime)


@router.patch(
    "/{runtime_id}",
    response_model=RuntimeRegistration,
    description=(
        "Mutate a runtime's descriptors without rotating its identity. "
        "Requires the current `version`; a stale value is rejected with "
        "the live server version. Accepts `Idempotency-Key` for safe "
        "retries of an unseen response."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **merge_conflict(RESP_409_IDEMPOTENCY, RESP_409_VERSION_CONFLICT),
        **merge_status(422, RESP_422_RUNTIME),
    },
)
async def update_runtime(
    runtime_id: UUID,
    update_in: RuntimeRegistrationUpdateRequest,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> RuntimeRegistration:
    runtime = await registry_service.get_runtime(session, principal, runtime_id)
    if runtime is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "runtime not found")
    ensure_can_write(principal, "runtime")

    async def _update() -> RuntimeRegistration:
        updated = await registry_service.update_runtime(
            session, principal, runtime, update_in.update, update_in.expected_version
        )
        return registry_service.to_contract(updated)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"PATCH /runtimes/{runtime_id}",
        RuntimeRegistration,
        _update,
        status.HTTP_200_OK,
    )


@router.post(
    "/{runtime_id}/revoke",
    response_model=RuntimeRegistration,
    description=(
        "Logically revoke a runtime (idempotent: already revoked is a "
        "successful no-op). The row stays readable but resolves as "
        "non-live, so bindings toward it fall through instead of silently "
        "retargeting. No physical delete exists. Naturally idempotent — "
        "no `Idempotency-Key` needed."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def revoke_runtime(
    runtime_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> RuntimeRegistration:
    runtime = await registry_service.get_runtime(session, principal, runtime_id)
    if runtime is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "runtime not found")
    revoked = await registry_service.revoke_runtime(session, principal, runtime)
    return registry_service.to_contract(revoked)
