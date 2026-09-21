from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from studio_contracts.decisions import Decision, DecisionCreate

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_DECISION_TRANSITION,
    RESP_409_IDEMPOTENCY,
)
from studio_api.services import decisions as decisions_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])


@router.get(
    "",
    response_model=list[Decision],
    description=(
        "List recorded decisions, optionally filtered by project. Any "
        "authenticated machine may read."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_decisions(
    session: DbSession, machine: CurrentMachine, project_id: UUID | None = Query(default=None)
) -> list[Decision]:
    decisions = await decisions_service.list_decisions(session, project_id=project_id)
    return [Decision.model_validate(d) for d in decisions]


@router.post(
    "",
    response_model=Decision,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Record a project decision. Requires a writer role; the proposer "
        "identity is derived from the caller's authenticated machine. "
        "Accepts `Idempotency-Key` for safe retries: the same key "
        "returns the original decision instead of allocating a second id."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_IDEMPOTENCY},
)
async def create_decision(
    decision_in: DecisionCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> Decision:
    ensure_can_write(principal, "decision")

    async def _create() -> Decision:
        return Decision.model_validate(
            await decisions_service.create_decision(session, principal, decision_in)
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /decisions",
        Decision,
        _create,
        status.HTTP_201_CREATED,
    )


@router.post(
    "/{decision_id}/accept",
    response_model=Decision,
    description=(
        "Accept a proposed Decision (`proposed` -> `accepted`). Admin role "
        "only. This is a state transition, not a creation: no "
        "`Idempotency-Key` — retrying after success answers "
        "`409 invalid_decision_transition`, never a duplicate transition."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_DECISION_TRANSITION,
    },
)
async def accept_decision(
    decision_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> Decision:
    decision = await decisions_service.accept_decision(session, principal, decision_id)
    return Decision.model_validate(decision)


@router.post(
    "/{decision_id}/supersede",
    response_model=Decision,
    description=(
        "Supersede a Decision (`proposed` or `accepted` -> `superseded`, "
        "terminal — no transition is ever allowed out of it). Admin role "
        "only. This is a state transition, not a creation: no "
        "`Idempotency-Key` — retrying after success answers "
        "`409 invalid_decision_transition`, never a duplicate transition."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_DECISION_TRANSITION,
    },
)
async def supersede_decision(
    decision_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> Decision:
    decision = await decisions_service.supersede_decision(session, principal, decision_id)
    return Decision.model_validate(decision)
