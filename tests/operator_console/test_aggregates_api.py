from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.operator_console.conftest import EMAIL
from tests.operator_console.fakes import ATELIER, FakeRepository


async def test_dashboard_exposes_health_and_phase_m_measures(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/dashboard", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active_studios"] == 2
    assert body["storage"]["percent"] == 72.3
    assert [service["key"] for service in body["services"]] == ["api", "database"]
    assert body["alerts"][0]["level"] == "warning"
    assert body["error_rate_5xx_24h"] == 0.2
    assert body["api_latency_p50_ms"] == 120
    # Billing is not deployed: absent, never a fabricated figure.
    assert body["unpaid_in_grace"] is None


async def test_measures_return_phase_m_series(
    client: AsyncClient, repository: FakeRepository, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/measures", params={"days": 7}, headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window_days"] == 7
    assert body["series"][0]["metric"] == "storage_bytes"
    assert repository.days[-1] == 7


async def test_measures_refuse_an_out_of_range_window(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/measures", params={"days": 365}, headers=auth_headers)
    assert response.status_code == 422


async def test_usage_aggregates_by_studio_and_globally(
    client: AsyncClient, repository: FakeRepository, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/usage", params={"days": 30}, headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window_days"] == 30
    assert body["studios"] == 3
    assert body["totals"]["tokens_in"] == 300
    assert body["totals"]["costs"] == [{"currency": "EUR", "amount": "3.75"}]
    assert body["api_calls"] == 4_200_000
    assert len(body["top_studios"]) == 3
    assert body["over_quota"][0]["name"] == "Atelier Phare"
    assert repository.days[-1] == 30


async def test_billing_is_reported_unavailable_not_faked(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/billing", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is False
    assert body["reason_code"] == "billing_not_deployed"
    assert "S4" in body["message"]
    # No subscription, invoice or webhook payload field exists.
    assert set(body) == {"available", "reason_code", "message"}


async def test_break_glass_queue_lists_requests_and_status(
    client: AsyncClient, repository: FakeRepository, auth_headers: dict[str, str]
) -> None:
    empty = await client.get("/api/v1/break-glass", headers=auth_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"total": 0, "requests": []}

    created = await client.post(
        "/api/v1/break-glass",
        json={
            "studio_id": str(ATELIER),
            "reason": "Incident support 42",
            "scope": "metadata",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "requested"
    assert body["studio_name"] == "Atelier Phare"
    assert body["operator_ref"] == EMAIL
    assert set(body) == {
        "id",
        "studio_id",
        "studio_name",
        "operator_ref",
        "reason",
        "scope",
        "status",
        "requested_at",
        "decided_at",
        "expires_at",
    }

    queue = await client.get("/api/v1/break-glass", headers=auth_headers)
    assert queue.status_code == 200, queue.text
    assert queue.json()["total"] == 1
    assert queue.json()["requests"][0]["status"] == "requested"


async def test_break_glass_request_validates_studio_reason_and_scope(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    unknown = await client.post(
        "/api/v1/break-glass",
        json={"studio_id": str(uuid.uuid4()), "reason": "Incident 7", "scope": "metadata"},
        headers=auth_headers,
    )
    assert unknown.status_code == 404

    blank = await client.post(
        "/api/v1/break-glass",
        json={"studio_id": str(ATELIER), "reason": "   ", "scope": "metadata"},
        headers=auth_headers,
    )
    assert blank.status_code == 422
    assert blank.json()["detail"]["error_code"] == "break_glass_reason_required"

    content_scope = await client.post(
        "/api/v1/break-glass",
        json={"studio_id": str(ATELIER), "reason": "Incident 7", "scope": "content"},
        headers=auth_headers,
    )
    assert content_scope.status_code == 422


async def test_break_glass_requires_the_console_token(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/break-glass")).status_code == 401
    assert (
        await client.post(
            "/api/v1/break-glass",
            json={"studio_id": str(ATELIER), "reason": "Incident 7", "scope": "metadata"},
        )
    ).status_code == 401
