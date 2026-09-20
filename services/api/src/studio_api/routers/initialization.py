"""Canonical HTTP surface of project initialization (Roadmaps P5, DEC-0087).

Thin adapters over `services.initialization` with the default
`StudioServicesInitializationTarget`: preview is a pure read, apply is
idempotent (`Idempotency-Key`) and replay-safe. Same permission boundary as
the MCP pair: preview needs no write grant, creating a project is
provisioning, initializing into an existing one is a write.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request, status
from studio_contracts.auth import Role
from studio_contracts.initialization import (
    InitializationPreview,
    InitializationResult,
    ProjectInitializationPlan,
    ProjectInitializationRequest,
)
from studio_contracts.roadmaps import RoadmapOrigin, WriteProvenance

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    ErrorResponses,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import initialization as initialization_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1", tags=["initialization"])

IdempotencyKey = Header(
    default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
)

RESP_422_INIT: ErrorResponses = {
    422: {
        "description": "`invalid_initialization` (a blocking problem refuses the "
        "apply before any write; `problems` is the structured list). "
        "A schema-shape error is the framework's native 422.",
        "content": {
            "application/json": {"example": {"detail": {"error_code": "invalid_initialization"}}}
        },
    },
    409: {
        "description": "`actor_not_owned` (declared `agent_id` not attached to "
        "the caller's machine).",
        "content": {"application/json": {"example": {"detail": {"error_code": "actor_not_owned"}}}},
    },
}


@router.post(
    "/projects/initialization/preview",
    response_model=InitializationPreview,
    responses={**RESP_401_UNAUTHORIZED},
)
async def preview_initialization(
    plan: ProjectInitializationPlan,
    session: DbSession,
    principal: CurrentPrincipal,
) -> InitializationPreview:
    target = initialization_service.StudioServicesInitializationTarget(session, principal)
    return await initialization_service.preview_initialization(target, plan)


@router.post(
    "/projects/initialization/apply",
    response_model=InitializationResult,
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_422_INIT},
)
async def apply_initialization(
    payload: ProjectInitializationRequest,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = IdempotencyKey,
) -> InitializationResult:
    ensure_can_write(principal, "initialization")
    is_agent_write = payload.provenance.agent_id is not None or principal.role is Role.AGENT
    provenance = WriteProvenance(
        origin=RoadmapOrigin.AI_PROPOSAL if is_agent_write else RoadmapOrigin.MANUAL,
        agent_id=payload.provenance.agent_id,
    )
    target = initialization_service.StudioServicesInitializationTarget(session, principal)
    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /projects/initialization/apply",
        InitializationResult,
        lambda: initialization_service.apply_initialization(
            target, payload.plan, principal, provenance
        ),
        status.HTTP_200_OK,
    )
