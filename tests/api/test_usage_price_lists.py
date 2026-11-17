from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from studio_api.db.models.project import ProjectModel
from studio_contracts.usage import UsagePriceList

PRICE_LISTS = "/api/v1/usage/price-lists"
RATE = {"input": "2", "output": "10", "cache_read": "0.2", "cache_write": "2.5"}


def _grid(price_list_id: str, effective_from: str, **changes: Any) -> dict[str, Any]:
    return {
        "price_list_id": price_list_id,
        "currency": "USD",
        "effective_from": effective_from,
        "models": {"claude-sonnet-5": RATE},
        **changes,
    }


async def _publish(
    client: AsyncClient, headers: dict[str, str], body: dict[str, Any], expected: int = 201
) -> dict[str, Any]:
    response = await client.post(
        PRICE_LISTS, headers={**headers, "Idempotency-Key": str(uuid.uuid4())}, json=body
    )
    assert response.status_code == expected, response.text
    return response.json()


async def _effective(
    client: AsyncClient, headers: dict[str, str], **params: str
) -> UsagePriceList | None:
    response = await client.get(f"{PRICE_LISTS}/effective", headers=headers, params=params)
    if response.status_code == 404:
        assert response.json()["detail"]["error_code"] == "price_list_not_found"
        return None
    assert response.status_code == 200, response.text
    return UsagePriceList.model_validate(response.json())


async def test_effective_list_prefers_the_project_then_the_latest_global(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    project_id = str(project.id)
    suffix = uuid.uuid4().hex[:8]
    assert await _effective(client, auth_headers, project_id=project_id) is None

    await _publish(client, admin_auth_headers, _grid(f"g1-{suffix}", "2026-10-01T00:00:00Z"))
    await _publish(client, admin_auth_headers, _grid(f"g2-{suffix}", "2026-11-01T00:00:00Z"))
    await _publish(client, admin_auth_headers, _grid(f"future-{suffix}", "2099-01-01T00:00:00Z"))
    current = await _effective(client, auth_headers, project_id=project_id)
    assert current is not None and current.price_list_id == f"g2-{suffix}"
    past = await _effective(client, auth_headers, at="2026-10-15T00:00:00Z")
    assert past is not None and past.price_list_id == f"g1-{suffix}"

    own = _grid(f"p1-{suffix}", "2026-09-01T00:00:00Z", project_id=project_id, currency="EUR")
    created = await _publish(client, auth_headers, own)
    assert created["models"]["claude-sonnet-5"]["output"] == "10"
    scoped = await _effective(client, auth_headers, project_id=project_id)
    assert scoped is not None and scoped.price_list_id == f"p1-{suffix}"
    assert scoped.currency == "EUR"
    assert scoped.pricing_ref().price_list_id == f"p1-{suffix}"

    listed = await client.get(PRICE_LISTS, headers=auth_headers, params={"project_id": project_id})
    ids = [item["price_list_id"] for item in listed.json()]
    assert f"p1-{suffix}" in ids and f"g2-{suffix}" in ids
    globals_only = await client.get(PRICE_LISTS, headers=auth_headers)
    assert f"p1-{suffix}" not in [item["price_list_id"] for item in globals_only.json()]


async def test_lists_are_immutable_and_publishing_is_reserved(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    auth_headers: dict[str, str],
    agent_auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    global_grid = _grid(f"g-{suffix}", "2026-11-01T00:00:00Z")
    await _publish(client, auth_headers, global_grid, expected=403)
    await _publish(client, agent_auth_headers, global_grid, expected=403)
    project_grid = _grid(f"p-{suffix}", "2026-11-01T00:00:00Z", project_id=str(project.id))
    await _publish(client, agent_auth_headers, project_grid, expected=403)
    await _publish(client, readonly_auth_headers, project_grid, expected=403)

    await _publish(client, admin_auth_headers, global_grid)
    duplicate = await _publish(client, admin_auth_headers, global_grid, expected=409)
    assert duplicate["detail"]["error_code"] == "price_list_conflict"

    unknown = _grid(f"u-{suffix}", "2026-11-01T00:00:00Z", project_id=str(uuid.uuid4()))
    await _publish(client, admin_auth_headers, unknown, expected=404)


async def test_idempotent_publish_replays_the_same_list(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    body = _grid(f"idem-{uuid.uuid4().hex[:8]}", "2026-11-01T00:00:00Z")
    headers = {**admin_auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    first = await client.post(PRICE_LISTS, headers=headers, json=body)
    second = await client.post(PRICE_LISTS, headers=headers, json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_invalid_grids_are_rejected(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    suffix = uuid.uuid4().hex[:8]
    for body in (
        _grid(f"a-{suffix}", "2026-11-01T00:00:00Z", models={}),
        _grid(f"b-{suffix}", "2026-11-01T00:00:00Z", currency="usd"),
        _grid(f"c-{suffix}", "2026-11-01T00:00:00"),
        _grid(f"d-{suffix}", "2026-11-01T00:00:00Z", models={"Claude": RATE}),
        _grid(f"e-{suffix}", "2026-11-01T00:00:00Z", models={"x": {**RATE, "input": "-1"}}),
    ):
        await _publish(client, admin_auth_headers, body, expected=422)
