from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from studio_operator.auth import require_operator
from studio_operator.repository import OperatorRepository, get_repository
from studio_operator.schemas import FeatureAvailability, SuspensionList
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
    response_model=FeatureAvailability,
    description=(
        "Fiche C4 — billing is S4 (Stripe) and not deployed: this answers "
        "`available=false` with the reason, and reads no subscription, invoice or "
        "webhook row. Never a card number: Stripe alone holds payment data."
    ),
)
async def billing(_operator: Operator) -> FeatureAvailability:
    return FeatureAvailability(
        available=False,
        reason_code="billing_not_deployed",
        message=(
            "Facturation Stripe (S4) non déployée : abonnements, impayés et "
            "événements webhook ne sont pas encore lisibles."
        ),
    )


@router.get(
    "/break-glass",
    response_model=FeatureAvailability,
    description=(
        "Fiche C5 — the break-glass request queue belongs to its own task and is "
        "not implemented here: no request, grant or log is read or written by this "
        "console, which keeps the 'operator reads nothing by default' guarantee."
    ),
)
async def break_glass(_operator: Operator) -> FeatureAvailability:
    return FeatureAvailability(
        available=False,
        reason_code="break_glass_not_deployed",
        message=(
            "Demandes break-glass non implémentées dans cette version : "
            "l'opérateur ne lit rien par défaut."
        ),
    )
