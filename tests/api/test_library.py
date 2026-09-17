from __future__ import annotations

import uuid

from httpx import AsyncClient
from studio_api.db.models.project import ProjectModel
from studio_contracts.library import (
    CapabilityRequirement,
    RuntimeCapabilities,
    check_compatibility,
)


def _rule_payload(scope: str, key: str = "no-silent-upgrade") -> dict[str, object]:
    return {
        "kind": "rule",
        "stable_key": key,
        "scope": scope,
        "title": "Never upgrade silently",
        "description": "Locked resources keep their version.",
        "content": {
            "content_schema": "studio.library.rule/v1",
            "text": "Do not upgrade a locked resource.",
        },
    }


def _skill_payload(scope: str, key: str = "private-skill") -> dict[str, object]:
    return {
        "kind": "skill",
        "stable_key": key,
        "scope": scope,
        "title": "Private skill",
        "description": None,
        "content": {
            "content_schema": "studio.library.skill/v1",
            "text": "Skill body.",
        },
    }


async def test_create_studio_rule_starts_draft_unactivated(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/library", headers=auth_headers, json=_rule_payload("studio")
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["active_version"] == 0
    assert body["version"] == 1

    versions = await client.get(f"/api/v1/library/{body['id']}/versions", headers=auth_headers)
    assert versions.status_code == 200
    assert [v["version"] for v in versions.json()] == [1]


async def test_create_then_activate_is_two_steps(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (
        await client.post("/api/v1/library", headers=auth_headers, json=_rule_payload("studio"))
    ).json()

    second = await client.post(
        f"/api/v1/library/{created['id']}/versions",
        headers=auth_headers,
        json={
            "title": "v2 title",
            "content": {"content_schema": "studio.library.rule/v1", "text": "v2"},
        },
    )
    assert second.status_code == 201
    assert second.json()["version"] == 2
    still = (await client.get(f"/api/v1/library/{created['id']}", headers=auth_headers)).json()
    assert still["active_version"] == 0

    activated = await client.post(
        f"/api/v1/library/{created['id']}/activate",
        headers=auth_headers,
        json={"version": 2, "expected_resource_version": still["version"]},
    )
    assert activated.status_code == 200
    assert activated.json()["active_version"] == 2
    assert activated.json()["status"] == "active"


async def test_activate_rejects_stale_version(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (
        await client.post("/api/v1/library", headers=auth_headers, json=_rule_payload("studio"))
    ).json()
    await client.post(
        f"/api/v1/library/{created['id']}/activate",
        headers=auth_headers,
        json={"version": 1, "expected_resource_version": 1},
    )
    stale = await client.post(
        f"/api/v1/library/{created['id']}/activate",
        headers=auth_headers,
        json={"version": 1, "expected_resource_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["error_code"] == "version_conflict"
    assert stale.json()["detail"]["server_version"] == 2


async def test_reactivate_active_version_is_noop(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (
        await client.post("/api/v1/library", headers=auth_headers, json=_rule_payload("studio"))
    ).json()
    first = (
        await client.post(
            f"/api/v1/library/{created['id']}/activate",
            headers=auth_headers,
            json={"version": 1, "expected_resource_version": 1},
        )
    ).json()
    again = await client.post(
        f"/api/v1/library/{created['id']}/activate",
        headers=auth_headers,
        json={"version": 1, "expected_resource_version": first["version"]},
    )
    assert again.status_code == 200
    assert again.json()["version"] == first["version"]


async def test_create_replays_on_idempotency_key(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    payload = _rule_payload("studio")
    first = await client.post("/api/v1/library", headers=headers, json=payload)
    second = await client.post("/api/v1/library", headers=headers, json=payload)
    assert first.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_create_rejects_payload_mismatch(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    await client.post("/api/v1/library", headers=headers, json=_rule_payload("studio"))
    other = _rule_payload("studio", key="other-key")
    response = await client.post("/api/v1/library", headers=headers, json=other)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"


async def test_duplicate_stable_key_conflicts(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await client.post("/api/v1/library", headers=auth_headers, json=_rule_payload("studio"))
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/library", headers=auth_headers, json=_rule_payload("studio")
    )
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "duplicate_stable_key"


async def test_studio_create_requires_provisioning_role(
    client: AsyncClient,
    agent_auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
) -> None:
    for headers in (agent_auth_headers, readonly_auth_headers):
        response = await client.post(
            "/api/v1/library", headers=headers, json=_rule_payload("studio")
        )
        assert response.status_code == 403


async def test_user_scope_isolated_without_existence_leak(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
) -> None:
    created = (
        await client.post(
            "/api/v1/library",
            headers=auth_headers,
            json=_skill_payload("user"),
        )
    ).json()

    other_list = await client.get("/api/v1/library", headers=other_auth_headers)
    assert other_list.status_code == 200
    assert all(item["id"] != created["id"] for item in other_list.json())

    other_get = await client.get(f"/api/v1/library/{created['id']}", headers=other_auth_headers)
    assert other_get.status_code == 404

    admin_get = await client.get(f"/api/v1/library/{created['id']}", headers=admin_auth_headers)
    assert admin_get.status_code == 200


async def test_project_scope_create_and_version_event(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    payload = {**_rule_payload("project"), "project_id": str(project.id)}
    created = (await client.post("/api/v1/library", headers=auth_headers, json=payload)).json()
    assert created["project_id"] == str(project.id)

    events = (
        await client.get(
            "/api/v1/events", headers=auth_headers, params={"project_id": str(project.id)}
        )
    ).json()
    assert "library.version.created" in [e["event_type"] for e in events]


async def test_user_scope_mutation_emits_no_event(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    await client.post(
        "/api/v1/library", headers=auth_headers, json=_rule_payload("user", key="quiet-skill")
    )
    events = (
        await client.get(
            "/api/v1/events", headers=auth_headers, params={"project_id": str(project.id)}
        )
    ).json()
    assert [e for e in events if e["event_type"].startswith("library.")] == []


async def test_version_pins_reference_without_duplication(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    rule = (
        await client.post(
            "/api/v1/library", headers=auth_headers, json=_rule_payload("studio", key="base-rule")
        )
    ).json()
    skill = (
        await client.post(
            "/api/v1/library",
            headers=auth_headers,
            json={
                "kind": "skill",
                "stable_key": "uses-base",
                "scope": "studio",
                "title": "Skill on base rule",
                "content": {"content_schema": "studio.library.skill/v1", "text": "skill body"},
                "dependencies": [{"kind": "rule", "stable_key": "base-rule", "version": 1}],
            },
        )
    ).json()
    versions = (
        await client.get(f"/api/v1/library/{skill['id']}/versions", headers=auth_headers)
    ).json()
    assert versions[0]["dependencies"] == [
        {"kind": "rule", "stable_key": "base-rule", "version": 1}
    ]
    assert versions[0]["content"] == {
        "content_schema": "studio.library.skill/v1",
        "text": "skill body",
    }
    assert rule["id"] != skill["id"]


async def test_unknown_pin_is_not_found(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json={
            "kind": "skill",
            "stable_key": "dangling",
            "scope": "studio",
            "title": "Dangling",
            "content": {"content_schema": "studio.library.skill/v1", "text": "Dangling skill."},
            "dependencies": [{"kind": "rule", "stable_key": "missing", "version": 1}],
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "pin_not_found"


async def test_ambiguous_pin_conflicts(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    await client.post(
        "/api/v1/library", headers=auth_headers, json=_rule_payload("studio", key="shared-key")
    )
    await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json={**_rule_payload("project", key="shared-key"), "project_id": str(project.id)},
    )
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json={
            "kind": "skill",
            "stable_key": "needs-disambiguation",
            "scope": "studio",
            "title": "Ambiguous",
            "content": {"content_schema": "studio.library.skill/v1", "text": "Ambiguous skill."},
            "dependencies": [{"kind": "rule", "stable_key": "shared-key", "version": 1}],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "pin_ambiguous"


async def test_readonly_may_list_locks(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    """TECH/04: `readonly` keeps full read access on every GET, locks included."""
    resource = (
        await client.post(
            "/api/v1/library",
            headers=auth_headers,
            json={**_rule_payload("project"), "project_id": str(project.id)},
        )
    ).json()
    await client.post(
        "/api/v1/library-locks",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_id": resource["id"],
            "locked_version": 1,
        },
    )
    listing = await client.get(
        "/api/v1/library-locks",
        headers=readonly_auth_headers,
        params={"project_id": str(project.id)},
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1


async def test_project_lock_lifecycle(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    resource = (
        await client.post(
            "/api/v1/library",
            headers=auth_headers,
            json={**_rule_payload("project"), "project_id": str(project.id)},
        )
    ).json()
    lock = (
        await client.post(
            "/api/v1/library-locks",
            headers=auth_headers,
            json={
                "project_id": str(project.id),
                "resource_id": resource["id"],
                "locked_version": 1,
            },
        )
    ).json()
    assert lock["locked_version"] == 1

    duplicate = await client.post(
        "/api/v1/library-locks",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_id": resource["id"],
            "locked_version": 1,
        },
    )
    assert duplicate.status_code == 409

    foreign_release = await client.delete(
        f"/api/v1/library-locks/{lock['id']}", headers=other_auth_headers
    )
    assert foreign_release.status_code == 403

    released = await client.delete(f"/api/v1/library-locks/{lock['id']}", headers=auth_headers)
    assert released.status_code == 200
    assert released.json()["id"] == lock["id"]


async def test_deprecate_keeps_history_and_is_idempotent(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = (
        await client.post("/api/v1/library", headers=auth_headers, json=_rule_payload("studio"))
    ).json()
    activated = (
        await client.post(
            f"/api/v1/library/{created['id']}/activate",
            headers=auth_headers,
            json={"version": 1, "expected_resource_version": 1},
        )
    ).json()
    deprecated = (
        await client.post(
            f"/api/v1/library/{created['id']}/deprecate",
            headers=auth_headers,
            json={"expected_resource_version": activated["version"]},
        )
    ).json()
    assert deprecated["status"] == "deprecated"
    assert deprecated["active_version"] == 1

    again = await client.post(
        f"/api/v1/library/{created['id']}/deprecate",
        headers=auth_headers,
        json={"expected_resource_version": deprecated["version"]},
    )
    assert again.status_code == 200
    assert again.json()["version"] == deprecated["version"]


async def test_agent_definition_is_not_a_valid_actor(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    """DEC-0062: an `AgentDefinition` id must never satisfy `actor_not_owned`
    paths — only `Agent` provenance is a valid actor."""
    definition = (
        await client.post(
            "/api/v1/library",
            headers=auth_headers,
            json={
                "kind": "agent_definition",
                "stable_key": "godot-debugger",
                "scope": "studio",
                "title": "Godot debugger",
                "content": {
                    "content_schema": "studio.library.agent_definition/v1",
                    "summary": "Debugs Godot projects.",
                },
            },
        )
    ).json()
    assert definition["kind"] == "agent_definition"

    worklog = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "agent_id": definition["id"],
            "summary": "attempted cross-attribution",
        },
    )
    assert worklog.status_code == 409
    assert worklog.json()["detail"]["error_code"] == "actor_not_owned"


def test_capability_unknown_is_not_compatible() -> None:
    requirement = CapabilityRequirement(coding=True, tools_required=["mcp"], reasoning="deep")
    assert check_compatibility(requirement, RuntimeCapabilities()) != []
    assert check_compatibility(CapabilityRequirement(), RuntimeCapabilities()) == []
    satisfied = check_compatibility(
        CapabilityRequirement(coding=True),
        RuntimeCapabilities(coding=True, tools=["mcp"]),
    )
    assert satisfied == []
