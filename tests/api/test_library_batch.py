from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from studio_api.db.models.project import ProjectModel
from studio_contracts.library import LibraryVersionBatchGet

URL = "/api/v1/library/versions/batch-get"


def _payload(key: str, scope: str = "studio") -> dict[str, object]:
    return {
        "kind": "rule",
        "stable_key": key,
        "scope": scope,
        "title": key,
        "content": {"content_schema": "studio.library.rule/v1", "text": f"Body of {key}."},
    }


async def _create(
    client: AsyncClient, headers: dict[str, str], key: str, **extra: object
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/library", headers=headers, json={**_payload(key, **extra)}
    )
    assert response.status_code == 201
    return response.json()


def _ref(resource_id: object, version: int = 1) -> dict[str, object]:
    return {"resource_id": str(resource_id), "version": version}


async def test_batch_mixes_ok_and_not_found_in_request_order(
    client: AsyncClient, auth_headers: dict[str, str], admin_auth_headers: dict[str, str]
) -> None:
    first = await _create(client, admin_auth_headers, "batch-a")
    second = await _create(client, admin_auth_headers, "batch-b")
    items = [_ref(second["id"]), _ref(first["id"], 9), _ref(uuid.uuid4()), _ref(first["id"])]
    response = await client.post(URL, headers=auth_headers, json={"items": items})
    assert response.status_code == 200
    result = response.json()["items"]
    assert [(i["resource_id"], i["version"], i["status"]) for i in result] == [
        (second["id"], 1, "ok"),
        (first["id"], 9, "not_found"),
        (items[2]["resource_id"], 1, "not_found"),
        (first["id"], 1, "ok"),
    ]
    assert result[0]["detail"]["title"] == "batch-b"
    assert result[1]["detail"] is None


async def test_batch_deduplicates_requested_pairs(
    client: AsyncClient, auth_headers: dict[str, str], admin_auth_headers: dict[str, str]
) -> None:
    resource = await _create(client, admin_auth_headers, "batch-dup")
    response = await client.post(
        URL, headers=auth_headers, json={"items": [_ref(resource["id"])] * 3}
    )
    assert response.status_code == 200
    assert [i["status"] for i in response.json()["items"]] == ["ok"] * 3


async def test_batch_masks_another_users_private_resource(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
) -> None:
    private = await _create(client, auth_headers, "batch-private", scope="user")
    body = {"items": [_ref(private["id"]), _ref(uuid.uuid4())]}
    other = await client.post(URL, headers=other_auth_headers, json=body)
    assert other.status_code == 200
    assert [i["status"] for i in other.json()["items"]] == ["not_found", "not_found"]
    assert all(i["detail"] is None for i in other.json()["items"])
    owner = await client.post(URL, headers=auth_headers, json=body)
    assert owner.json()["items"][0]["status"] == "ok"
    admin = await client.post(URL, headers=admin_auth_headers, json=body)
    assert admin.json()["items"][0]["status"] == "ok"


@pytest.mark.isolation
async def test_batch_forbids_the_whole_batch_for_an_unreadable_project(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    mine = await _create(client, auth_headers, "batch-mine", scope="user")
    scoped = (
        await client.post(
            "/api/v1/library",
            headers=admin_auth_headers,
            json={**_payload("batch-scoped", "project"), "project_id": str(project.id)},
        )
    ).json()
    response = await client.post(
        URL,
        headers=auth_headers,
        json={"items": [_ref(mine["id"]), _ref(scoped["id"])]},
    )
    assert response.status_code == 403
    only_mine = await client.post(URL, headers=auth_headers, json={"items": [_ref(mine["id"])]})
    assert only_mine.status_code == 200


async def test_batch_bounds_and_auth(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    too_many = {"items": [_ref(uuid.uuid4()) for _ in range(501)]}
    assert (await client.post(URL, headers=auth_headers, json=too_many)).status_code == 422
    assert (await client.post(URL, headers=auth_headers, json={"items": []})).status_code == 422
    bad_version = {"items": [_ref(uuid.uuid4(), 0)]}
    assert (await client.post(URL, headers=auth_headers, json=bad_version)).status_code == 422
    exact = {"items": [_ref(uuid.uuid4()) for _ in range(500)]}
    assert (await client.post(URL, headers=auth_headers, json=exact)).status_code == 200
    assert (await client.post(URL, json=exact)).status_code == 401


def test_batch_contract_bounds() -> None:
    ref = {"resource_id": str(uuid.uuid4()), "version": 1}
    assert len(LibraryVersionBatchGet.model_validate({"items": [ref] * 500}).items) == 500
    for items in ([], [ref] * 501, [{**ref, "version": 0}], [{**ref, "extra": 1}]):
        with pytest.raises(ValidationError):
            LibraryVersionBatchGet.model_validate({"items": items})
    with pytest.raises(ValidationError):
        LibraryVersionBatchGet.model_validate({"items": [ref], "extra": 1})


async def test_batch_serves_200_versions_in_one_request(
    client: AsyncClient, auth_headers: dict[str, str], admin_auth_headers: dict[str, str]
) -> None:
    """P11-scale: a 200-resource sync needs one batch call, not one per 50."""
    first = await _create(client, admin_auth_headers, "batch-200")
    items = [_ref(first["id"])] + [_ref(uuid.uuid4()) for _ in range(199)]
    response = await client.post(URL, headers=auth_headers, json={"items": items})
    assert response.status_code == 200
    result = response.json()["items"]
    assert len(result) == 200
    assert result[0]["status"] == "ok"
    assert {i["status"] for i in result[1:]} == {"not_found"}
