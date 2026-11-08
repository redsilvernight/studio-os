"""P11-scale: batch read of exact library versions (additive)."""

from __future__ import annotations

from httpx import AsyncClient


def _rule_payload(scope: str, key: str) -> dict[str, object]:
    return {
        "kind": "rule",
        "stable_key": key,
        "scope": scope,
        "title": f"title {key}",
        "description": None,
        "content": {
            "content_schema": "studio.library.rule/v1",
            "text": f"body {key}",
        },
    }


async def test_versions_batch_returns_exact_rows_and_skips_unknown(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = (
        await client.post("/api/v1/library", headers=auth_headers, json=_rule_payload("studio", "batch-a"))
    ).json()
    second = (
        await client.post("/api/v1/library", headers=auth_headers, json=_rule_payload("studio", "batch-b"))
    ).json()
    for resource in (first, second):
        await client.post(
            f"/api/v1/library/{resource['id']}/activate",
            headers=auth_headers,
            json={"version": 1, "expected_resource_version": resource["version"]},
        )

    response = await client.post(
        "/api/v1/library/versions/batch",
        headers=auth_headers,
        json={
            "requests": [
                {"resource_id": first["id"], "version": 1},
                {"resource_id": second["id"], "version": 1},
                {"resource_id": second["id"], "version": 99},
                {"resource_id": "00000000-0000-0000-0000-000000000000", "version": 1},
            ]
        },
    )
    assert response.status_code == 200
    rows = response.json()
    assert {(row["resource_id"], row["version"]) for row in rows} == {
        (first["id"], 1),
        (second["id"], 1),
    }
    assert all(row["title"].startswith("title batch-") for row in rows)


async def test_versions_batch_rejects_empty_and_too_many(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    empty = await client.post(
        "/api/v1/library/versions/batch", headers=auth_headers, json={"requests": []}
    )
    assert empty.status_code == 422

    too_many = await client.post(
        "/api/v1/library/versions/batch",
        headers=auth_headers,
        json={
            "requests": [
                {"resource_id": "00000000-0000-0000-0000-000000000000", "version": 1}
                for _ in range(501)
            ]
        },
    )
    assert too_many.status_code == 422
