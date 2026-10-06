from __future__ import annotations

from fastapi import APIRouter
from studio_contracts.bootstrap_plan import BootstrapPlan, BootstrapPlanRequest

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_422_RESOLUTION,
)
from studio_api.services import bootstrap_plan as bootstrap_plan_service

router = APIRouter(prefix="/api/v1/bootstrap-plan", tags=["bootstrap-plan"])


@router.post(
    "",
    response_model=BootstrapPlan,
    description=(
        "Read-only aggregated bootstrap plan of a project: the agent "
        "definitions visible in the project context (or the named "
        "`agent_keys`) resolved through `resolve_full`, merged into one "
        "de-duplicated artifact list (agents, model profiles, skills, "
        "rules) with exact version, provenance, `common`/`project` segment, "
        "`required_by` and a content hash, plus a `plan_hash`. "
        "Deterministic (no timestamp, sorted) and harness-agnostic. Any "
        "failing agent fails the whole plan with the `POST /resolutions` "
        "error: unknown or invisible definition `404 definition_not_found`, "
        "incompatible runtime `422`. Pure read: safe to retry, no "
        "`Idempotency-Key` needed."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        422: RESP_422_RESOLUTION[422],
    },
)
async def build_bootstrap_plan(
    plan_in: BootstrapPlanRequest,
    session: DbSession,
    principal: CurrentPrincipal,
) -> BootstrapPlan:
    return await bootstrap_plan_service.build_bootstrap_plan(session, principal, plan_in)
