from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from studio_contracts.infra import InfraMeasurementsReport

from studio_operator.auth import require_operator
from studio_operator.repository import OperatorRepository, get_repository
from studio_operator.schemas import Dashboard
from studio_operator.settings import OperatorAccount

router = APIRouter(tags=["dashboard"])

Operator = Annotated[OperatorAccount, Depends(require_operator)]
Repository = Annotated[OperatorRepository, Depends(get_repository)]


@router.get(
    "/dashboard",
    response_model=Dashboard,
    description=(
        "Fiche C1 — service health and phase-M measures, aggregated: active "
        "studios, platform storage against capacity, alert thresholds, and the "
        "state of the API/database/Stripe-webhook sources. Never a project name, "
        "a file name or any client content. A source the phase M does not "
        "measure is reported `unavailable`, never a made-up figure."
    ),
)
async def dashboard(_operator: Operator, repository: Repository) -> Dashboard:
    return await repository.dashboard()


@router.get(
    "/measures",
    response_model=InfraMeasurementsReport,
    description=(
        "Fiche C1 — raw phase-M series over `days` (table sizes, per-project "
        "storage, SSE connections, process memory, backup volume): numbers and "
        "timestamps only, never a title, a file name or content."
    ),
)
async def measures(
    _operator: Operator,
    repository: Repository,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> InfraMeasurementsReport:
    return await repository.measures(days)
