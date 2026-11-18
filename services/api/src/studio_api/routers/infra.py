from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from studio_contracts.auth import Role
from studio_contracts.infra import InfraMeasurementsReport

from studio_api.db.models.user import UserModel
from studio_api.deps import DbSession, require_roles
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN
from studio_api.services import infra_measurements

router = APIRouter(prefix="/api/v1/internal/infra-measurements", tags=["infra"])


@router.get(
    "",
    response_model=InfraMeasurementsReport,
    description=(
        "Infrastructure cost measurements of the instance, as series over the last "
        "`days` (default 7): table sizes, per-project storage, SSE connections, process "
        "memory, backup volume. Numbers and timestamps only, never a title, file name or "
        "content. Requires the admin role: any other role gets `403 forbidden`."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def get_infra_measurements(
    session: DbSession,
    _admin: Annotated[UserModel, Depends(require_roles(Role.ADMIN))],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> InfraMeasurementsReport:
    return await infra_measurements.report(session, days)
