"""Stripe webhook (S4-stripe): signature, replay, unpaid grace, data kept."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api import settings as settings_module
from studio_api.db.models.studio import StudioModel
from studio_api.routers import billing as billing_router
from studio_api.services import billing as billing_service

WHSEC = "whsec_unit_only_value"
URL = "/api/v1/billing/stripe/webhook"


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    patched = settings_module.get_settings().model_copy(
        update={"stripe_webhook_secret": SecretStr(WHSEC)}
    )
    monkeypatch.setattr(billing_router, "get_settings", lambda: patched)


def _sign(body: bytes, secret: str = WHSEC, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


async def _post(client: AsyncClient, event: dict[str, object], **kw: object) -> int:
    body = json.dumps(event).encode()
    headers = {"Stripe-Signature": _sign(body)}
    response = await client.post(URL, content=body, headers=headers)
    return response.status_code


async def _studio_with_customer(db_session: AsyncSession) -> StudioModel:
    studio = StudioModel(
        slug=f"s-{uuid.uuid4().hex[:8]}",
        name="Atelier",
        stripe_customer_id=f"cus_{uuid.uuid4().hex}",
    )
    db_session.add(studio)
    await db_session.commit()
    return studio


def _sub_event(customer: str, status: str, event_id: str | None = None) -> dict[str, object]:
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": customer, "status": status}},
    }


async def test_invalid_or_missing_signature_changes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    studio = await _studio_with_customer(db_session)
    body = json.dumps(_sub_event(str(studio.stripe_customer_id), "active")).encode()
    for headers in (
        {},
        {"Stripe-Signature": _sign(body, secret="whsec_wrong")},
        {"Stripe-Signature": _sign(body, ts=int(time.time()) - 3600)},  # stale replay
    ):
        response = await client.post(URL, content=body, headers=headers)
        assert response.status_code == 401
    await db_session.refresh(studio)
    assert studio.plan == "free"


async def test_signed_event_upgrades_once_and_replay_has_no_effect(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    studio = await _studio_with_customer(db_session)
    event = _sub_event(str(studio.stripe_customer_id), "active")
    assert await _post(client, event) == 200
    await db_session.refresh(studio)
    assert studio.plan == "pro"
    studio.plan = "free"  # an operator change a replay must not undo
    await db_session.commit()
    body = json.dumps(event).encode()
    response = await client.post(URL, content=body, headers={"Stripe-Signature": _sign(body)})
    assert response.json() == {"status": "duplicate"}
    await db_session.refresh(studio)
    assert studio.plan == "free"


async def test_unpaid_keeps_pro_during_grace_then_downgrades_keeping_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    studio = await _studio_with_customer(db_session)
    customer = str(studio.stripe_customer_id)
    await _post(client, _sub_event(customer, "active"))
    await _post(
        client,
        {
            "id": f"evt_{uuid.uuid4().hex}",
            "type": "invoice.payment_failed",
            "data": {"object": {"customer": customer}},
        },
    )
    await db_session.refresh(studio)
    assert studio.plan == "pro"
    assert studio.billing_past_due_since is not None
    assert await billing_service.downgrade_overdue_studios(db_session, 7) == []
    later = datetime.now(UTC) + timedelta(days=8)
    assert await billing_service.downgrade_overdue_studios(db_session, 7, now=later) == [studio.id]
    await db_session.commit()
    await db_session.refresh(studio)
    assert (studio.plan, studio.billing_past_due_since, studio.name) == ("free", None, "Atelier")


async def test_payment_recovery_clears_the_grace(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    studio = await _studio_with_customer(db_session)
    customer = str(studio.stripe_customer_id)
    await _post(client, _sub_event(customer, "past_due"))
    await db_session.refresh(studio)
    assert studio.billing_past_due_since is not None
    await _post(client, _sub_event(customer, "active"))
    await db_session.refresh(studio)
    assert (studio.plan, studio.billing_past_due_since) == ("pro", None)


async def test_subscription_deleted_drops_to_free_and_unknown_customer_is_ignored(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    studio = await _studio_with_customer(db_session)
    customer = str(studio.stripe_customer_id)
    await _post(client, _sub_event(customer, "active"))
    deleted = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": customer}},
    }
    assert await _post(client, deleted) == 200
    await db_session.refresh(studio)
    assert studio.plan == "free"
    assert await _post(client, _sub_event("cus_unknown", "active")) == 200
