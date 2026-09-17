from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import library as library_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.library import (
    BindingRelation,
    DependencyPin,
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
    binding_relation_for,
    binding_scope_allows,
)


def _rule_content(text: str = "Follow the checklist.") -> dict[str, object]:
    return {"content_schema": "studio.library.rule/v1", "text": text}


def _skill_content(text: str = "Skill body.") -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": text}


def _profile_content() -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": {"coding": True},
        "description": "Fictional profile for provider_a/model_a.",
    }


def _agent_content() -> dict[str, object]:
    return {
        "content_schema": "studio.library.agent_definition/v1",
        "summary": "Fictional helper.",
        "intended_use": "Exercises.",
    }


def _workflow_content(agent_key: str) -> dict[str, object]:
    """Minimal P11-valid workflow: one participant composing `agent_key`
    (the matching `composes_agent` pin is added by the caller)."""
    return {
        "content_schema": "studio.library.workflow/v1",
        "participants": [
            {
                "participant_id": "worker",
                "agent_stable_key": agent_key,
                "outputs": [{"name": "result"}],
            }
        ],
        "outputs": [{"name": "result", "source": {"participant_id": "worker", "name": "result"}}],
    }


_CONTENTS = {
    "rule": _rule_content(),
    "skill": _skill_content(),
    "model_profile": _profile_content(),
    "agent_definition": _agent_content(),
}


def _payload(
    kind: str,
    key: str,
    scope: str = "studio",
    dependencies: list[dict[str, object]] | None = None,
    project_id: object = None,
    content: dict[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "kind": kind,
        "stable_key": key,
        "scope": scope,
        "title": f"{key} title",
        "content": content if content is not None else _CONTENTS[kind],
        "dependencies": dependencies or [],
    }
    if project_id is not None:
        body["project_id"] = str(project_id)
    return body


async def _create(
    client: AsyncClient, headers: dict[str, str], payload: dict[str, object]
) -> dict[str, object]:
    response = await client.post("/api/v1/library", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _pin(kind: str, key: str, version: int = 1, relation: str | None = None) -> dict[str, object]:
    pin: dict[str, object] = {"kind": kind, "stable_key": key, "version": version}
    if relation is not None:
        pin["relation"] = relation
    return pin


# --- Matrix as pure contract -----------------------------------------------


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        ("agent_definition", "rule", BindingRelation.APPLIES_RULE),
        ("agent_definition", "skill", BindingRelation.USES_SKILL),
        ("agent_definition", "model_profile", BindingRelation.REQUIRES_MODEL_PROFILE),
        ("agent_definition", "agent_definition", BindingRelation.COMPOSES_AGENT),
        ("agent_definition", "workflow", BindingRelation.REFERENCES_WORKFLOW),
        ("skill", "rule", BindingRelation.REFINES_SKILL_RULE),
        ("workflow", "rule", BindingRelation.APPLIES_RULE),
        ("workflow", "skill", BindingRelation.USES_SKILL),
        ("workflow", "agent_definition", BindingRelation.COMPOSES_AGENT),
    ],
)
def test_matrix_allowed_couples(source: str, target: str, expected: BindingRelation) -> None:
    assert binding_relation_for(LibraryKind(source), LibraryKind(target)) == expected


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("rule", "rule"),
        ("rule", "skill"),
        ("rule", "agent_definition"),
        ("rule", "model_profile"),
        ("rule", "workflow"),
        ("model_profile", "rule"),
        ("model_profile", "skill"),
        ("model_profile", "agent_definition"),
        ("model_profile", "model_profile"),
        ("model_profile", "workflow"),
        ("skill", "skill"),
        ("skill", "model_profile"),
        ("skill", "agent_definition"),
        ("skill", "workflow"),
        ("agent_definition", "agent_definition_missing"),
    ],
)
def test_matrix_forbidden_couples(source: str, target: str) -> None:
    if target == "agent_definition_missing":
        assert (
            binding_relation_for(LibraryKind(source), LibraryKind.AGENT_DEFINITION)
            == BindingRelation.COMPOSES_AGENT
        )
        return
    assert binding_relation_for(LibraryKind(source), LibraryKind(target)) is None


def test_scope_rule_shared_never_binds_private() -> None:
    owner_a = "11111111-1111-4111-8111-111111111111"
    owner_b = "22222222-2222-4222-8222-222222222222"
    assert binding_scope_allows(LibraryScope.STUDIO, owner_a, LibraryScope.STUDIO, owner_a)
    assert binding_scope_allows(LibraryScope.USER, owner_a, LibraryScope.STUDIO, None)
    assert binding_scope_allows(LibraryScope.USER, owner_a, LibraryScope.USER, owner_a)
    assert not binding_scope_allows(LibraryScope.USER, owner_a, LibraryScope.USER, owner_b)
    assert not binding_scope_allows(LibraryScope.STUDIO, owner_a, LibraryScope.USER, owner_a)
    assert not binding_scope_allows(LibraryScope.PROJECT, owner_a, LibraryScope.USER, owner_a)
    assert binding_scope_allows(LibraryScope.PROJECT, owner_a, LibraryScope.STUDIO, None)


# --- Valid relations --------------------------------------------------------


async def test_agent_binds_all_five_kinds(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("rule", "p5-rule"))
    await _create(client, auth_headers, _payload("skill", "p5-skill"))
    await _create(client, auth_headers, _payload("model_profile", "p5-profile"))
    await _create(client, auth_headers, _payload("agent_definition", "p5-peer"))
    await _create(
        client,
        auth_headers,
        _payload(
            "workflow",
            "p5-flow",
            content=_workflow_content("p5-peer"),
            dependencies=[_pin("agent_definition", "p5-peer")],
        ),
    )
    agent = await _create(
        client,
        auth_headers,
        _payload(
            "agent_definition",
            "p5-agent",
            dependencies=[
                _pin("rule", "p5-rule"),
                _pin("skill", "p5-skill", relation="uses_skill"),
                _pin("model_profile", "p5-profile"),
                _pin("agent_definition", "p5-peer"),
                _pin("workflow", "p5-flow"),
            ],
        ),
    )
    versions = (
        await client.get(f"/api/v1/library/{agent['id']}/versions", headers=auth_headers)
    ).json()
    relations = {d["stable_key"]: d["relation"] for d in versions[0]["dependencies"]}
    assert relations == {
        "p5-rule": "applies_rule",
        "p5-skill": "uses_skill",
        "p5-profile": "requires_model_profile",
        "p5-peer": "composes_agent",
        "p5-flow": "references_workflow",
    }


async def test_skill_refines_rule_and_workflow_binds(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("rule", "p5-w-rule"))
    await _create(client, auth_headers, _payload("agent_definition", "p5-w-agent"))
    skill = await _create(
        client,
        auth_headers,
        _payload("skill", "p5-w-skill", dependencies=[_pin("rule", "p5-w-rule")]),
    )
    versions = (
        await client.get(f"/api/v1/library/{skill['id']}/versions", headers=auth_headers)
    ).json()
    assert versions[0]["dependencies"][0]["relation"] == "refines_skill_rule"
    flow = await _create(
        client,
        auth_headers,
        _payload(
            "workflow",
            "p5-w-flow",
            content=_workflow_content("p5-w-agent"),
            dependencies=[
                _pin("rule", "p5-w-rule"),
                _pin("skill", "p5-w-skill"),
                _pin("agent_definition", "p5-w-agent"),
            ],
        ),
    )
    flow_versions = (
        await client.get(f"/api/v1/library/{flow['id']}/versions", headers=auth_headers)
    ).json()
    assert {d["relation"] for d in flow_versions[0]["dependencies"]} == {
        "applies_rule",
        "uses_skill",
        "composes_agent",
    }


async def test_workflow_binds_agent_definition(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("agent_definition", "p5-f-agent"))
    flow = await _create(
        client,
        auth_headers,
        _payload(
            "workflow",
            "p5-f-flow",
            content=_workflow_content("p5-f-agent"),
            dependencies=[_pin("agent_definition", "p5-f-agent")],
        ),
    )
    versions = (
        await client.get(f"/api/v1/library/{flow['id']}/versions", headers=auth_headers)
    ).json()
    assert versions[0]["dependencies"][0]["relation"] == "composes_agent"


# --- Invalid relations ------------------------------------------------------


async def test_rule_cannot_source_binding(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("skill", "p5-r-target"))
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json=_payload("rule", "p5-r-source", dependencies=[_pin("skill", "p5-r-target")]),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_binding"


async def test_model_profile_cannot_source_binding(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("rule", "p5-m-target"))
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json=_payload("model_profile", "p5-m-source", dependencies=[_pin("rule", "p5-m-target")]),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_binding"


async def test_skill_cannot_bind_model_profile(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("model_profile", "p5-s-target"))
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json=_payload("skill", "p5-s-source", dependencies=[_pin("model_profile", "p5-s-target")]),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_binding"


async def test_wrong_relation_for_allowed_couple_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("skill", "p5-x-skill"))
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json=_payload(
            "agent_definition",
            "p5-x-agent",
            dependencies=[_pin("skill", "p5-x-skill", relation="applies_rule")],
        ),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "invalid_binding"
    assert detail["reason"] == "relation_mismatch"


async def test_unknown_relation_string_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("skill", "p5-u-skill"))
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json=_payload(
            "agent_definition",
            "p5-u-agent",
            dependencies=[_pin("skill", "p5-u-skill", relation="teleports_to")],
        ),
    )
    assert response.status_code == 422


# --- Cardinality ------------------------------------------------------------


async def test_agent_zero_or_one_model_profile(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    bare = await _create(client, auth_headers, _payload("agent_definition", "p5-c-bare"))
    assert bare["kind"] == "agent_definition"
    await _create(client, auth_headers, _payload("model_profile", "p5-c-profile"))
    single = await _create(
        client,
        auth_headers,
        _payload(
            "agent_definition", "p5-c-single", dependencies=[_pin("model_profile", "p5-c-profile")]
        ),
    )
    assert single["kind"] == "agent_definition"


async def test_agent_two_model_profiles_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("model_profile", "p5-c2-a"))
    await _create(client, auth_headers, _payload("model_profile", "p5-c2-b"))
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json=_payload(
            "agent_definition",
            "p5-c2-agent",
            dependencies=[
                _pin("model_profile", "p5-c2-a"),
                _pin("model_profile", "p5-c2-b"),
            ],
        ),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "invalid_binding"
    assert detail["reason"] == "too_many_model_profiles"


# --- Version pinning --------------------------------------------------------


async def test_pin_stays_on_old_version(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await _create(client, auth_headers, _payload("skill", "p5-v-skill"))
    agent = await _create(
        client,
        auth_headers,
        _payload("agent_definition", "p5-v-agent", dependencies=[_pin("skill", "p5-v-skill")]),
    )
    created_skill = (
        await client.get("/api/v1/library", headers=auth_headers, params={"kind": "skill"})
    ).json()
    skill_id = next(r["id"] for r in created_skill if r["stable_key"] == "p5-v-skill")
    second = await client.post(
        f"/api/v1/library/{skill_id}/versions",
        headers=auth_headers,
        json={"title": "v2", "content": _skill_content("Skill body v2.")},
    )
    assert second.status_code == 201, second.text
    versions = (
        await client.get(f"/api/v1/library/{agent['id']}/versions", headers=auth_headers)
    ).json()
    assert versions[0]["dependencies"] == [
        {"kind": "skill", "stable_key": "p5-v-skill", "version": 1, "relation": "uses_skill"}
    ]


# --- Scope ------------------------------------------------------------------


async def test_user_may_bind_studio_and_own_user(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("rule", "p5-o-global"))
    await _create(client, auth_headers, _payload("rule", "p5-o-mine", scope="user"))
    skill = await _create(
        client,
        auth_headers,
        _payload(
            "skill",
            "p5-o-skill",
            scope="user",
            dependencies=[_pin("rule", "p5-o-global"), _pin("rule", "p5-o-mine")],
        ),
    )
    assert skill["scope"] == "user"


async def test_user_cannot_bind_other_user(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("rule", "p5-o-secret", scope="user"))
    response = await client.post(
        "/api/v1/library",
        headers=other_auth_headers,
        json=_payload(
            "skill", "p5-o-snoop", scope="user", dependencies=[_pin("rule", "p5-o-secret")]
        ),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "pin_not_found"


async def test_studio_cannot_bind_user(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await _create(client, auth_headers, _payload("rule", "p5-o-priv", scope="user"))
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json=_payload("skill", "p5-o-shared", dependencies=[_pin("rule", "p5-o-priv")]),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "invalid_binding"
    assert detail["reason"] == "forbidden_scope"


async def test_project_cannot_bind_private_user(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    await _create(client, auth_headers, _payload("rule", "p5-o-ppriv", scope="user"))
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json=_payload(
            "agent_definition",
            "p5-o-pagent",
            scope="project",
            dependencies=[_pin("rule", "p5-o-ppriv")],
            project_id=project.id,
        ),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_binding"


# --- Ownership --------------------------------------------------------------


async def test_no_ownership_bypass_via_binding(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    owned = await _create(client, auth_headers, _payload("rule", "p5-w-owned"))
    response = await client.post(
        f"/api/v1/library/{owned['id']}/versions",
        headers=other_auth_headers,
        json={"title": "hijack", "content": _rule_content("Hijacked.")},
    )
    assert response.status_code == 403


# --- Deprecation ------------------------------------------------------------


async def test_deprecated_target_keeps_history(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    rule = await _create(client, auth_headers, _payload("rule", "p5-d-rule"))
    agent = await _create(
        client,
        auth_headers,
        _payload("agent_definition", "p5-d-agent", dependencies=[_pin("rule", "p5-d-rule")]),
    )
    await client.post(
        f"/api/v1/library/{agent['id']}/activate",
        headers=auth_headers,
        json={"version": 1, "expected_resource_version": agent["version"]},
    )
    refreshed = (await client.get(f"/api/v1/library/{rule['id']}", headers=auth_headers)).json()
    deprecated = await client.post(
        f"/api/v1/library/{rule['id']}/deprecate",
        headers=auth_headers,
        json={"expected_resource_version": refreshed["version"]},
    )
    assert deprecated.status_code == 200, deprecated.text
    versions = (
        await client.get(f"/api/v1/library/{agent['id']}/versions", headers=auth_headers)
    ).json()
    assert versions[0]["dependencies"] == [
        {"kind": "rule", "stable_key": "p5-d-rule", "version": 1, "relation": "applies_rule"}
    ]
    principal: Principal = await load_principal(db_session, machine[0])
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.AGENT_DEFINITION, "p5-d-agent"
    )
    assert resolved.version == 1


# --- Atomicity --------------------------------------------------------------


async def test_invalid_binding_leaves_no_partial_version(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, _payload("rule", "p5-a-rule"))
    await _create(client, auth_headers, _payload("model_profile", "p5-a-profile"))
    skill = await _create(
        client,
        auth_headers,
        _payload("skill", "p5-a-skill", dependencies=[_pin("rule", "p5-a-rule")]),
    )
    before = (
        await client.get(f"/api/v1/library/{skill['id']}/versions", headers=auth_headers)
    ).json()
    response = await client.post(
        f"/api/v1/library/{skill['id']}/versions",
        headers=auth_headers,
        json={
            "title": "bad v2",
            "content": _skill_content("v2."),
            "dependencies": [
                _pin("rule", "p5-a-rule"),
                _pin("model_profile", "p5-a-profile"),
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_binding"
    after = (
        await client.get(f"/api/v1/library/{skill['id']}/versions", headers=auth_headers)
    ).json()
    assert len(after) == len(before)


# --- Fail-closed resolution -------------------------------------------------


async def test_resolve_user_graph_fails_closed_for_stranger(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine: Principal = await load_principal(db_session, machine[0])
    other: Principal = await load_principal(db_session, other_machine[0])
    rule, _ = await library_service.create_resource(
        db_session,
        mine,
        LibraryResourceCreate(
            kind=LibraryKind.RULE,
            stable_key="p5-f-rule",
            scope=LibraryScope.USER,
            title="t",
            content={"content_schema": "studio.library.rule/v1", "text": "t"},
            dependencies=[],
        ),
    )
    await library_service.activate_resource_version(db_session, mine, rule, 1, rule.version)
    skill, _ = await library_service.create_resource(
        db_session,
        mine,
        LibraryResourceCreate(
            kind=LibraryKind.SKILL,
            stable_key="p5-f-skill",
            scope=LibraryScope.USER,
            title="t",
            content={"content_schema": "studio.library.skill/v1", "text": "t"},
            dependencies=[DependencyPin(kind=LibraryKind.RULE, stable_key="p5-f-rule", version=1)],
        ),
    )
    await db_session.refresh(skill)
    await library_service.activate_resource_version(db_session, mine, skill, 1, skill.version)
    resolved = await library_service.resolve_definition(
        db_session, mine, LibraryKind.SKILL, "p5-f-skill"
    )
    assert resolved.resource_id == skill.id
    with pytest.raises(HTTPException) as exc_info:
        await library_service.resolve_definition(db_session, other, LibraryKind.SKILL, "p5-f-skill")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {"error_code": "definition_not_found"}
