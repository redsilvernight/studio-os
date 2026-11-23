from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from studio_operator.auth import require_operator
from studio_operator.repository import OperatorRepository, get_repository
from studio_operator.schemas import UsageReport
from studio_operator.settings import OperatorAccount

router = APIRouter(tags=["usage"])

Operator = Annotated[OperatorAccount, Depends(require_operator)]
Repository = Annotated[OperatorRepository, Depends(get_repository)]


@router.get(
    "/usage",
    response_model=UsageReport,
    description=(
        "Fiche C3 — aggregate usage over `days`: platform storage against "
        "capacity, measured phase-M totals (tokens, duration, cost per currency) "
        "and the top studios by tokens, plus the studios at or above the storage "
        "alert threshold. Never a file name, a project name or any content."
    ),
)
async def usage(
    _operator: Operator,
    repository: Repository,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> UsageReport:
    return await repository.usage(days)
