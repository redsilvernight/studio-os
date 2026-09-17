from __future__ import annotations

import inspect
import json
import uuid
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.routers import library as library_router
from studio_api.routers import resolutions as resolutions_router
from studio_api.routers import runtime_bindings as bindings_router
from studio_api.routers import runtimes as runtimes_router
from studio_api.services import library as library_service
from studio_api.services import runtime_bindings as bindings_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
    RuntimeCapabilities,
)
from studio_contracts.resolution import AgentResolutionRequest, SessionRuntimeOverride
from studio_contracts.runtime import (
    RuntimeBindingCreate,
    RuntimeLevel,
    RuntimeRegistrationCreate,
    RuntimeRegistrationUpdateRequest,
    RuntimeTarget,
)
from studio_mcp.errors import McpError
from studio_mcp.tools import ai_library as p8

from tests.mcp.conftest import FakeContext

AGENT = LibraryKind.AGENT_DEFINITION
PROFILE = LibraryKind.MODEL_PROFILE
RULE = LibraryKind.RULE
SKILL = LibraryKind.SKILL

P8_TOOL_NAMES = {
    "studio_resolve_agent",
    "studio_discover_definitions",
    "studio_publish_definition",
    "studio_configure_runtime",
    "studio_register_runtime",
}


def as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    assert isinstance(result, dict)
    return result


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _principal(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> Principal:
    return await load_principal(db_session, machine[0])


def _agent_content() -> dict[str, object]:
    return {"content_schema": "studio.library.agent_definition/v1", "summary": "P8 gate."}


def _rule_content() -> dict[str, object]:
    return {"content_schema": "studio.library.rule/v1", "text": "Always verify."}


def _skill_content() -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": "Skill body."}


def _profile_content(**requirements: object) -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": dict(requirements),
        "description": "P8 gate.",
    }


async def _create(
    db_session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    key: str,
    content: dict[str, object],
    dependencies: list[DependencyPin] | None = None,
    scope: LibraryScope = LibraryScope.STUDIO,
):
    resource, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=kind,
            stable_key=key,
            scope=scope,
            title=f"{key} title",
            content=content,
            dependencies=dependencies or [],
        ),
    )
    await db_session.refresh(resource)
    await library_service.activate_resource_version(
        db_session, principal, resource, 1, resource.version
    )
    await db_session.refresh(resource)
    return resource


async def _gate_world(
    db_session: AsyncSession,
    principal: Principal,
    agent_key: str,
    profile_key: str,
    rule_key: str,
    skill_key: str,
) -> None:
    await _create(db_session, principal, RULE, rule_key, _rule_content())
    await _create(
        db_session,
        principal,
        SKILL,
        skill_key,
        _skill_content(),
        dependencies=[DependencyPin(kind=RULE, stable_key=rule_key, version=1)],
    )
    await _create(db_session, principal, PROFILE, profile_key, _profile_content(coding=True))
    await _create(
        db_session,
        principal,
        AGENT,
        agent_key,
        _agent_content(),
        dependencies=[
            DependencyPin(kind=SKILL, stable_key=skill_key, version=1),
            DependencyPin(kind=PROFILE, stable_key=profile_key, version=1),
        ],
    )


def _http_request() -> Request:
    return Request({"type": "http", "method": "POST", "headers": []})


def _stable(dump: dict[str, Any], *extra: str) -> dict[str, Any]:
    return {k: v for k, v in dump.items() if k not in ("id", "created_at", "updated_at", *extra)}


# ---------------------------------------------------------------------------
# Output schemas (§36) + thin handlers (§32)
# ---------------------------------------------------------------------------


async def test_p8_tools_have_explicit_output_schemas() -> None:
    from studio_mcp.server import mcp

    by_name = {tool.name: tool for tool in await mcp.list_tools()}
    expected_refs = {
        "studio_resolve_agent": "ResolvedAgentDefinition",
        "studio_discover_definitions": "DefinitionDetail",
        "studio_publish_definition": "PublishDefinitionResult",
        "studio_configure_runtime": "RuntimeBinding",
        "studio_register_runtime": "RuntimeRegistration",
    }
    for name, ref in expected_refs.items():
        schema = by_name[name].output_schema
        assert schema is not None, name
        assert schema.get("type") == "object", name
        assert "result" in schema.get("properties", {}), name
        text = json.dumps(schema)
        assert ref in text, name
        assert "error_code" in text, name


def test_p8_handlers_are_thin_delegates_to_shared_services() -> None:
    src = inspect.getsource(p8)
    assert "studio_api.db" not in src
    assert "get_session_factory" not in src
    assert "AsyncSession(" not in src
    for query_marker in ("select(", "session.execute", "session.get(", "insert(", "delete("):
        assert query_marker not in src, query_marker
    for marker in (
        "library_service.",
        "bindings_service.",
        "registry_service.",
        "resolution_service.",
    ):
        assert marker in src, marker


# ---------------------------------------------------------------------------
# Resolution (§11-§14, §34)
# ---------------------------------------------------------------------------


async def test_p8_resolve_happy_path_full_structured_output(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
) -> None:
    mine = await _principal(db_session, machine)
    agent_key, profile_key, rule_key, skill_key = (
        _key("p8-a"),
        _key("p8-m"),
        _key("p8-r"),
        _key("p8-s"),
    )
    await _gate_world(db_session, mine, agent_key, profile_key, rule_key, skill_key)
    await bindings_service.create_binding(
        db_session,
        mine,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key=agent_key,
            target=RuntimeTarget(
                machine_id=machine[0].id, capabilities=RuntimeCapabilities(coding=True)
            ),
        ),
    )

    result = await p8.studio_resolve_agent(agent_key, auth_ctx)
    assert isinstance(result, BaseModel)
    resolved = as_dict(result)
    assert resolved["agent"]["stable_key"] == agent_key
    assert resolved["agent"]["version"] == 1
    assert resolved["agent"]["provenance"]["source"] == "active_pointer"
    assert resolved["agent"]["scope"] == "studio"
    assert [r["stable_key"] for r in resolved["rules"]] == [rule_key]
    assert resolved["rules"][0]["paths"] != []
    assert [s["stable_key"] for s in resolved["skills"]] == [skill_key]
    assert resolved["model_profile"]["stable_key"] == profile_key
    assert resolved["requirements"]["coding"] is True
    assert resolved["runtime"]["compatible"] is True
    assert resolved["runtime"]["level"] == "user"
    assert resolved["runtime"]["matched_stable_key"] == agent_key
    assert resolved["runtime"]["provenance"]["binding_level"] == "user"


async def test_p8_resolve_incompatible_has_no_fallback(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
) -> None:
    mine = await _principal(db_session, machine)
    agent_key, profile_key = _key("p8-bad"), _key("p8-badm")
    await _create(db_session, mine, PROFILE, profile_key, _profile_content(coding=True))
    await _create(
        db_session,
        mine,
        AGENT,
        agent_key,
        _agent_content(),
        dependencies=[DependencyPin(kind=PROFILE, stable_key=profile_key, version=1)],
    )
    await bindings_service.create_binding(
        db_session,
        mine,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key=agent_key,
            target=RuntimeTarget(
                model_ref="weak-model", capabilities=RuntimeCapabilities(coding=False)
            ),
        ),
    )

    result = await p8.studio_resolve_agent(agent_key, auth_ctx)
    assert isinstance(result, McpError)
    assert result.error_code == "runtime_incompatible"
    assert result.model_extra.get("matched_stable_key") == agent_key
    assert result.model_extra.get("unsatisfied") != []


async def test_p8_resolve_unknown_definition(
    auth_ctx: FakeContext,
) -> None:
    result = await p8.studio_resolve_agent("no-such-agent", auth_ctx)
    assert isinstance(result, McpError)
    assert result.error_code == "definition_not_found"


async def test_p8_session_override_ephemeral_and_wins(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
) -> None:
    mine = await _principal(db_session, machine)
    agent_key = _key("p8-ephem")
    await _create(db_session, mine, AGENT, agent_key, _agent_content())
    before = await bindings_service.list_bindings(db_session, mine, None, None, None, None)

    result = await p8.studio_resolve_agent(
        agent_key,
        auth_ctx,
        session_overrides=[
            SessionRuntimeOverride(
                target_kind=AGENT,
                target_stable_key=agent_key,
                target=RuntimeTarget(machine_id=machine[0].id),
            )
        ],
    )
    resolved = as_dict(result)
    assert resolved["runtime"]["provenance"]["source"] == "session_override"
    after = await bindings_service.list_bindings(db_session, mine, None, None, None, None)
    assert [b.id for b in after] == [b.id for b in before]

    duplicate = await p8.studio_resolve_agent(
        agent_key,
        auth_ctx,
        session_overrides=[
            SessionRuntimeOverride(
                target_kind=AGENT,
                target_stable_key=agent_key,
                target=RuntimeTarget(machine_id=machine[0].id),
            ),
            SessionRuntimeOverride(
                target_kind=AGENT,
                target_stable_key=agent_key,
                target=RuntimeTarget(model_ref="other"),
            ),
        ],
    )
    assert isinstance(duplicate, McpError)
    assert duplicate.error_code == "invalid_resolution_input"


# ---------------------------------------------------------------------------
# Discovery (§16)
# ---------------------------------------------------------------------------


async def test_p8_discover_list_and_read(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
) -> None:
    mine = await _principal(db_session, machine)
    key = _key("p8-d")
    resource = await _create(db_session, mine, RULE, key, _rule_content())

    listed = await p8.studio_discover_definitions(auth_ctx, kind="rule")
    assert isinstance(listed, BaseModel)
    assert any(d["stable_key"] == key for d in as_dict(listed)["definitions"])

    by_id = await p8.studio_discover_definitions(
        auth_ctx, resource_id=str(resource.id), include_versions=True
    )
    detail = as_dict(by_id)
    assert detail["resource"]["stable_key"] == key
    assert len(detail["versions"]) == 1

    by_key = await p8.studio_discover_definitions(auth_ctx, kind="rule", stable_key=key)
    assert as_dict(by_key)["resource"]["id"] == str(resource.id)

    missing_kind = await p8.studio_discover_definitions(auth_ctx, stable_key=key)
    assert isinstance(missing_kind, McpError)
    assert missing_kind.error_code == "invalid_argument"

    unknown = await p8.studio_discover_definitions(
        auth_ctx, resource_id="00000000-0000-0000-0000-000000000000"
    )
    assert isinstance(unknown, McpError)
    assert unknown.error_code == "definition_not_found"

    bad_limit = await p8.studio_discover_definitions(auth_ctx, limit=0)
    assert isinstance(bad_limit, McpError)
    assert bad_limit.error_code == "invalid_argument"


# ---------------------------------------------------------------------------
# Publish (§17) + Principal-before-idempotence (§9, §35)
# ---------------------------------------------------------------------------


async def test_p8_publish_lifecycle(
    auth_ctx: FakeContext,
    readonly_auth_ctx: FakeContext,
) -> None:
    key = _key("p8-pub")
    created = await p8.studio_publish_definition(
        "create",
        auth_ctx,
        kind="rule",
        stable_key=key,
        scope="studio",
        title="P8 rule",
        content=_rule_content(),
    )
    assert not isinstance(created, McpError)
    first = as_dict(created)
    assert first["resource"]["stable_key"] == key
    assert first["resource"]["active_version"] == 0
    assert first["version"]["version"] == 1
    resource_id = first["resource"]["id"]

    denied = await p8.studio_publish_definition(
        "create",
        readonly_auth_ctx,
        kind="rule",
        stable_key=_key("p8-no"),
        scope="studio",
        title="nope",
        content=_rule_content(),
    )
    assert isinstance(denied, McpError)
    assert denied.error_code == "forbidden"

    second = await p8.studio_publish_definition(
        "create_version",
        auth_ctx,
        resource_id=resource_id,
        title="v2",
        content={"content_schema": "studio.library.rule/v1", "text": "v2"},
    )
    assert as_dict(second)["version"]["version"] == 2
    assert as_dict(second)["resource"]["active_version"] == 0
    current_version = as_dict(second)["resource"]["version"]

    activated = await p8.studio_publish_definition(
        "activate",
        auth_ctx,
        resource_id=resource_id,
        version=2,
        expected_resource_version=current_version,
    )
    assert as_dict(activated)["resource"]["active_version"] == 2

    stale = await p8.studio_publish_definition(
        "activate", auth_ctx, resource_id=resource_id, version=1, expected_resource_version=1
    )
    assert isinstance(stale, McpError)
    assert stale.error_code == "version_conflict"

    deprecated = await p8.studio_publish_definition(
        "deprecate",
        auth_ctx,
        resource_id=resource_id,
        expected_resource_version=as_dict(activated)["resource"]["version"],
    )
    assert as_dict(deprecated)["resource"]["status"] == "deprecated"

    bad_content = await p8.studio_publish_definition(
        "create",
        auth_ctx,
        kind="rule",
        stable_key=_key("p8-bad"),
        scope="studio",
        title="bad",
        content={"content_schema": "studio.library.rule/v1"},
    )
    assert isinstance(bad_content, McpError)
    assert bad_content.error_code == "invalid_content"


async def test_p8_publish_idempotency_and_principal_first(
    auth_ctx: FakeContext,
    readonly_auth_ctx: FakeContext,
) -> None:
    key, idem = _key("p8-idem"), f"p8-{_key('k')}"
    first = await p8.studio_publish_definition(
        "create",
        auth_ctx,
        kind="rule",
        stable_key=key,
        scope="studio",
        title="idem",
        content=_rule_content(),
        idempotency_key=idem,
    )
    replay = await p8.studio_publish_definition(
        "create",
        auth_ctx,
        kind="rule",
        stable_key=key,
        scope="studio",
        title="idem",
        content=_rule_content(),
        idempotency_key=idem,
    )
    assert as_dict(first)["resource"]["id"] == as_dict(replay)["resource"]["id"]

    mismatch = await p8.studio_publish_definition(
        "create",
        auth_ctx,
        kind="rule",
        stable_key=key,
        scope="studio",
        title="different",
        content=_rule_content(),
        idempotency_key=idem,
    )
    assert isinstance(mismatch, McpError)
    assert mismatch.error_code == "idempotency_key_payload_mismatch"

    fresh = f"p8-{_key('k')}"
    denied = await p8.studio_publish_definition(
        "create",
        readonly_auth_ctx,
        kind="rule",
        stable_key=_key("p8-x"),
        scope="studio",
        title="x",
        content=_rule_content(),
        idempotency_key=fresh,
    )
    assert isinstance(denied, McpError)
    assert denied.error_code == "forbidden"
    allowed = await p8.studio_publish_definition(
        "create",
        auth_ctx,
        kind="rule",
        stable_key=_key("p8-x"),
        scope="studio",
        title="x",
        content=_rule_content(),
        idempotency_key=fresh,
    )
    assert not isinstance(allowed, McpError)


# ---------------------------------------------------------------------------
# Configure runtime (§18)
# ---------------------------------------------------------------------------


async def test_p8_configure_runtime_set_clear(
    auth_ctx: FakeContext,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    key = _key("p8-cfg")
    await _create(db_session, mine, AGENT, key, _agent_content())
    idem = f"p8-{_key('k')}"

    created = await p8.studio_configure_runtime(
        "set",
        auth_ctx,
        level="user",
        target_kind="agent_definition",
        target_stable_key=key,
        target={"machine_id": str(machine[0].id)},
        idempotency_key=idem,
    )
    assert not isinstance(created, McpError)
    assert as_dict(created)["level"] == "user"

    replay = await p8.studio_configure_runtime(
        "set",
        auth_ctx,
        level="user",
        target_kind="agent_definition",
        target_stable_key=key,
        target={"machine_id": str(machine[0].id)},
        idempotency_key=idem,
    )
    assert as_dict(replay)["id"] == as_dict(created)["id"]

    cleared = await p8.studio_configure_runtime(
        "clear",
        auth_ctx,
        level="user",
        target_kind="agent_definition",
        target_stable_key=key,
    )
    assert as_dict(cleared)["id"] == as_dict(created)["id"]

    gone = await p8.studio_configure_runtime(
        "clear",
        auth_ctx,
        level="user",
        target_kind="agent_definition",
        target_stable_key=key,
    )
    assert isinstance(gone, McpError)
    assert gone.error_code == "not_found"

    ephemeral = await p8.studio_configure_runtime(
        "set",
        auth_ctx,
        level="session",
        target_kind="agent_definition",
        target_stable_key=key,
        target={"machine_id": str(machine[0].id)},
    )
    assert isinstance(ephemeral, McpError)
    assert ephemeral.error_code == "invalid_runtime_binding"


# ---------------------------------------------------------------------------
# Register runtime (§19-§21)
# ---------------------------------------------------------------------------


async def test_p8_register_runtime_lifecycle_provider_neutral(
    auth_ctx: FakeContext,
) -> None:
    idem = f"p8-{_key('k')}"
    ollama = await p8.studio_register_runtime(
        "register",
        auth_ctx,
        provider_ref="ollama",
        model_ref="m1",
        capabilities={"coding": True},
        idempotency_key=idem,
    )
    assert not isinstance(ollama, McpError)
    first = as_dict(ollama)
    assert first["provider_ref"] == "ollama"

    other = await p8.studio_register_runtime(
        "register", auth_ctx, provider_ref="future-provider", model_ref="m1"
    )
    assert not isinstance(other, McpError)
    assert as_dict(other)["id"] != first["id"]

    replay = await p8.studio_register_runtime(
        "register",
        auth_ctx,
        provider_ref="ollama",
        model_ref="m1",
        capabilities={"coding": True},
        idempotency_key=idem,
    )
    assert as_dict(replay)["id"] == first["id"]

    updated = await p8.studio_register_runtime(
        "update",
        auth_ctx,
        runtime_id=first["id"],
        model_ref="m2",
        expected_version=1,
    )
    assert as_dict(updated)["model_ref"] == "m2"

    stale = await p8.studio_register_runtime(
        "update", auth_ctx, runtime_id=first["id"], model_ref="m3", expected_version=1
    )
    assert isinstance(stale, McpError)
    assert stale.error_code == "version_conflict"

    revoked = await p8.studio_register_runtime("revoke", auth_ctx, runtime_id=first["id"])
    assert as_dict(revoked)["status"] == "revoked"
    again = await p8.studio_register_runtime("revoke", auth_ctx, runtime_id=first["id"])
    assert as_dict(again)["status"] == "revoked"

    unknown = await p8.studio_register_runtime(
        "update",
        auth_ctx,
        runtime_id="00000000-0000-0000-0000-000000000000",
        expected_version=1,
    )
    assert isinstance(unknown, McpError)
    assert unknown.error_code == "runtime_not_found"

    secret = await p8.studio_register_runtime(
        "register", auth_ctx, provider_ref="p", runtime_metadata={"api_key": "x"}
    )
    assert isinstance(secret, McpError)
    assert secret.error_code == "invalid_argument"


# ---------------------------------------------------------------------------
# Auth / isolation (§35)
# ---------------------------------------------------------------------------


async def test_p8_auth_and_isolation(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
    other_machine: tuple[MachineModel, str],
    other_auth_ctx: FakeContext,
    readonly_auth_ctx: FakeContext,
) -> None:
    naked = FakeContext(headers=None)
    for call in (
        p8.studio_resolve_agent("x", naked),
        p8.studio_discover_definitions(naked),
        p8.studio_publish_definition("create", naked),
        p8.studio_configure_runtime("clear", naked),
        p8.studio_register_runtime("revoke", naked),
    ):
        result = await call
        assert isinstance(result, McpError)
        assert result.error_code == "unauthenticated"

    for call in (
        p8.studio_publish_definition("create", readonly_auth_ctx),
        p8.studio_configure_runtime(
            "clear",
            readonly_auth_ctx,
            level="user",
            target_kind="agent_definition",
            target_stable_key="x",
        ),
        p8.studio_register_runtime("register", readonly_auth_ctx),
    ):
        result = await call
        assert isinstance(result, McpError)
        assert result.error_code == "forbidden"

    mine = await _principal(db_session, machine)
    private_key = _key("p8-priv")
    await _create(db_session, mine, AGENT, private_key, _agent_content(), scope=LibraryScope.USER)
    masked = await p8.studio_resolve_agent(private_key, other_auth_ctx)
    assert isinstance(masked, McpError)
    assert masked.error_code == "definition_not_found"

    foreign_machine = await p8.studio_resolve_agent(
        private_key,
        auth_ctx,
        session_overrides=[
            {
                "target_kind": "agent_definition",
                "target_stable_key": private_key,
                "target": {"machine_id": str(other_machine[0].id)},
            }
        ],
    )
    assert isinstance(foreign_machine, McpError)
    assert foreign_machine.error_code == "forbidden"


# ---------------------------------------------------------------------------
# HTTP / MCP semantic parity (§33)
# ---------------------------------------------------------------------------


async def test_p8_http_mcp_parity(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    agent_key, profile_key = _key("p8-par"), _key("p8-parm")
    await _create(db_session, mine, PROFILE, profile_key, _profile_content(coding=True))
    await _create(
        db_session,
        mine,
        AGENT,
        agent_key,
        _agent_content(),
        dependencies=[DependencyPin(kind=PROFILE, stable_key=profile_key, version=1)],
    )
    await bindings_service.create_binding(
        db_session,
        mine,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key=agent_key,
            target=RuntimeTarget(
                machine_id=machine[0].id, capabilities=RuntimeCapabilities(coding=True)
            ),
        ),
    )

    http_resolved = await resolutions_router.resolve_agent_definition(
        AgentResolutionRequest(stable_key=agent_key, project_id=project.id),
        db_session,
        mine,
    )
    mcp_resolved = await p8.studio_resolve_agent(agent_key, auth_ctx, project_id=str(project.id))
    assert as_dict(mcp_resolved) == http_resolved.model_dump(mode="json")

    rule_key = _key("p8-parr")
    http_created = await library_router.create_library_resource(
        LibraryResourceCreate(
            kind=RULE,
            stable_key=rule_key,
            scope=LibraryScope.STUDIO,
            title="parity",
            content=_rule_content(),
        ),
        _http_request(),
        db_session,
        mine,
        None,
    )
    mcp_key = _key("p8-parm2")
    mcp_created = await p8.studio_publish_definition(
        "create",
        auth_ctx,
        kind="rule",
        stable_key=mcp_key,
        scope="studio",
        title="parity",
        content=_rule_content(),
    )
    assert as_dict(mcp_created)["resource"]["stable_key"] == mcp_key
    assert _stable(as_dict(mcp_created)["resource"], "stable_key") == _stable(
        http_created.model_dump(mode="json"), "stable_key"
    )

    bind_key = _key("p8-parb")
    http_binding = await bindings_router.create_runtime_binding(
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key=bind_key,
            target=RuntimeTarget(machine_id=machine[0].id),
        ),
        _http_request(),
        db_session,
        mine,
        None,
    )
    mcp_bind_key = _key("p8-parb2")
    mcp_binding = await p8.studio_configure_runtime(
        "set",
        auth_ctx,
        level="user",
        target_kind="agent_definition",
        target_stable_key=mcp_bind_key,
        target={"machine_id": str(machine[0].id)},
    )
    assert _stable(as_dict(mcp_binding), "target_stable_key") == _stable(
        http_binding.model_dump(mode="json"), "target_stable_key"
    )

    http_runtime = await runtimes_router.register_runtime(
        RuntimeRegistrationCreate(provider_ref="parity", model_ref="m"),
        _http_request(),
        db_session,
        mine,
        None,
    )
    mcp_runtime = await p8.studio_register_runtime(
        "register", auth_ctx, provider_ref="parity", model_ref="m"
    )
    assert _stable(as_dict(mcp_runtime)) == _stable(http_runtime.model_dump(mode="json"))


async def test_p8_register_update_parity(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
) -> None:
    from studio_contracts.runtime import RuntimeRegistrationUpdate

    mine = await _principal(db_session, machine)
    http_runtime = await runtimes_router.register_runtime(
        RuntimeRegistrationCreate(provider_ref="parity-u", model_ref="m"),
        _http_request(),
        db_session,
        mine,
        None,
    )
    http_updated = await runtimes_router.update_runtime(
        UUID(http_runtime.id) if isinstance(http_runtime.id, str) else http_runtime.id,
        RuntimeRegistrationUpdateRequest(
            update=RuntimeRegistrationUpdate(model_ref="m2"),
            expected_version=http_runtime.version,
        ),
        _http_request(),
        db_session,
        mine,
        None,
    )
    mcp_runtime = await p8.studio_register_runtime(
        "register", auth_ctx, provider_ref="parity-um", model_ref="m"
    )
    mcp_updated = await p8.studio_register_runtime(
        "update",
        auth_ctx,
        runtime_id=as_dict(mcp_runtime)["id"],
        model_ref="m2",
        expected_version=as_dict(mcp_runtime)["version"],
    )
    assert _stable(as_dict(mcp_updated), "provider_ref") == _stable(
        http_updated.model_dump(mode="json"), "provider_ref"
    )
