"""P61b-merge-apply: keep the override, merge it, or revert to the common."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.api.test_library_base_update import _common_rule

RULE = "studio.library.rule/v1"


async def _move_common(
    client: AsyncClient, headers: dict[str, str], common_id: str, text: str
) -> int:
    created = await client.post(
        f"/api/v1/library/{common_id}/versions",
        headers=headers,
        json={"title": "next", "content": {"content_schema": RULE, "text": text}},
    )
    assert created.status_code == 201, created.text
    current = (await client.get(f"/api/v1/library/{common_id}", headers=headers)).json()
    activated = await client.post(
        f"/api/v1/library/{common_id}/activate",
        headers=headers,
        json={
            "version": created.json()["version"],
            "expected_resource_version": current["version"],
        },
    )
    assert activated.status_code == 200
    return int(activated.json()["active_version"])


async def _setup(
    client: AsyncClient, headers: dict[str, str], *, base: str, ours: str, theirs: str
) -> tuple[str, dict[str, Any], int]:
    common_id = await _common_rule(client, headers, "merge-me")
    await client.post(
        f"/api/v1/library/{common_id}/versions",
        headers=headers,
        json={"title": "base", "content": {"content_schema": RULE, "text": base}},
    )
    current = (await client.get(f"/api/v1/library/{common_id}", headers=headers)).json()
    await client.post(
        f"/api/v1/library/{common_id}/activate",
        headers=headers,
        json={"version": 2, "expected_resource_version": current["version"]},
    )
    created = await client.post(
        "/api/v1/library",
        headers=headers,
        json={
            "kind": "rule",
            "stable_key": "merge-me",
            "scope": "user",
            "title": "mine",
            "content": {"content_schema": RULE, "text": ours},
            "derived_from": {"resource_id": common_id, "version": 2},
        },
    )
    assert created.status_code == 201, created.text
    override = (
        await client.post(
            f"/api/v1/library/{created.json()['id']}/activate",
            headers=headers,
            json={"version": 1, "expected_resource_version": created.json()["version"]},
        )
    ).json()
    base_version = await _move_common(client, headers, common_id, theirs)
    return common_id, override, base_version


async def _apply(
    client: AsyncClient, headers: dict[str, str], override: dict[str, Any], **body: Any
) -> Any:
    return await client.post(
        f"/api/v1/library/{override['id']}/merge-apply",
        headers=headers,
        json={"expected_resource_version": override["version"], **body},
    )


async def _versions(
    client: AsyncClient, headers: dict[str, str], override: dict[str, Any]
) -> list[dict[str, Any]]:
    return (await client.get(f"/api/v1/library/{override['id']}/versions", headers=headers)).json()


async def test_keep_override_rebases_without_touching_the_text(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    common_id, override, base = await _setup(
        client, admin_auth_headers, base="a\nb\n", ours="a\nmine\n", theirs="a\ntheirs\n"
    )
    response = await _apply(
        client, admin_auth_headers, override, choice="keep_override", base_active_version=base
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["active_version"] == 2
    assert updated["base_update_available"] is False
    latest = (await _versions(client, admin_auth_headers, override))[-1]
    assert latest["content"]["text"] == "a\nmine\n"
    assert latest["derived_from"] == {"resource_id": common_id, "version": base}


async def test_clean_merge_combines_both_sides(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    common_id, override, base = await _setup(
        client,
        admin_auth_headers,
        base="one\ntwo\nthree\n",
        ours="ONE\ntwo\nthree\n",
        theirs="one\ntwo\nTHREE\n",
    )
    response = await _apply(
        client, admin_auth_headers, override, choice="merge", base_active_version=base
    )
    assert response.status_code == 200, response.text
    latest = (await _versions(client, admin_auth_headers, override))[-1]
    assert latest["content"] == {"content_schema": RULE, "text": "ONE\ntwo\nTHREE\n"}
    assert latest["derived_from"] == {"resource_id": common_id, "version": base}


async def test_conflicting_merge_writes_nothing_until_resolved(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    _, override, base = await _setup(
        client, admin_auth_headers, base="x\n", ours="mine\n", theirs="theirs\n"
    )
    conflict = await _apply(
        client, admin_auth_headers, override, choice="merge", base_active_version=base
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"error_code": "merge_conflict", "conflicts": 1}
    marked = await _apply(
        client,
        admin_auth_headers,
        override,
        choice="merge",
        base_active_version=base,
        content="<<<<<<< ours\nmine\n=======\ntheirs\n>>>>>>> theirs\n",
    )
    assert marked.status_code == 422
    assert marked.json()["detail"]["error_code"] == "unresolved_merge_conflict"
    assert len(await _versions(client, admin_auth_headers, override)) == 1
    unchanged = (
        await client.get(f"/api/v1/library/{override['id']}", headers=admin_auth_headers)
    ).json()
    assert unchanged["version"] == override["version"]
    assert unchanged["base_update_available"] is True

    resolved = await _apply(
        client,
        admin_auth_headers,
        override,
        choice="merge",
        base_active_version=base,
        content="mine and theirs\n",
    )
    assert resolved.status_code == 200, resolved.text
    assert (await _versions(client, admin_auth_headers, override))[-1]["content"][
        "text"
    ] == "mine and theirs\n"


async def test_revert_to_common_deprecates_and_is_restorable(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    _, override, base = await _setup(
        client, admin_auth_headers, base="x\n", ours="mine\n", theirs="theirs\n"
    )
    response = await _apply(
        client, admin_auth_headers, override, choice="revert_to_common", base_active_version=base
    )
    assert response.status_code == 200, response.text
    reverted = response.json()
    assert reverted["status"] == "deprecated"

    restored = await client.post(
        f"/api/v1/library/{override['id']}/activate",
        headers=admin_auth_headers,
        json={"version": 1, "expected_resource_version": reverted["version"]},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"
    assert (await _versions(client, admin_auth_headers, override))[0]["content"]["text"] == "mine\n"


async def test_stale_preview_or_resource_is_rejected_without_writing(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    common_id, override, base = await _setup(
        client, admin_auth_headers, base="x\n", ours="mine\n", theirs="theirs\n"
    )
    newer = await _move_common(client, admin_auth_headers, common_id, "even newer\n")
    moved = await _apply(
        client, admin_auth_headers, override, choice="keep_override", base_active_version=base
    )
    assert moved.status_code == 409
    assert moved.json()["detail"] == {"error_code": "base_moved", "base_active_version": newer}
    stale = await client.post(
        f"/api/v1/library/{override['id']}/merge-apply",
        headers=admin_auth_headers,
        json={
            "choice": "keep_override",
            "expected_resource_version": override["version"] - 1,
            "base_active_version": newer,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["error_code"] == "version_conflict"
    bad = await _apply(
        client,
        admin_auth_headers,
        override,
        choice="keep_override",
        base_active_version=newer,
        content="x",
    )
    assert bad.status_code == 422
    assert len(await _versions(client, admin_auth_headers, override)) == 1


async def test_other_user_cannot_apply(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
) -> None:
    _, override, base = await _setup(
        client, admin_auth_headers, base="x\n", ours="mine\n", theirs="theirs\n"
    )
    response = await _apply(
        client, other_auth_headers, override, choice="keep_override", base_active_version=base
    )
    assert response.status_code == 404
