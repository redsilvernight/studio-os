from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from studio_operator.auth import require_operator
from studio_operator.repository import (
    ACTIVE,
    SUSPENDED,
    OperatorRepository,
    ProtectedStudioError,
    get_repository,
)
from studio_operator.schemas import (
    StudioDetail,
    StudioList,
    StudioSummary,
    SuspensionRequest,
)
from studio_operator.settings import OperatorAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/studios", tags=["studios"])

Operator = Annotated[OperatorAccount, Depends(require_operator)]
Repository = Annotated[OperatorRepository, Depends(get_repository)]


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error_code": "studio_not_found", "message": "Studio introuvable."},
    )


@router.get(
    "",
    response_model=StudioList,
    description=(
        "Fiche C2 — studio directory: name, plan, status, storage against the "
        "plan quota, member count against the plan limit, owner email. `q` "
        "matches the studio name, its slug or the owner's address; results are "
        "sorted by name and capped by `limit`. Aggregate measures only: the "
        "console has no route to any client content."
    ),
)
async def list_studios(
    _operator: Operator,
    repository: Repository,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> StudioList:
    studios = await repository.list_studios(q, limit=limit)
    return StudioList(total=await repository.count_studios(), studios=studios)


@router.get(
    "/{studio_id}",
    response_model=StudioDetail,
    description=(
        "Fiche C2 — one studio, measures only: plan, status, storage, members, "
        "owner address and measured usage totals. No project, no file, no note."
    ),
)
async def get_studio(
    studio_id: uuid.UUID,
    _operator: Operator,
    repository: Repository,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> StudioDetail:
    detail = await repository.studio_detail(studio_id, days=days)
    if detail is None:
        raise _not_found()
    return detail


async def _apply_status(
    repository: OperatorRepository,
    studio_id: uuid.UUID,
    new_status: str,
    reason: str | None = None,
) -> StudioSummary:
    try:
        studio = await repository.set_status(studio_id, new_status, reason)
    except ProtectedStudioError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "studio_not_suspendable",
                "message": "Le studio interne ne peut pas être suspendu.",
            },
        ) from None
    if studio is None:
        raise _not_found()
    return studio


@router.post(
    "/{studio_id}/suspension",
    response_model=StudioSummary,
    description=(
        "Fiche C2 — suspend a studio. A motif is mandatory (`422` otherwise), "
        "visible to the owner, and stored in `studios.suspension_reason` (0053); "
        "only `studios.status` and that column change to `suspended` — nothing is "
        "deleted and export stays allowed. The internal studio refuses with `409`."
    ),
)
async def suspend_studio(
    studio_id: uuid.UUID,
    payload: SuspensionRequest,
    operator: Operator,
    repository: Repository,
) -> StudioSummary:
    studio = await _apply_status(repository, studio_id, SUSPENDED, payload.reason)
    logger.info(
        "operator %s suspended studio %s (reason: %s)",
        operator.email,
        studio_id,
        payload.reason,
    )
    return studio


@router.delete(
    "/{studio_id}/suspension",
    response_model=StudioSummary,
    description=(
        "Lift a suspension: `studios.status` returns to `active`. Idempotent; "
        "the studio must exist (`404` otherwise)."
    ),
)
async def lift_suspension(
    studio_id: uuid.UUID,
    operator: Operator,
    repository: Repository,
) -> StudioSummary:
    studio = await _apply_status(repository, studio_id, ACTIVE)
    logger.info("operator %s reactivated studio %s", operator.email, studio_id)
    return studio
