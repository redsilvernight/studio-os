from __future__ import annotations

from copy import deepcopy

from httpx import AsyncClient

from tests.api.test_library_bindings import _create, _payload

URL = "/api/v1/resolutions/work-profile-pack"


async def _activate(
    client: AsyncClient, headers: dict[str, str], resource: dict[str, object]
) -> None:
    result = await client.post(
        f"/api/v1/library/{resource['id']}/activate",
        headers=headers,
        json={"version": 1, "expected_resource_version": resource["version"]},
    )
    assert result.status_code == 200, result.text


async def test_pack_preview_composes_without_publication_and_respects_user_visibility(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    base = await _create(client, auth_headers, _payload("agent_definition", "pack-base"))
    await _activate(client, auth_headers, base)
    base_pin = {
        "resource_id": base["id"],
        "kind": "agent_definition",
        "stable_key": "pack-base",
        "version": 1,
    }
    adaptation = await _create(
        client,
        auth_headers,
        _payload("agent_definition", "pack-base", scope="user", dependencies=[base_pin]),
    )
    await _activate(client, auth_headers, adaptation)
    binding = await client.post(
        "/api/v1/runtime-bindings",
        headers=auth_headers,
        json={
            "level": "user",
            "target_kind": "agent_definition",
            "target_stable_key": "pack-base",
            "target": {"harness_ref": "codex", "model_ref": "test-model"},
        },
    )
    assert binding.status_code == 201, binding.text
    pack = {
        "format": "studio.work-profile-pack/v1",
        "profile": {
            "stable_key": "example",
            "title": "Example",
            "agent_stable_key": "pack-base",
            "permissions": ["read"],
        },
        "base": base_pin,
        "adaptations": [{**base_pin, "resource_id": adaptation["id"]}],
    }
    request = {
        "pack": pack,
        "machine_policy": {
            "opt_in": True,
            "max_concurrent": 1,
            "allowed_harnesses": ["codex"],
            "permissions": ["read"],
        },
    }
    before = (await client.get("/api/v1/library", headers=auth_headers)).json()
    response = await client.post(URL, headers=auth_headers, json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["accepted"] is True
    assert result["mutates"] is result["authoritative"] is False
    assert result["issues"] == []
    assert {row["resource_id"] for row in result["observed"]} == {base["id"], adaptation["id"]}
    assert (await client.get("/api/v1/library", headers=auth_headers)).json() == before
    denied = await client.post(URL, headers=other_auth_headers, json=request)
    assert denied.status_code == 404
    assert denied.json()["detail"]["error_code"] == "pin_not_found"
    other_request = deepcopy(request)
    other_request["pack"]["adaptations"] = []
    other_preview = await client.post(URL, headers=other_auth_headers, json=other_request)
    assert other_preview.status_code == 200, other_preview.text
    assert other_preview.json()["issues"] == []
    assert [row["resource_id"] for row in other_preview.json()["observed"]] == [base["id"]]
    changed = deepcopy(request)
    changed["pack"]["adaptations"] = []
    mismatch = await client.post(URL, headers=auth_headers, json=changed)
    assert mismatch.status_code == 200, mismatch.text
    assert mismatch.json()["accepted"] is False
    assert mismatch.json()["issues"] == ["composition_mismatch"]
    changed = deepcopy(request)
    changed["machine_policy"]["permissions"] = []
    capped = await client.post(URL, headers=auth_headers, json=changed)
    assert capped.status_code == 200
    assert capped.json()["accepted"] is False
    assert capped.json()["profile"]["effective_permissions"] == []
    changed["pack"]["format"] = "studio.work-profile-pack/v99"
    assert (await client.post(URL, headers=auth_headers, json=changed)).status_code == 422
