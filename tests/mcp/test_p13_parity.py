"""P13 — parité HTTP/MCP sur la fixture agnostique + frontière des handlers.

Le transport MCP doit rester un delegate strict des mêmes services canoniques
que le HTTP (P8/DEC-0072) : résultats identiques pour les deux utilisateurs,
runtimes propres à chacun, isolation préservée, et handlers toujours fins
(aucun accès DB, aucun HTTP local, aucune logique dupliquée).
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.routers import resolutions as resolutions_router
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
from studio_contracts.resolution import AgentResolutionRequest
from studio_contracts.runtime import (
    RuntimeBindingCreate,
    RuntimeLevel,
    RuntimeTarget,
)
from studio_mcp.tools import ai_library as p8

from tests.mcp.conftest import FakeContext

AGENT = LibraryKind.AGENT_DEFINITION
RULE = LibraryKind.RULE
SKILL = LibraryKind.SKILL
PROFILE = LibraryKind.MODEL_PROFILE

P8_TOOL_NAMES = {
    "studio_resolve_agent",
    "studio_discover_definitions",
    "studio_publish_definition",
    "studio_configure_runtime",
    "studio_register_runtime",
}


async def _create(
    db_session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    key: str,
    content: dict[str, object],
    dependencies: list[DependencyPin] | None = None,
):
    resource, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=kind,
            stable_key=key,
            scope=LibraryScope.STUDIO,
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


def _rule(text: str) -> dict[str, object]:
    return {"content_schema": "studio.library.rule/v1", "text": text}


def _skill(text: str) -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": text}


def _profile(**requirements: object) -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": dict(requirements),
        "description": "shared",
    }


async def _world(
    db_session: AsyncSession,
    admin: Principal,
    owner_a: Principal,
    machine_a: MachineModel,
    owner_b: Principal,
    machine_b: MachineModel,
) -> None:
    await _create(db_session, admin, RULE, "par-rule", _rule("Coding standard."))
    await _create(
        db_session,
        admin,
        SKILL,
        "par-skill",
        _skill("Review skill."),
        dependencies=[DependencyPin(kind=RULE, stable_key="par-rule", version=1)],
    )
    await _create(db_session, admin, PROFILE, "par-profile", _profile(coding=True))
    await _create(
        db_session,
        admin,
        AGENT,
        "par-agent",
        {"content_schema": "studio.library.agent_definition/v1", "summary": "shared agent"},
        dependencies=[
            DependencyPin(kind=SKILL, stable_key="par-skill", version=1),
            DependencyPin(kind=PROFILE, stable_key="par-profile", version=1),
        ],
    )
    await bindings_service.create_binding(
        db_session,
        owner_a,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key="par-agent",
            target=RuntimeTarget(
                machine_id=machine_a.id,
                harness_ref="harness_a",
                provider_ref="provider_a",
                model_ref="model_a",
                capabilities=RuntimeCapabilities(coding=True),
            ),
        ),
    )
    await bindings_service.create_binding(
        db_session,
        owner_b,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key="par-agent",
            target=RuntimeTarget(
                machine_id=machine_b.id,
                harness_ref="harness_b",
                provider_ref="provider_b",
                model_ref="model_b",
                capabilities=RuntimeCapabilities(coding=True),
            ),
        ),
    )


async def test_p13_http_mcp_parity_on_agnostic_fixture(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    admin_machine: tuple[MachineModel, str],
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
) -> None:
    admin = await load_principal(db_session, admin_machine[0])
    owner_a = await load_principal(db_session, machine[0])
    owner_b = await load_principal(db_session, other_machine[0])
    await _world(db_session, admin, owner_a, machine[0], owner_b, other_machine[0])

    http_a = await resolutions_router.resolve_agent_definition(
        AgentResolutionRequest(stable_key="par-agent"), db_session, owner_a
    )
    mcp_a = await p8.studio_resolve_agent("par-agent", auth_ctx)
    assert mcp_a.model_dump(mode="json") == http_a.model_dump(mode="json")

    http_b = await resolutions_router.resolve_agent_definition(
        AgentResolutionRequest(stable_key="par-agent"), db_session, owner_b
    )
    mcp_b = await p8.studio_resolve_agent("par-agent", other_auth_ctx)
    assert mcp_b.model_dump(mode="json") == http_b.model_dump(mode="json")

    def _logical(dump: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in dump.items() if k != "runtime"}

    assert _logical(http_a.model_dump(mode="json")) == _logical(http_b.model_dump(mode="json"))
    assert http_a.runtime is not None and http_b.runtime is not None
    assert http_a.runtime.target.provider_ref == "provider_a"
    assert http_b.runtime.target.provider_ref == "provider_b"
    assert http_a.runtime.target.harness_ref == "harness_a"
    assert http_b.runtime.target.harness_ref == "harness_b"


async def test_p13_mcp_preserves_user_isolation(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_auth_ctx: FakeContext,
) -> None:
    mine = await load_principal(db_session, machine[0])
    private_key = f"par-priv-{uuid.uuid4().hex[:8]}"
    private = await library_service.create_resource(
        db_session,
        mine,
        LibraryResourceCreate(
            kind=AGENT,
            stable_key=private_key,
            scope=LibraryScope.USER,
            title="private",
            content={"content_schema": "studio.library.agent_definition/v1", "summary": "p"},
        ),
    )
    resource, _ = private
    await db_session.refresh(resource)
    await library_service.activate_resource_version(db_session, mine, resource, 1, resource.version)

    owner_visible = await library_service.list_resources(db_session, mine, kind="agent_definition")
    assert private_key in {r.stable_key for r in owner_visible}

    masked = await p8.studio_resolve_agent(private_key, other_auth_ctx)
    assert masked.error_code == "definition_not_found"
    assert private_key not in masked.model_dump_json()


async def test_p13_mcp_tool_schemas_are_contract_shaped() -> None:
    import json as _json

    from studio_mcp.server import mcp

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert P8_TOOL_NAMES <= set(tools)
    for name in P8_TOOL_NAMES:
        tool = tools[name]
        assert tool.input_schema is not None, name
        assert tool.input_schema.get("type") == "object", name
        assert tool.output_schema is not None, name
        text = _json.dumps(tool.output_schema)
        assert "error_code" in text, name


def test_p13_mcp_handlers_stay_thin_and_offline() -> None:
    src = inspect.getsource(p8)
    for marker in (
        "studio_api.db",
        "get_session_factory",
        "AsyncSession(",
        "select(",
        "session.execute",
        "session.get(",
        "insert(",
        "delete(",
    ):
        assert marker not in src, marker
    for marker in ("httpx", "requests", "urllib", "localhost", "127.0.0.1"):
        assert marker not in src, marker
    for marker in (
        "library_service.",
        "bindings_service.",
        "registry_service.",
        "resolution_service.",
    ):
        assert marker in src, marker
