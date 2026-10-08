from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Header, Query, Request, status
from studio_contracts.decisions import Decision, DecisionCreate, DecisionSupersede

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_DECISION_TRANSITION,
    RESP_409_IDEMPOTENCY,
    ErrorResponses,
)
from studio_api.services import decisions as decisions_service
from studio_api.services import idempotency as idempotency_service

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])

RESP_422_DECISION_SUPERSEDE: ErrorResponses = {
    422: {
        "description": (
            "Supersede body rejected, nothing stored: `superseded_by` is "
            "optional, but when present it must be a UUID string — a "
            "malformed one is the framework's native 422 and no transition "
            "is attempted."
        ),
        "content": {
            "application/json": {
                "example": {
                    "detail": [
                        {"loc": ["body", "superseded_by"], "msg": "Input should be a valid UUID"}
                    ]
                }
            }
        },
    }
}


@router.get(
    "",
    response_model=list[Decision],
    description=(
        "List recorded decisions of the caller's accessible projects, plus "
        "global (project-less) decisions for a caller with at least one "
        "project, optionally filtered by project. A `project_id` the caller "
        "cannot access answers `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_decisions(
    session: DbSession, principal: CurrentPrincipal, project_id: UUID | None = Query(default=None)
) -> list[Decision]:
    decisions = await decisions_service.list_decisions(session, principal, project_id=project_id)
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
    decisions_service.authorize_create(principal, decision_in.project_id)

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
        "`409 invalid_decision_transition`, never a duplicate transition. "
        "Optional body `superseded_by` names the replacing Decision "
        "(internal UUID): the two are linked by a `supersedes` edge, so the "
        "replacement and what it replaced stay traceable in both "
        "directions. Omit it (or omit the body) to supersede without "
        "naming a replacement — the transition then records nothing but the "
        "status change."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_DECISION_TRANSITION,
        **RESP_422_DECISION_SUPERSEDE,
    },
)
async def supersede_decision(
    decision_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    body: DecisionSupersede | None = Body(default=None),
) -> Decision:
    superseded_by = body.superseded_by if body else None
    if superseded_by is None:
        # Additive: a body-less supersede keeps calling the service exactly
        # as before, so no existing call changes shape.
        decision = await decisions_service.supersede_decision(session, principal, decision_id)
    else:
        decision = await decisions_service.supersede_decision(
            session, principal, decision_id, superseded_by=superseded_by
        )
    return Decision.model_validate(decision)
