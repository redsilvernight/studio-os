"""Stripe Checkout and customer portal (`/api/v1/studios/{id}/billing`, S4-stripe).

`owner` only: subscribing or managing the subscription is the studio owner's
call. Both routes return a Stripe-hosted URL; the subscription state itself is
only ever written by a signed webhook.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from studio_api.db.models.studio import StudioRole
from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN
from studio_api.routers.github import _read_bounded_body
from studio_api.services import billing as billing_service
from studio_api.services import studios as studios_service
from studio_api.services.authz import ensure_studio_role
from studio_api.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["studios"])
_MAX_WEBHOOK_BYTES = 262_144

BillingClient = Annotated[httpx.AsyncClient, Depends(billing_service.get_billing_client)]


class CheckoutRequest(BaseModel):
    interval: billing_service.BillingInterval = "month"


class BillingSessionRead(BaseModel):
    url: str


@router.post(
    "/studios/{studio_id}/billing/checkout",
    response_model=BillingSessionRead,
    description=(
        "Stripe-hosted Checkout URL to subscribe the studio to Pro, monthly or "
        "yearly (`owner` only). `409 already_subscribed` once on Pro, `503 "
        "billing_unavailable` when Stripe is not configured. The plan changes "
        "only when Stripe's signed webhook says so, never on return."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def create_checkout(
    studio_id: uuid.UUID,
    payload: CheckoutRequest,
    session: DbSession,
    principal: CurrentPrincipal,
    client: BillingClient,
) -> BillingSessionRead:
    actor = await studios_service.studio_principal(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.OWNER)
    studio = await billing_service.load_studio(session, studio_id)
    url = await billing_service.create_checkout_session(session, client, studio, payload.interval)
    await session.commit()
    return BillingSessionRead(url=url)


class StripeWebhookResult(BaseModel):
    status: Literal["applied", "ignored", "duplicate"]


@router.post(
    "/billing/stripe/webhook",
    response_model=StripeWebhookResult,
    description=(
        "Stripe webhook ingress. Authenticated by the `Stripe-Signature` HMAC "
        "over the raw body (deliberate signed exception to Bearer auth) and "
        "the only writer of a studio's paid status. Each event id is applied "
        "once: a replay answers `duplicate` and changes nothing. Unpaid "
        "starts a grace delay, then the studio drops to the free plan, data kept."
    ),
    responses={
        401: {"description": "Invalid or missing signature."},
        413: {"description": "Body over the bounded ingress size."},
        503: {"description": "`STUDIO_STRIPE_WEBHOOK_SECRET` unset."},
    },
)
async def stripe_webhook(
    request: Request,
    session: DbSession,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> StripeWebhookResult:
    secret = get_settings().stripe_webhook_secret
    if secret is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "webhook_not_configured", "message": "Webhook not configured."},
        )
    body = await _read_bounded_body(request, _MAX_WEBHOOK_BYTES)
    if body is None:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, detail={"error_code": "webhook_body_too_large"}
        )
    if not billing_service.verify_stripe_signature(
        secret.get_secret_value(), body, stripe_signature
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook signature")
    try:
        event = json.loads(body)
    except ValueError:
        event = None
    if not isinstance(event, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail={"error_code": "webhook_invalid_event"}
        )
    outcome = await billing_service.apply_event(session, event)
    await session.commit()
    return StripeWebhookResult(status=outcome)


@router.post(
    "/studios/{studio_id}/billing/portal",
    response_model=BillingSessionRead,
    description=(
        "Stripe-hosted customer-portal URL to manage or cancel the subscription "
        "(`owner` only). `409 no_subscription` until a Checkout created the customer."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def create_portal(
    studio_id: uuid.UUID,
    session: DbSession,
    principal: CurrentPrincipal,
    client: BillingClient,
) -> BillingSessionRead:
    actor = await studios_service.studio_principal(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.OWNER)
    studio = await billing_service.load_studio(session, studio_id)
    return BillingSessionRead(url=await billing_service.create_portal_session(client, studio))
