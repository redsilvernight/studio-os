from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status
from studio_contracts.usage import (
    UsageSubscription,
    UsageSubscriptionCreate,
    UsageSubscriptionUpdate,
)

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
    RESP_409_VERSION_CONFLICT,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import usage_subscriptions as subscription_service

router = APIRouter(prefix="/api/v1/usage/subscriptions", tags=["usage"])


@router.get(
    "",
    response_model=list[UsageSubscription],
    description="List the subscriptions declared for a project, by start date.",
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_subscriptions(
    session: DbSession, principal: CurrentPrincipal, project_id: UUID = Query()
) -> list[UsageSubscription]:
    rows = await subscription_service.list_subscriptions(session, principal, project_id)
    return [subscription_service.to_subscription(row) for row in rows]


@router.post(
    "",
    response_model=UsageSubscription,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Declare a flat-rate subscription (monthly price, currency, covered harnesses and/or "
        "providers, period). Its price is spread over the covered usage at read time in "
        "/usage/summary (subscription_share); nothing is stored per entry. Launch-scoped "
        "credentials cannot manage subscriptions. Supports Idempotency-Key."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_IDEMPOTENCY,
    },
)
async def create_subscription(
    payload: UsageSubscriptionCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> UsageSubscription:
    async def _create() -> UsageSubscription:
        return subscription_service.to_subscription(
            await subscription_service.create_subscription(
                session, principal, payload, commit=idempotency_key is None
            )
        )

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /usage/subscriptions",
        UsageSubscription,
        _create,
        status.HTTP_201_CREATED,
    )


@router.put(
    "/{subscription_id}",
    response_model=UsageSubscription,
    description=(
        "Replace a subscription's terms. A stale expected_version fails with "
        "version_conflict and server_version."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_VERSION_CONFLICT,
    },
)
async def update_subscription(
    subscription_id: UUID,
    payload: UsageSubscriptionUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
) -> UsageSubscription:
    row = await subscription_service.update_subscription(
        session, principal, subscription_id, payload
    )
    return subscription_service.to_subscription(row)


@router.delete(
    "/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Delete a subscription; summaries stop allocating it. A stale expected_version "
        "fails with version_conflict and server_version."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **RESP_409_VERSION_CONFLICT,
    },
)
async def delete_subscription(
    subscription_id: UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    expected_version: int = Query(ge=1),
) -> Response:
    await subscription_service.delete_subscription(
        session, principal, subscription_id, expected_version
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
