from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from studio_contracts.infra import InfraMeasurementsReport

from studio_api.deps import DbSession, require_operator
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN
from studio_api.services import infra_measurements
from studio_api.services.authz import Principal

router = APIRouter(prefix="/api/v1/internal/infra-measurements", tags=["infra"])


@router.get(
    "",
    response_model=InfraMeasurementsReport,
    description=(
        "Infrastructure cost measurements of the instance, as series over the last "
        "`days` (default 7): table sizes, per-project storage, SSE connections, process "
        "memory, backup volume. Numbers and timestamps only, never a title, file name or "
        "content. Requires the instance operator (`is_operator`): anyone else gets `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def get_infra_measurements(
    session: DbSession,
    _admin: Annotated[Principal, Depends(require_operator)],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> InfraMeasurementsReport:
    return await infra_measurements.report(session, days)
