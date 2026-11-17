from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from pydantic import AwareDatetime
from studio_contracts.usage import UsagePriceList, UsagePriceListCreate

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_409_IDEMPOTENCY,
    ErrorResponses,
    merge_conflict,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import usage_price_lists as price_list_service

router = APIRouter(prefix="/api/v1/usage/price-lists", tags=["usage"])

_RESP_404_PRICE_LIST: ErrorResponses = {
    404: {
        "description": (
            "No price list in force (price_list_not_found): the daemon keeps its cached or "
            "bundled grid. A project-scoped publish on an unknown project also answers 404."
        ),
        "content": {
            "application/json": {"example": {"detail": {"error_code": "price_list_not_found"}}}
        },
    }
}
_RESP_409_PRICE_LIST: ErrorResponses = {
    409: {
        "description": (
            "price_list_id already exists (price_list_conflict). Lists are immutable: "
            "publish a correction under a new id."
        ),
        "content": {
            "application/json": {"example": {"detail": {"error_code": "price_list_conflict"}}}
        },
    }
}


@router.get(
    "",
    response_model=list[UsagePriceList],
    description=(
        "List the global price lists, plus the project's own when project_id is given, "
        "newest effective_from first."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_price_lists(
    session: DbSession, principal: CurrentPrincipal, project_id: UUID | None = Query(default=None)
) -> list[UsagePriceList]:
    rows = await price_list_service.list_price_lists(session, principal, project_id)
    return [price_list_service.to_price_list(row) for row in rows]


@router.get(
    "/effective",
    response_model=UsagePriceList,
    description=(
        "The price list in force at `at` (default now): the project's own latest list with "
        "effective_from <= at, otherwise the global one. Daemons price local usage with it "
        "and record its price_list_id in PricingRef."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **_RESP_404_PRICE_LIST},
)
async def effective_price_list(
    session: DbSession,
    principal: CurrentPrincipal,
    project_id: UUID | None = Query(default=None),
    at: AwareDatetime | None = Query(default=None),
) -> UsagePriceList:
    row = await price_list_service.effective_price_list(
        session, principal, project_id, at or datetime.now(UTC)
    )
    return price_list_service.to_price_list(row)


@router.post(
    "",
    response_model=UsagePriceList,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Publish an immutable, dated price list (per million tokens). A global list "
        "(project_id null) is admin-only; a project list needs an admin or a developer with "
        "write access. Agents and launch credentials never publish. Supports Idempotency-Key."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **_RESP_404_PRICE_LIST,
        **merge_conflict(_RESP_409_PRICE_LIST, RESP_409_IDEMPOTENCY),
    },
)
async def create_price_list(
    payload: UsagePriceListCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> UsagePriceList:
    async def _create() -> UsagePriceList:
        return price_list_service.to_price_list(
            await price_list_service.create_price_list(
                session, principal, payload, commit=idempotency_key is None
            )
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /usage/price-lists",
        UsagePriceList,
        _create,
        status.HTTP_201_CREATED,
    )
