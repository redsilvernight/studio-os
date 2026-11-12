"""P60-alert: an override owner is warned when the common base moved.

The alert is a read-only projection: it never re-bases the override, never
copies the new common content and never touches another user's resources.
"""

from __future__ import annotations

from httpx import AsyncClient


def _rule_payload(scope: str, key: str, text: str) -> dict[str, object]:
    return {
        "kind": "rule",
        "stable_key": key,
        "scope": scope,
        "title": f"{key} title",
        "content": {"content_schema": "studio.library.rule/v1", "text": text},
    }


async def _common_rule(client: AsyncClient, headers: dict[str, str], key: str) -> str:
    created = (
        await client.post(
            "/api/v1/library", headers=headers, json=_rule_payload("studio", key, "base")
        )
    ).json()
    activated = await client.post(
        f"/api/v1/library/{created['id']}/activate",
        headers=headers,
        json={"version": 1, "expected_resource_version": created["version"]},
    )
    assert activated.status_code == 200
    return created["id"]


async def _override(
    client: AsyncClient, headers: dict[str, str], common_id: str, key: str
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/library",
        headers=headers,
        json={
            **_rule_payload("user", key, "my override"),
            "derived_from": {"resource_id": common_id, "version": 1},
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    activated = await client.post(
        f"/api/v1/library/{created['id']}/activate",
        headers=headers,
        json={"version": 1, "expected_resource_version": created["version"]},
    )
    assert activated.status_code == 200
    return activated.json()


async def test_owner_is_alerted_when_common_moves_without_any_auto_apply(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    common_id = await _common_rule(client, admin_auth_headers, "shared-base")
    override = await _override(client, admin_auth_headers, common_id, "shared-base")
    assert override["base_update_available"] is False
    assert override["base_active_version"] is None

    # The common gains v2 and activates it: the override's base is now stale.
    second = await client.post(
        f"/api/v1/library/{common_id}/versions",
        headers=admin_auth_headers,
        json={
            "title": "common v2",
            "content": {"content_schema": "studio.library.rule/v1", "text": "new base"},
        },
    )
    assert second.status_code == 201
    current = (await client.get(f"/api/v1/library/{common_id}", headers=admin_auth_headers)).json()
    activated = await client.post(
        f"/api/v1/library/{common_id}/activate",
        headers=admin_auth_headers,
        json={"version": 2, "expected_resource_version": current["version"]},
    )
    assert activated.status_code == 200

    detail = (
        await client.get(f"/api/v1/library/{override['id']}", headers=admin_auth_headers)
    ).json()
    assert detail["base_update_available"] is True
    assert detail["base_active_version"] == 2

    listed = (
        await client.get(
            "/api/v1/library", headers=admin_auth_headers, params={"scope": "user"}
        )
    ).json()
    flagged = [item for item in listed if item["id"] == override["id"]]
    assert len(flagged) == 1
    assert flagged[0]["base_update_available"] is True
    assert flagged[0]["base_active_version"] == 2

    # Information only: repeated reads neither move the pointer nor import the
    # new common content, and no extra version is created.
    for _ in range(3):
        again = (
            await client.get(f"/api/v1/library/{override['id']}", headers=admin_auth_headers)
        ).json()
        assert again["active_version"] == 1
        assert again["status"] == "active"
    versions = (
        await client.get(
            f"/api/v1/library/{override['id']}/versions", headers=admin_auth_headers
        )
    ).json()
    assert len(versions) == 1
    assert versions[0]["content"]["text"] == "my override"
    assert versions[0]["derived_from"] == {"resource_id": common_id, "version": 1}


async def test_other_user_is_never_alerted_about_someone_elses_override(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    common_id = await _common_rule(client, admin_auth_headers, "shared-base")
    override = await _override(client, admin_auth_headers, common_id, "shared-base")
    second = await client.post(
        f"/api/v1/library/{common_id}/versions",
        headers=admin_auth_headers,
        json={"title": "v2", "content": {"content_schema": "studio.library.rule/v1", "text": "v2"}},
    )
    assert second.status_code == 201
    current = (await client.get(f"/api/v1/library/{common_id}", headers=admin_auth_headers)).json()
    await client.post(
        f"/api/v1/library/{common_id}/activate",
        headers=admin_auth_headers,
        json={"version": 2, "expected_resource_version": current["version"]},
    )

    # The override (and therefore its alert) does not exist for another user.
    assert (
        await client.get(f"/api/v1/library/{override['id']}", headers=other_auth_headers)
    ).status_code == 404
    listed = (await client.get("/api/v1/library", headers=other_auth_headers)).json()
    assert all(item["id"] != override["id"] for item in listed)


async def test_current_base_raises_no_alert(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    common_id = await _common_rule(client, admin_auth_headers, "shared-base")
    override = await _override(client, admin_auth_headers, common_id, "shared-base")

    detail = (
        await client.get(f"/api/v1/library/{override['id']}", headers=admin_auth_headers)
    ).json()
    assert detail["base_update_available"] is False
    assert detail["base_active_version"] is None
