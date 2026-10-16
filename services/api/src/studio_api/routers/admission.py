from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from studio_contracts.admission import AdmissionDryRun
from studio_contracts.auth import CapabilityToken

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN, RESP_404_NOT_FOUND
from studio_api.services import admission as admission_service
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1/roadmaps", tags=["roadmaps"])


@router.get(
    "/{roadmap_id}/admission/dry-run",
    response_model=AdmissionDryRun,
    description=(
        "Read-only admission dry-run of a roadmap's linked Tasks: which ones "
        "could be launched now, on which of the caller's machines, and the "
        "listed `reasons` every other Task is excluded. A step with no linked "
        "task is reported in `steps_without_tasks`. `harness_id` filters the "
        "machines to those able to run it (any detected harness when omitted). "
        "Creates no `TaskLaunch`, reserves nothing and changes no state: the "
        "same server state yields the same lists, reasons and `plan_digest`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def admission_dry_run(
    roadmap_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    harness_id: CapabilityToken | None = Query(default=None),
) -> AdmissionDryRun:
    return await admission_service.dry_run(
        session, principal, roadmap_id, harness_id, get_settings()
    )
