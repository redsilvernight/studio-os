from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from studio_contracts.ai_integration import AiIntegrationStatus

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN
from studio_api.services import ai_integration as ai_integration_service
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1/projects", tags=["ai-integration"])


@router.get(
    "/{project_id}/ai-integration",
    response_model=AiIntegrationStatus,
    response_model_exclude_none=True,
    description=(
        "Read-only AI integration status of a project (AIB P6): the "
        "desired state (aggregated bootstrap plan: `plan_hash`, agent keys, "
        "artifact counts; `desired_error` when it cannot be built) next to "
        "what each of the caller's machines (every machine for `admin`) "
        "last reported through its heartbeat capability report. Reported "
        "values are machine claims with their reception time and a "
        "`freshness` (`fresh`, `stale`, `never_reported`): the server "
        "never asserts a write on a machine it has not been told about. "
        "Inaccessible and unknown projects answer the same `403`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def get_ai_integration(
    project_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> AiIntegrationStatus:
    return await ai_integration_service.ai_integration_status(
        session, principal, project_id, get_settings()
    )
