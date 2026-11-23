"""Stripe Checkout and customer portal (S4-stripe).

Stripe hosts both pages: this module only creates the customer and the hosted
sessions and returns their URL. No card data ever reaches the API, and the
secret key is read from the environment (`STUDIO_STRIPE_SECRET_KEY`) and never
logged or echoed. Subscription state is *not* written here: it changes only
through a signed webhook (fe18faa4), never from a redirect.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.stripe_event import StripeEventModel
from studio_api.db.models.studio import StudioModel
from studio_api.settings import Settings, get_settings

logger = logging.getLogger(__name__)

BillingInterval = Literal["month", "year"]
PAID_PLAN_CODE = "pro"
FREE_PLAN_CODE = "free"
_TIMEOUT_SECONDS = 15.0


def _error(code: str, http_status: int, message: str) -> HTTPException:
    return HTTPException(http_status, detail={"error_code": code, "message": message})


async def get_billing_client() -> AsyncIterator[httpx.AsyncClient]:
    """Per-request HTTP client; tests override it with a `MockTransport`."""
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        yield client


def _secret(settings: Settings) -> str:
    if settings.stripe_secret_key is None:
        raise _error(
            "billing_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not configured."
        )
    return settings.stripe_secret_key.get_secret_value()


def _price_id(settings: Settings, interval: BillingInterval) -> str:
    price = (
        settings.stripe_price_monthly_id if interval == "month" else settings.stripe_price_annual_id
    )
    if not price:
        raise _error(
            "billing_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not configured."
        )
    return price


async def _stripe_post(
    client: httpx.AsyncClient,
    settings: Settings,
    path: str,
    data: dict[str, str],
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """One form-encoded Stripe call. Only the error type/code is logged: never
    the key, the request body or the response body."""
    headers = {"Authorization": f"Bearer {_secret(settings)}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        response = await client.post(
            f"{settings.stripe_api_base}{path}", data=data, headers=headers
        )
    except httpx.HTTPError as exc:
        logger.warning("stripe call failed path=%s error=%s", path, type(exc).__name__)
        raise _error(
            "billing_provider_error", status.HTTP_502_BAD_GATEWAY, "Stripe is unreachable."
        ) from exc
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
        except ValueError:
            err = {}
        logger.warning(
            "stripe call refused path=%s status=%s type=%s code=%s",
            path,
            response.status_code,
            err.get("type"),
            err.get("code"),
        )
        raise _error(
            "billing_provider_error", status.HTTP_502_BAD_GATEWAY, "Stripe refused the request."
        )
    body: dict[str, Any] = response.json()
    return body


def _return_url(settings: Settings, outcome: str) -> str:
    origin = settings.billing_return_origin.rstrip("/")
    return f"{origin}{settings.billing_upgrade_url}?checkout={outcome}"


async def ensure_customer(
    session: AsyncSession, client: httpx.AsyncClient, studio: StudioModel, settings: Settings
) -> str:
    """The studio's Stripe customer id, created on first use. The Stripe
    idempotency key collapses a concurrent double click into one customer."""
    if studio.stripe_customer_id:
        return studio.stripe_customer_id
    customer = await _stripe_post(
        client,
        settings,
        "/customers",
        {"name": studio.name, "metadata[studio_id]": str(studio.id)},
        idempotency_key=f"studio-customer-{studio.id}",
    )
    studio.stripe_customer_id = str(customer["id"])
    await session.flush()
    return studio.stripe_customer_id


async def create_checkout_session(
    session: AsyncSession,
    client: httpx.AsyncClient,
    studio: StudioModel,
    interval: BillingInterval,
    *,
    settings: Settings | None = None,
) -> str:
    """Hosted Checkout URL to subscribe to Pro. A studio already on Pro manages
    its subscription through the portal instead (409)."""
    settings = settings or get_settings()
    if studio.plan == PAID_PLAN_CODE:
        raise _error(
            "already_subscribed", status.HTTP_409_CONFLICT, "Use the customer portal instead."
        )
    price = _price_id(settings, interval)
    customer = await ensure_customer(session, client, studio, settings)
    data = {
        "mode": "subscription",
        "customer": customer,
        "client_reference_id": str(studio.id),
        "line_items[0][price]": price,
        "line_items[0][quantity]": "1",
        "subscription_data[metadata][studio_id]": str(studio.id),
        "success_url": _return_url(settings, "success"),
        "cancel_url": _return_url(settings, "cancel"),
    }
    # shortcut: the trial is offered on every Checkout of a free studio, so a
    # studio that cancels and returns can re-trial; track it when abuse shows.
    if settings.stripe_trial_days:
        data["subscription_data[trial_period_days]"] = str(settings.stripe_trial_days)
    created = await _stripe_post(client, settings, "/checkout/sessions", data)
    return str(created["url"])


async def create_portal_session(
    client: httpx.AsyncClient, studio: StudioModel, *, settings: Settings | None = None
) -> str:
    """Hosted customer-portal URL. A studio that never subscribed has no Stripe
    customer yet: 409, the caller must go through Checkout first."""
    settings = settings or get_settings()
    if not studio.stripe_customer_id:
        raise _error(
            "no_subscription", status.HTTP_409_CONFLICT, "This studio has no subscription yet."
        )
    created = await _stripe_post(
        client,
        settings,
        "/billing_portal/sessions",
        {
            "customer": studio.stripe_customer_id,
            "return_url": _return_url(settings, "portal"),
        },
    )
    return str(created["url"])


SIGNATURE_TOLERANCE_SECONDS = 300
_SUBSCRIPTION_PAID = {"active", "trialing"}
_SUBSCRIPTION_UNPAID = {"past_due", "unpaid"}
_SUBSCRIPTION_ENDED = {"canceled", "incomplete_expired"}


def verify_stripe_signature(
    secret: str, body: bytes, header: str | None, *, now: float | None = None
) -> bool:
    """`Stripe-Signature: t=<ts>,v1=<hmac>[,v1=...]`: HMAC-SHA256 of `<ts>.<body>`
    with the endpoint secret, constant-time compare, timestamp within tolerance
    (a captured delivery cannot be replayed later)."""
    if not header:
        return False
    parts = [item.partition("=") for item in header.split(",")]
    timestamps = [value for key, _, value in parts if key == "t"]
    signatures = [value for key, _, value in parts if key == "v1"]
    if len(timestamps) != 1 or not signatures or not timestamps[0].isdigit():
        return False
    if (
        abs((time.time() if now is None else now) - int(timestamps[0]))
        > SIGNATURE_TOLERANCE_SECONDS
    ):
        return False
    expected = hmac.new(
        secret.encode(), timestamps[0].encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in signatures)


async def apply_event(
    session: AsyncSession, event: dict[str, Any], *, now: datetime | None = None
) -> Literal["applied", "ignored", "duplicate"]:
    """Apply one signed Stripe event once. Returns `duplicate`, `ignored` or
    `applied`. The event id is recorded in the same transaction as its effect,
    so a failure rolls both back and Stripe's retry reapplies it. Data is never
    deleted: a lost subscription only changes `studios.plan`."""
    event_id, event_type = str(event.get("id", "")), str(event.get("type", ""))
    obj = event.get("data", {}).get("object", {})
    if not event_id or not isinstance(obj, dict):
        raise _error("webhook_invalid_event", status.HTTP_400_BAD_REQUEST, "Malformed event.")
    inserted = await session.execute(
        pg_insert(StripeEventModel)
        .values(id=event_id, type=event_type)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(StripeEventModel.id)
    )
    if inserted.scalar_one_or_none() is None:
        return "duplicate"
    customer = obj.get("customer")
    studio = (
        await session.scalar(
            select(StudioModel).where(StudioModel.stripe_customer_id == customer).with_for_update()
        )
        if isinstance(customer, str)
        else None
    )
    if studio is None:
        return "ignored"
    now = now or datetime.now(UTC)
    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        sub_status = obj.get("status")
        studio.billing_status = sub_status if isinstance(sub_status, str) else None
        trial_end = obj.get("trial_end")
        studio.billing_trial_ends_at = (
            datetime.fromtimestamp(trial_end, UTC)
            if sub_status == "trialing" and isinstance(trial_end, int)
            else None
        )
        if sub_status in _SUBSCRIPTION_PAID:
            studio.plan, studio.billing_past_due_since = PAID_PLAN_CODE, None
        elif sub_status in _SUBSCRIPTION_UNPAID:
            studio.billing_past_due_since = studio.billing_past_due_since or now
        elif sub_status in _SUBSCRIPTION_ENDED:
            _drop_to_free(studio)
    elif event_type == "customer.subscription.deleted":
        _drop_to_free(studio)
    elif event_type == "invoice.payment_failed":
        if studio.plan == PAID_PLAN_CODE:
            studio.billing_past_due_since = studio.billing_past_due_since or now
    elif event_type == "invoice.paid":
        studio.billing_past_due_since = None
    else:
        return "ignored"
    return "applied"


def _drop_to_free(studio: StudioModel) -> None:
    studio.plan, studio.billing_past_due_since = FREE_PLAN_CODE, None
    studio.billing_status, studio.billing_trial_ends_at = None, None


class BillingStatus(BaseModel):
    """Subscription state of one studio, read-only: the plan, Stripe's status,
    the unpaid marker with the end of its grace delay, and the trial end."""

    plan: str
    status: str | None
    past_due_since: datetime | None
    grace_ends_at: datetime | None
    grace_days: int
    trial_ends_at: datetime | None


def billing_status(studio: StudioModel, *, settings: Settings | None = None) -> BillingStatus:
    grace_days = (settings or get_settings()).stripe_grace_days
    since = studio.billing_past_due_since
    return BillingStatus(
        plan=studio.plan,
        status=studio.billing_status,
        past_due_since=since,
        grace_ends_at=since + timedelta(days=grace_days) if since else None,
        grace_days=grace_days,
        trial_ends_at=studio.billing_trial_ends_at,
    )


async def downgrade_overdue_studios(
    session: AsyncSession, grace_days: int, *, now: datetime | None = None
) -> list[uuid.UUID]:
    """Unpaid past the grace delay: back to the free plan. Run on a schedule
    (`studios downgrade-overdue`). Only `studios.plan` changes."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=grace_days)
    overdue = await session.scalars(
        select(StudioModel)
        .where(
            StudioModel.plan == PAID_PLAN_CODE,
            StudioModel.billing_past_due_since.is_not(None),
            StudioModel.billing_past_due_since <= cutoff,
        )
        .with_for_update()
    )
    downgraded = []
    for studio in overdue:
        _drop_to_free(studio)
        downgraded.append(studio.id)
    return downgraded


async def load_studio(session: AsyncSession, studio_id: uuid.UUID) -> StudioModel:
    studio = await session.get(StudioModel, studio_id)
    if studio is None:  # membership was checked first, so this is a race with a purge
        raise _error("studio_not_found", status.HTTP_404_NOT_FOUND, "Studio not found.")
    return studio
