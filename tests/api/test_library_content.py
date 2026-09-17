from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from studio_contracts.library import (
    RULE_SKILL_TEXT_MAX_LENGTH,
    AgentDefinitionContent,
    CapabilityRequirement,
    LibraryKind,
    ModelProfileContent,
    RuleContent,
    RuntimeCapabilities,
    SkillContent,
    check_compatibility,
    content_validation_errors,
    validate_library_content,
)


def _rule_content(text: str = "Do not upgrade a locked resource.") -> dict[str, object]:
    return {"content_schema": "studio.library.rule/v1", "text": text}


def _skill_content(text: str = "Skill body.") -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": text}


def _profile_content(**requirements: object) -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": dict(requirements),
        "description": "Fictional profile for provider_a/model_a.",
    }


def _agent_content() -> dict[str, object]:
    return {
        "content_schema": "studio.library.agent_definition/v1",
        "summary": "Fictional debugger.",
        "intended_use": "Debugging exercises.",
    }


# --- P3 schemas: rule / skill -------------------------------------------------


def test_rule_content_valid() -> None:
    assert content_validation_errors(LibraryKind.RULE, _rule_content()) == []
    validate_library_content(LibraryKind.RULE, _rule_content())


def test_rule_content_rejects_missing_schema() -> None:
    assert content_validation_errors(LibraryKind.RULE, {"text": "x"}) != []


def test_rule_content_rejects_wrong_schema() -> None:
    content = {"content_schema": "studio.library.skill/v1", "text": "x"}
    assert content_validation_errors(LibraryKind.RULE, content) != []


def test_rule_content_rejects_missing_or_empty_text() -> None:
    assert (
        content_validation_errors(LibraryKind.RULE, {"content_schema": "studio.library.rule/v1"})
        != []
    )
    assert content_validation_errors(LibraryKind.RULE, _rule_content("")) != []


def test_rule_content_rejects_too_long_text() -> None:
    assert (
        content_validation_errors(LibraryKind.RULE, _rule_content("x" * RULE_SKILL_TEXT_MAX_LENGTH))
        == []
    )
    assert (
        content_validation_errors(
            LibraryKind.RULE, _rule_content("x" * (RULE_SKILL_TEXT_MAX_LENGTH + 1))
        )
        != []
    )


def test_rule_content_rejects_extra_keys() -> None:
    content = {**_rule_content(), "provider": "provider_a"}
    assert content_validation_errors(LibraryKind.RULE, content) != []


def test_skill_content_valid_and_bounded() -> None:
    assert content_validation_errors(LibraryKind.SKILL, _skill_content()) == []
    assert (
        content_validation_errors(
            LibraryKind.SKILL, _skill_content("x" * (RULE_SKILL_TEXT_MAX_LENGTH + 1))
        )
        != []
    )
    assert (
        content_validation_errors(
            LibraryKind.SKILL, {"content_schema": "studio.library.rule/v1", "text": "x"}
        )
        != []
    )


# --- P3 schemas: model_profile -------------------------------------------------


def test_model_profile_content_valid() -> None:
    content = _profile_content(coding=True, context_window_min=32000)
    assert content_validation_errors(LibraryKind.MODEL_PROFILE, content) == []
    parsed = ModelProfileContent.model_validate(content)
    assert parsed.requirements.coding is True
    assert parsed.requirements.context_window_min == 32000


def test_model_profile_content_empty_requirements_valid() -> None:
    content = _profile_content()
    assert content_validation_errors(LibraryKind.MODEL_PROFILE, content) == []


def test_model_profile_content_rejects_missing_requirements() -> None:
    content = {
        "content_schema": "studio.library.model_profile/v1",
        "description": "No requirements key.",
    }
    assert content_validation_errors(LibraryKind.MODEL_PROFILE, content) != []


@pytest.mark.parametrize(
    "vendor_key",
    [
        "provider",
        "model",
        "harness",
        "endpoint",
        "api_key",
        "family",
        "api_version",
        "whitelist",
        "ranking",
    ],
)
def test_model_profile_content_rejects_vendor_keys(vendor_key: str) -> None:
    content = {**_profile_content(coding=True), vendor_key: "provider_a"}
    assert content_validation_errors(LibraryKind.MODEL_PROFILE, content) != []


def test_model_profile_content_rejects_wrong_schema() -> None:
    content = {
        "content_schema": "studio.library.rule/v1",
        "requirements": {},
    }
    assert content_validation_errors(LibraryKind.MODEL_PROFILE, content) != []


# --- P3 schemas: agent_definition ----------------------------------------------


def test_agent_definition_content_valid() -> None:
    assert content_validation_errors(LibraryKind.AGENT_DEFINITION, _agent_content()) == []
    assert (
        content_validation_errors(
            LibraryKind.AGENT_DEFINITION,
            {"content_schema": "studio.library.agent_definition/v1"},
        )
        == []
    )
    parsed = AgentDefinitionContent.model_validate(_agent_content())
    assert parsed.summary == "Fictional debugger."


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "coding",
        "requirements",
        "tools_required",
        "provider",
        "model",
        "harness",
        "runtime",
        "endpoint",
    ],
)
def test_agent_definition_content_rejects_inline_capabilities_and_runtime(
    forbidden_key: str,
) -> None:
    content = {**_agent_content(), forbidden_key: True}
    assert content_validation_errors(LibraryKind.AGENT_DEFINITION, content) != []


def test_agent_definition_content_rejects_wrong_schema() -> None:
    content = {"content_schema": "studio.library.rule/v1", "summary": "x"}
    assert content_validation_errors(LibraryKind.AGENT_DEFINITION, content) != []


# --- P3 schemas: workflow deferred to P11 ---------------------------------------


def test_workflow_content_stays_free_form() -> None:
    assert content_validation_errors(LibraryKind.WORKFLOW, {}) == []
    assert content_validation_errors(LibraryKind.WORKFLOW, {"anything": [1, 2]}) == []


# --- Capability matching (frozen P3 semantics) -----------------------------------


def test_empty_requirement_is_compatible_with_anything() -> None:
    assert check_compatibility(CapabilityRequirement(), RuntimeCapabilities()) == []
    assert check_compatibility(CapabilityRequirement(), RuntimeCapabilities(coding=True)) == []


def test_coding_dimension() -> None:
    assert (
        check_compatibility(CapabilityRequirement(coding=True), RuntimeCapabilities(coding=True))
        == []
    )
    assert (
        check_compatibility(CapabilityRequirement(coding=True), RuntimeCapabilities(coding=False))
        != []
    )


def test_context_window_dimension() -> None:
    required = CapabilityRequirement(context_window_min=32000)
    assert check_compatibility(required, RuntimeCapabilities(context_window=64000)) == []
    assert check_compatibility(required, RuntimeCapabilities(context_window=32000)) == []
    assert check_compatibility(required, RuntimeCapabilities(context_window=16000)) != []
    assert check_compatibility(required, RuntimeCapabilities(context_window=None)) != []


def test_tools_subset_dimension() -> None:
    required = CapabilityRequirement(tools_required=["mcp", "shell"])
    assert check_compatibility(required, RuntimeCapabilities(tools=["mcp", "shell", "edit"])) == []
    assert check_compatibility(required, RuntimeCapabilities(tools=["mcp", "shell"])) == []
    assert check_compatibility(required, RuntimeCapabilities(tools=["mcp"])) != []
    assert check_compatibility(required, RuntimeCapabilities(tools=[])) != []


def test_local_dimension() -> None:
    assert (
        check_compatibility(
            CapabilityRequirement(local_compatible=True),
            RuntimeCapabilities(local=True),
        )
        == []
    )
    assert (
        check_compatibility(
            CapabilityRequirement(local_compatible=True),
            RuntimeCapabilities(local=False),
        )
        != []
    )


@pytest.mark.parametrize("dimension", ["reasoning", "multimodal", "cost", "latency"])
def test_open_string_dimensions_are_strict_equality(dimension: str) -> None:
    required = CapabilityRequirement(**{dimension: "tier_a"})
    assert check_compatibility(required, RuntimeCapabilities(**{dimension: "tier_a"})) == []
    # No implicit ranking: another tag never satisfies, even a "higher" one.
    assert check_compatibility(required, RuntimeCapabilities(**{dimension: "tier_b"})) != []
    # Unknown (undescribed) runtime side never satisfies.
    assert check_compatibility(required, RuntimeCapabilities()) != []


def test_unknown_is_not_compatible_bundle() -> None:
    required = CapabilityRequirement(
        reasoning="deep",
        coding=True,
        context_window_min=128000,
        tools_required=["mcp"],
        multimodal="vision",
        local_compatible=True,
        cost="low",
        latency="fast",
    )
    assert check_compatibility(required, RuntimeCapabilities()) != []


def test_neutrality_two_fictional_runtimes_agree() -> None:
    """provider_a/model_a vs provider_b/model_b are test names only: the
    domain carries no vendor field, so identical capability surfaces must
    yield identical verdicts for the same requirements."""
    assert "provider" not in CapabilityRequirement.model_fields
    assert "model" not in CapabilityRequirement.model_fields
    assert "harness" not in CapabilityRequirement.model_fields
    assert "provider" not in ModelProfileContent.model_fields
    assert "model" not in ModelProfileContent.model_fields
    assert "provider" not in AgentDefinitionContent.model_fields
    assert "provider" not in RuleContent.model_fields
    assert "provider" not in SkillContent.model_fields

    required = CapabilityRequirement(coding=True, tools_required=["mcp"])
    runtime_a = RuntimeCapabilities(coding=True, tools=["mcp", "shell"])
    runtime_b = RuntimeCapabilities(coding=True, tools=["mcp", "shell"])
    assert check_compatibility(required, runtime_a) == []
    assert check_compatibility(required, runtime_b) == []
    assert check_compatibility(required, runtime_a) == check_compatibility(required, runtime_b)


# --- Service-level: validation at write time (real Postgres) --------------------


async def _create(
    client: AsyncClient,
    headers: dict[str, str],
    payload: dict[str, object],
) -> dict[str, object]:
    response = await client.post("/api/v1/library", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def test_create_rule_rejects_invalid_content(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json={
            "kind": "rule",
            "stable_key": "bad-rule",
            "scope": "studio",
            "title": "Bad",
            "content": {"text": "missing schema marker"},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_content"


async def test_create_rule_rejects_extra_content_keys(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json={
            "kind": "rule",
            "stable_key": "vendor-rule",
            "scope": "studio",
            "title": "Vendor",
            "content": {**_rule_content(), "provider": "provider_a"},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_content"


async def test_create_model_profile_valid_and_invalid(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    valid: dict[str, object] = {
        "kind": "model_profile",
        "stable_key": "profile-a",
        "scope": "studio",
        "title": "Profile A",
        "content": _profile_content(coding=True, context_window_min=32000),
    }
    created = await _create(client, auth_headers, valid)
    assert created["kind"] == "model_profile"

    invalid: dict[str, object] = {
        "kind": "model_profile",
        "stable_key": "profile-vendor",
        "scope": "studio",
        "title": "Vendor profile",
        "content": {**_profile_content(coding=True), "provider": "provider_a"},
    }
    response = await client.post("/api/v1/library", headers=auth_headers, json=invalid)
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_content"


async def test_create_agent_definition_with_profile_link(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(
        client,
        auth_headers,
        {
            "kind": "model_profile",
            "stable_key": "linked-profile",
            "scope": "studio",
            "title": "Linked",
            "content": _profile_content(tools_required=["mcp"]),
        },
    )
    agent = await _create(
        client,
        auth_headers,
        {
            "kind": "agent_definition",
            "stable_key": "linked-agent",
            "scope": "studio",
            "title": "Linked agent",
            "content": _agent_content(),
            "dependencies": [
                {"kind": "model_profile", "stable_key": "linked-profile", "version": 1}
            ],
        },
    )
    versions = (
        await client.get(f"/api/v1/library/{agent['id']}/versions", headers=auth_headers)
    ).json()
    assert versions[0]["dependencies"] == [
        {"kind": "model_profile", "stable_key": "linked-profile", "version": 1}
    ]


async def test_create_agent_definition_rejects_inline_capabilities(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/library",
        headers=auth_headers,
        json={
            "kind": "agent_definition",
            "stable_key": "inline-agent",
            "scope": "studio",
            "title": "Inline",
            "content": {**_agent_content(), "coding": True},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "invalid_content"


async def test_agent_definition_without_profile_is_valid(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """No linked ModelProfile = no particular requirement expressed: the
    definition is valid and the empty requirement stays universally
    compatible."""
    agent = await _create(
        client,
        auth_headers,
        {
            "kind": "agent_definition",
            "stable_key": "bare-agent",
            "scope": "studio",
            "title": "Bare",
            "content": _agent_content(),
        },
    )
    assert agent["kind"] == "agent_definition"
    assert check_compatibility(CapabilityRequirement(), RuntimeCapabilities()) == []


async def test_new_version_rejects_invalid_content(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(
        client,
        auth_headers,
        {
            "kind": "rule",
            "stable_key": "evolving-rule",
            "scope": "studio",
            "title": "Evolving",
            "content": _rule_content(),
        },
    )
    bad = await client.post(
        f"/api/v1/library/{created['id']}/versions",
        headers=auth_headers,
        json={"title": "bad v2", "content": {"text": "no schema"}},
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["error_code"] == "invalid_content"

    good = await client.post(
        f"/api/v1/library/{created['id']}/versions",
        headers=auth_headers,
        json={"title": "good v2", "content": _rule_content("v2 text")},
    )
    assert good.status_code == 201
    assert good.json()["version"] == 2


async def test_validation_is_not_an_existence_oracle(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    """Authorization runs before semantic validation: a caller without
    rights gets 403/404, never a 422 that would confirm the target exists
    and is well-formed."""
    mine = await _create(
        client,
        auth_headers,
        {
            "kind": "rule",
            "stable_key": "oracle-rule",
            "scope": "studio",
            "title": "Oracle",
            "content": _rule_content(),
        },
    )
    probe = {"title": "probe", "content": {"text": "malformed, no schema"}}
    response = await client.post(
        f"/api/v1/library/{mine['id']}/versions",
        headers=other_auth_headers,
        json=probe,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "forbidden"


async def test_user_isolation_preserved_for_profiles(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    created = await _create(
        client,
        auth_headers,
        {
            "kind": "model_profile",
            "stable_key": "secret-profile",
            "scope": "user",
            "title": "Secret",
            "content": _profile_content(coding=True),
        },
    )
    other_get = await client.get(f"/api/v1/library/{created['id']}", headers=other_auth_headers)
    assert other_get.status_code == 404


async def test_invalid_content_releases_idempotency_reservation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A 422 releases the idempotency reservation: an identical retry gets
    422 again, and no resource row is ever committed (no ghost row)."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    payload: dict[str, object] = {
        "kind": "rule",
        "stable_key": "ghost-rule",
        "scope": "studio",
        "title": "Ghost",
        "content": {"text": "no schema"},
    }
    first = await client.post("/api/v1/library", headers=headers, json=payload)
    assert first.status_code == 422
    assert first.json()["detail"]["error_code"] == "invalid_content"
    second = await client.post("/api/v1/library", headers=headers, json=payload)
    assert second.status_code == 422
    listing = await client.get("/api/v1/library", headers=auth_headers)
    assert all(item["stable_key"] != "ghost-rule" for item in listing.json())
