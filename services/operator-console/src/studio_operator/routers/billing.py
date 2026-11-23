from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from studio_operator.auth import require_operator
from studio_operator.repository import OperatorRepository, get_repository
from studio_operator.schemas import (
    BillingReport,
    BreakGlassCreateRequest,
    BreakGlassQueue,
    BreakGlassRequest,
    SuspensionList,
)
from studio_operator.settings import OperatorAccount

router = APIRouter(tags=["suspensions"])

Operator = Annotated[OperatorAccount, Depends(require_operator)]
Repository = Annotated[OperatorRepository, Depends(get_repository)]


@router.get(
    "/suspensions",
    response_model=SuspensionList,
    description=(
        "Suspended studios: name, plan, members, storage and owner address, with "
        "the date the status last changed. Aggregate measures only."
    ),
)
async def suspensions(_operator: Operator, repository: Repository) -> SuspensionList:
    studios = await repository.suspended()
    return SuspensionList(total=len(studios), studios=studios)


@router.get(
    "/billing",
    response_model=BillingReport,
    description=(
        "Fiche C4 — subscription aggregates: studios per plan, unpaid studios "
        "with the end of their grace delay, running trials and the latest "
        "Stripe webhook event types. Never a card number, customer id, key or "
        "client content: Stripe alone holds payment data."
    ),
)
async def billing(_operator: Operator, repository: Repository) -> BillingReport:
    return await repository.billing()


@router.get(
    "/break-glass",
    response_model=BreakGlassQueue,
    description=(
        "Fiche C5 — break-glass request queue: who asked, why, the declared "
        "scope (`metadata` or `support`, never content) and the owner's status. "
        "The console never opens an access and never reads client content; a "
        "request waits for the studio owner's explicit approval."
    ),
)
async def break_glass(_operator: Operator, repository: Repository) -> BreakGlassQueue:
    requests = await repository.break_glass_queue()
    return BreakGlassQueue(total=len(requests), requests=requests)


@router.post(
    "/break-glass",
    response_model=BreakGlassRequest,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Fiche C5 — open a motivated break-glass request for one studio. It "
        "grants nothing: the studio owner approves, refuses or revokes, and "
        "every transition is journaled for the client. No content is read."
    ),
)
async def request_break_glass(
    body: BreakGlassCreateRequest, operator: Operator, repository: Repository
) -> BreakGlassRequest:
    reason = body.stripped_reason()
    if not reason:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "break_glass_reason_required",
                "message": "un motif est obligatoire",
            },
        )
    created = await repository.request_break_glass(
        body.studio_id, operator.email, reason, body.scope
    )
    if created is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "studio introuvable")
    return created
