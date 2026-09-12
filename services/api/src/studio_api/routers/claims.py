from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Request, status
from studio_contracts.claims import ResourceClaim, ResourceClaimCreate
from studio_contracts.events import EventCreate, EventType

from studio_api.deps import CurrentMachine, DbSession
from studio_api.services import claims as claims_service
from studio_api.services import events as events_service
from studio_api.services import idempotency as idempotency_service

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])


@router.get("", response_model=list[ResourceClaim])
async def list_claims(
    session: DbSession, machine: CurrentMachine, project_id: UUID | None = Query(default=None)
) -> list[ResourceClaim]:
    claims = await claims_service.list_claims(session, project_id=project_id)
    return [ResourceClaim.model_validate(c) for c in claims]


@router.post("", response_model=ResourceClaim, status_code=status.HTTP_201_CREATED)
async def create_claim(
    claim_in: ResourceClaimCreate,
    request: Request,
    session: DbSession,
    machine: CurrentMachine,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ResourceClaim:
    async def _create() -> ResourceClaim:
        claim = await claims_service.create_claim(session, claim_in, machine.id, agent_id=None)
        if await claims_service.has_conflict(session, claim):
            await events_service.create_event(
                session,
                EventCreate(
                    event_id=uuid4(),
                    event_type=EventType.RESOURCE_CONFLICT,
                    project_id=claim.project_id,
                    task_id=claim.task_id,
                    machine_id=machine.id,
                    actor_type="system",
                    actor_id=machine.id,
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


@router.post("/{claim_id}/renew", response_model=ResourceClaim)
async def renew_claim(claim_id: UUID, session: DbSession, machine: CurrentMachine) -> ResourceClaim:
    claim = await claims_service.get_claim(session, claim_id)
    claim = await claims_service.renew_claim(session, claim)
    return ResourceClaim.model_validate(claim)


@router.delete("/{claim_id}", status_code=status.HTTP_204_NO_CONTENT)
async def release_claim(claim_id: UUID, session: DbSession, machine: CurrentMachine) -> None:
    claim = await claims_service.get_claim(session, claim_id)
    await claims_service.release_claim(session, claim)
