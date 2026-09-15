from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Request, status
from studio_contracts.claims import ResourceClaim, ResourceClaimCreate
from studio_contracts.events import EventCreate, EventType

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
)
from studio_api.services import claims as claims_service
from studio_api.services import events as events_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])


@router.get(
    "",
    response_model=list[ResourceClaim],
    description=(
        "List resource claims, optionally filtered by project. Any authenticated machine may read."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_claims(
    session: DbSession, machine: CurrentMachine, project_id: UUID | None = Query(default=None)
) -> list[ResourceClaim]:
    claims = await claims_service.list_claims(session, project_id=project_id)
    return [ResourceClaim.model_validate(c) for c in claims]


@router.post(
    "",
    response_model=ResourceClaim,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Claim a resource path (file or folder) for the caller's machine. "
        "Claims are soft locks with a TTL: they warn other machines "
        "through a conflict event when paths overlap, but never block a "
        "write, a Git operation, or a transfer. Requires a writer role. "
        "Accepts `Idempotency-Key` for safe retries — replaying the same "
        "key never re-emits the conflict event."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_IDEMPOTENCY},
)
async def create_claim(
    claim_in: ResourceClaimCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> ResourceClaim:
    ensure_can_write(principal, "claim")

    async def _create() -> ResourceClaim:
        claim = await claims_service.create_claim(
            session, principal, claim_in, principal.machine.id, agent_id=None
        )
        if await claims_service.has_conflict(session, claim):
            await events_service.create_event(
                session,
                EventCreate(
                    event_id=uuid4(),
                    event_type=EventType.RESOURCE_CONFLICT,
                    project_id=claim.project_id,
                    task_id=claim.task_id,
                    machine_id=principal.machine.id,
                    actor_type="system",
                    actor_id=principal.machine.id,
                    client_timestamp=datetime.now(UTC),
                    payload={"claim_id": str(claim.id), "resource_path": claim.resource_path},
                ),
            )
        return ResourceClaim.model_validate(claim)

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /claims",
        ResourceClaim,
        _create,
        status.HTTP_201_CREATED,
    )


@router.post(
    "/{claim_id}/renew",
    response_model=ResourceClaim,
    description=(
        "Extend a claim's TTL. Only the machine holding the claim (or a "
        "privileged role) may renew it."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def renew_claim(
    claim_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> ResourceClaim:
    claim = await claims_service.get_claim(session, claim_id)
    claim = await claims_service.renew_claim(session, principal, claim)
    return ResourceClaim.model_validate(claim)


@router.delete(
    "/{claim_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Release a resource claim. Only the machine holding the claim "
        "(or a privileged role) may release it. Releasing twice is "
        "harmless — never a duplicate problem."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def release_claim(claim_id: UUID, session: DbSession, principal: CurrentPrincipal) -> None:
    claim = await claims_service.get_claim(session, claim_id)
    await claims_service.release_claim(session, principal, claim)
