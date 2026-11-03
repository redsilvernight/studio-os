from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from studio_contracts.admission import AdmissionBatchRequest, AdmissionBatchResult, AdmissionDryRun
from studio_contracts.auth import CapabilityToken

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_ADMISSION,
)
from studio_api.services import admission as admission_service
from studio_api.services import idempotency as idempotency_service
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


@router.post(
    "/{roadmap_id}/admission",
    response_model=AdmissionBatchResult,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Admit a whole batch of a roadmap's linked Tasks or nothing. "
        "`plan_digest` is the digest of the dry-run the human confirmed: the "
        "server recomputes the plan under a roadmap then task lock and refuses "
        "`409 admission_plan_changed` (carrying the fresh `plan`) if it moved "
        "— a second tab or another user sees this once Tasks became "
        "`launch_active`. Otherwise every item must be launchable on a machine "
        "of its `machine_ids`, unique, and admitted by the project budget; any "
        "refusal rolls the whole batch back and answers `409 admission_refused` "
        "with every `refusals` entry. On success the `TaskLaunch` rows, their "
        "reservations and events are written in one transaction. Requires a "
        "writer role and the right to launch on each target machine. Accepts "
        "`Idempotency-Key`: replaying the same key returns the original result."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_ADMISSION,
    },
)
async def admit_roadmap_batch(
    roadmap_id: UUID,
    body: AdmissionBatchRequest,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> AdmissionBatchResult:
    await admission_service.authorize_admit(session, principal, roadmap_id)

    async def _admit() -> AdmissionBatchResult:
        return await admission_service.admit_batch(
            session, principal, roadmap_id, body, get_settings()
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /roadmaps/{roadmap_id}/admission",
        AdmissionBatchResult,
        _admit,
        status.HTTP_201_CREATED,
    )
