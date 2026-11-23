from __future__ import annotations

from httpx import AsyncClient

from tests.operator_console.fakes import FakeRepository


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


async def test_break_glass_is_out_of_scope_and_reads_nothing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/break-glass", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is False
    assert body["reason_code"] == "break_glass_not_deployed"
    assert set(body) == {"available", "reason_code", "message"}
