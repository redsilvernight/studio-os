"""Stripe Checkout and portal (S4-stripe).

Stripe is replaced by an `httpx.MockTransport`: no network, no real key. Pins
the contract: owner only, hosted URL returned, the customer is created once,
the key never leaves the Authorization header, and nothing is written to the
plan by these routes.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from urllib.parse import parse_qs

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api import settings as settings_module
from studio_api.db.models.studio import StudioModel
from studio_api.main import app
from studio_api.services import billing as billing_service
from studio_api.services import provisioning as provisioning_service

SECRET = "sk_test_unit_only_value"


class FakeStripe:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.calls.append((request.url.path, form, dict(request.headers)))
        if self.fail:
            return httpx.Response(402, json={"error": {"type": "card_error", "code": "x"}})
        if request.url.path.endswith("/customers"):
            return httpx.Response(200, json={"id": "cus_test_1"})
        if request.url.path.endswith("/checkout/sessions"):
            return httpx.Response(200, json={"url": "https://checkout.stripe.test/c/1"})
        return httpx.Response(200, json={"url": "https://billing.stripe.test/p/1"})


@pytest.fixture
def stripe(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeStripe]:
    fake = FakeStripe()
    base = settings_module.get_settings()
    patched = base.model_copy(
        update={
            "stripe_secret_key": SecretStr(SECRET),
            "stripe_price_monthly_id": "price_month",
            "stripe_price_annual_id": "price_year",
        }
    )
    monkeypatch.setattr(billing_service, "get_settings", lambda: patched)

    async def _client() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as c:
            yield c

    app.dependency_overrides[billing_service.get_billing_client] = _client
    yield fake
    app.dependency_overrides.pop(billing_service.get_billing_client, None)


async def _owner(client: AsyncClient, db_session: AsyncSession) -> tuple[str, dict[str, str]]:
    user = await provisioning_service.create_user(
        db_session, "Owner", f"{uuid.uuid4()}@example.test", "developer"
    )
    _, token = await provisioning_service.create_machine(db_session, user.id, "m-billing")
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/v1/studios", json={"name": f"Atelier {uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"]), headers


async def test_checkout_creates_customer_once_and_returns_hosted_url(
    client: AsyncClient, db_session: AsyncSession, stripe: FakeStripe
) -> None:
    studio_id, headers = await _owner(client, db_session)
    for _ in range(2):
        response = await client.post(
            f"/api/v1/studios/{studio_id}/billing/checkout",
            json={"interval": "year"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"url": "https://checkout.stripe.test/c/1"}
    paths = [path for path, _, _ in stripe.calls]
    assert paths.count("/v1/customers") == 1
    session_form = next(form for path, form, _ in stripe.calls if path.endswith("/sessions"))
    assert session_form["line_items[0][price]"] == "price_year"
    assert session_form["customer"] == "cus_test_1"
    assert session_form["client_reference_id"] == studio_id
    assert all(h["authorization"] == f"Bearer {SECRET}" for _, _, h in stripe.calls)
    studio = await db_session.get(StudioModel, uuid.UUID(studio_id))
    assert studio is not None
    await db_session.refresh(studio)
    assert studio.stripe_customer_id == "cus_test_1"
    assert studio.plan == "free"  # only a signed webhook changes the plan


async def test_portal_needs_a_customer_then_returns_hosted_url(
    client: AsyncClient, db_session: AsyncSession, stripe: FakeStripe
) -> None:
    studio_id, headers = await _owner(client, db_session)
    url = f"/api/v1/studios/{studio_id}/billing/portal"
    assert (await client.post(url, headers=headers)).status_code == 409
    await client.post(f"/api/v1/studios/{studio_id}/billing/checkout", json={}, headers=headers)
    response = await client.post(url, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"url": "https://billing.stripe.test/p/1"}


async def test_only_the_owner_may_bill(
    client: AsyncClient, db_session: AsyncSession, stripe: FakeStripe
) -> None:
    studio_id, _ = await _owner(client, db_session)
    _, other = await _owner(client, db_session)
    for path in ("checkout", "portal"):
        response = await client.post(
            f"/api/v1/studios/{studio_id}/billing/{path}", json={}, headers=other
        )
        assert response.status_code == 403
    assert stripe.calls == []


async def test_pro_studio_is_sent_to_the_portal(
    client: AsyncClient, db_session: AsyncSession, stripe: FakeStripe
) -> None:
    studio_id, headers = await _owner(client, db_session)
    studio = await db_session.get(StudioModel, uuid.UUID(studio_id))
    assert studio is not None
    studio.plan = "pro"
    await db_session.commit()
    response = await client.post(
        f"/api/v1/studios/{studio_id}/billing/checkout", json={}, headers=headers
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "already_subscribed"


async def test_stripe_failure_is_a_502_without_leaking_the_key(
    client: AsyncClient,
    db_session: AsyncSession,
    stripe: FakeStripe,
    caplog: pytest.LogCaptureFixture,
) -> None:
    studio_id, headers = await _owner(client, db_session)
    stripe.fail = True
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            f"/api/v1/studios/{studio_id}/billing/checkout", json={}, headers=headers
        )
    assert response.status_code == 502
    assert SECRET not in response.text
    assert SECRET not in caplog.text


async def test_billing_is_unavailable_without_a_key(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    unset = settings_module.get_settings().model_copy(update={"stripe_secret_key": None})
    monkeypatch.setattr(billing_service, "get_settings", lambda: unset)
    studio_id, headers = await _owner(client, db_session)
    response = await client.post(
        f"/api/v1/studios/{studio_id}/billing/checkout", json={}, headers=headers
    )
    assert response.status_code == 503
