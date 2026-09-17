"""P13 — E2E client local sur la fixture agnostique.

Le client réel (`StudioApiClient` sur la vraie app + vraie transaction
Postgres) consomme une Library partagée : composition d'un Context Package
(P9) avec `include_library`, puis projection de la définition canonique
résolue vers deux harnesses (P10), sans logique provider/model dans le cœur.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import library as library_service
from studio_api.services import runtime_bindings as bindings_service
from studio_api.services.authz import Principal, load_principal
from studio_client.adapters import (
    AdapterError,
    AdapterErrorCode,
    get_adapter,
    list_adapters,
    materialize,
)
from studio_client.adapters.base import AdapterArtifact, AdapterResult
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.context import ContextPackageComposer, ContextPackageOptions
from studio_client.tokens import MemoryTokenStore
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryLockCreate,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersionCreate,
    RuntimeCapabilities,
)
from studio_contracts.runtime import (
    RuntimeBindingCreate,
    RuntimeLevel,
    RuntimeTarget,
)

AGENT = LibraryKind.AGENT_DEFINITION
RULE = LibraryKind.RULE
SKILL = LibraryKind.SKILL
PROFILE = LibraryKind.MODEL_PROFILE
WORKFLOW = LibraryKind.WORKFLOW


def _rule(text: str) -> dict[str, object]:
    return {"content_schema": "studio.library.rule/v1", "text": text}


def _skill(text: str) -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": text}


def _profile(**requirements: object) -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": dict(requirements),
        "description": "shared profile",
    }


def _agent(summary: str = "shared agent") -> dict[str, object]:
    return {"content_schema": "studio.library.agent_definition/v1", "summary": summary}


async def _create(
    db_session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    key: str,
    content: dict[str, object],
    *,
    scope: LibraryScope = LibraryScope.STUDIO,
    project_id: uuid.UUID | None = None,
    dependencies: list[DependencyPin] | None = None,
    activate: bool = True,
):
    resource, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=kind,
            stable_key=key,
            scope=scope,
            project_id=project_id,
            title=f"{key} title",
            content=content,
            dependencies=dependencies or [],
        ),
    )
    await db_session.refresh(resource)
    if activate:
        await library_service.activate_resource_version(
            db_session, principal, resource, 1, resource.version
        )
        await db_session.refresh(resource)
    return resource


async def _add_version(
    db_session: AsyncSession,
    principal: Principal,
    resource: object,
    content: dict[str, object],
    *,
    activate: bool = True,
):
    row = await library_service.create_resource_version(
        db_session,
        principal,
        resource,  # type: ignore[arg-type]
        LibraryVersionCreate(title="next", content=content),
    )
    await db_session.refresh(resource)  # type: ignore[arg-type]
    if activate:
        await library_service.activate_resource_version(
            db_session,
            principal,
            resource,  # type: ignore[arg-type]
            row.version,
            resource.version,  # type: ignore[attr-defined]
        )
        await db_session.refresh(resource)  # type: ignore[arg-type]
    return row


async def _library_world(
    db_session: AsyncSession,
    principal: Principal,
    project: ProjectModel,
) -> None:
    # Shadowing: a project rule of the same key hides the studio one.
    await _create(db_session, principal, RULE, "e2e-shadow", _rule("Studio rule."))
    await _create(
        db_session,
        principal,
        RULE,
        "e2e-shadow",
        _rule("Project rule."),
        scope=LibraryScope.PROJECT,
        project_id=project.id,
    )
    # Lock: project pins the studio rule to its v1 while v2 is active.
    locked = await _create(db_session, principal, RULE, "e2e-locked", _rule("Locked v1."))
    await _add_version(db_session, principal, locked, _rule("Locked v2."))
    await library_service.set_lock(
        db_session,
        principal,
        LibraryLockCreate(project_id=project.id, resource_id=locked.id, locked_version=1),
    )
    await _create(db_session, principal, SKILL, "e2e-skill", _skill("Skill body."))
    await _create(db_session, principal, PROFILE, "e2e-profile", _profile(coding=True))
    await _create(
        db_session,
        principal,
        AGENT,
        "e2e-agent",
        _agent(),
        dependencies=[
            DependencyPin(kind=SKILL, stable_key="e2e-skill", version=1),
            DependencyPin(kind=PROFILE, stable_key="e2e-profile", version=1),
        ],
    )
    await _create(
        db_session,
        principal,
        WORKFLOW,
        "e2e-flow",
        {
            "content_schema": "studio.library.workflow/v1",
            "participants": [{"participant_id": "worker", "agent_stable_key": "e2e-agent"}],
        },
        dependencies=[DependencyPin(kind=AGENT, stable_key="e2e-agent", version=1)],
    )
    await bindings_service.create_binding(
        db_session,
        principal,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key="e2e-agent",
            target=RuntimeTarget(
                provider_ref="provider_a",
                model_ref="model_a",
                capabilities=RuntimeCapabilities(coding=True),
            ),
        ),
    )


async def test_p13_client_context_package_from_real_library(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    owner = await load_principal(db_session, machine[0])
    await _library_world(db_session, owner, project)

    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        package = await ContextPackageComposer(client, client_config).generate(
            project.id,
            options=ContextPackageOptions(include_library=True),
        )

    items = {item["stable_key"]: item for item in package.data["library"]}
    assert set(items) == {"e2e-shadow", "e2e-locked", "e2e-skill"}

    assert items["e2e-shadow"]["scope"] == "project"
    assert items["e2e-shadow"]["text"] == "Project rule."
    assert items["e2e-shadow"]["library_kind"] == "rule"

    assert items["e2e-locked"]["version"] == 1
    assert items["e2e-locked"]["version_origin"] == "lock"
    assert items["e2e-locked"]["text"] == "Locked v1."

    assert items["e2e-skill"]["library_kind"] == "skill"
    assert items["e2e-skill"]["text"] == "Skill body."

    omitted = {(o["kind"], o["reason"]): o for o in package.manifest.to_dict()["omitted"]}
    assert ("library", "out_of_scope") in omitted
    assert omitted[("library", "out_of_scope")]["count"] == 3
    assert ("library", "server_unreachable") not in omitted

    library_refs = [s for s in package.manifest.sources if s.kind == "library"]
    assert len(library_refs) == 1
    assert library_refs[0].included == 3


async def test_p13_client_canonical_projected_to_two_adapters(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    owner = await load_principal(db_session, machine[0])
    await _library_world(db_session, owner, project)

    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        resolved = await client.resolve_agent("e2e-agent")
        before = resolved.model_dump(mode="json")

        assert resolved.runtime is not None
        assert resolved.runtime.target.harness_ref is None
        assert "claude-code" in list_adapters()

        claude = get_adapter("claude-code").translate(resolved)
        opencode = get_adapter("opencode").translate(resolved)

    assert resolved.model_dump(mode="json") == before

    assert claude.artifacts and opencode.artifacts
    assert claude.adapter_id == "claude-code"
    assert opencode.adapter_id == "opencode"
    assert claude.artifacts[0].path != opencode.artifacts[0].path

    text_blob = " ".join(a.content for a in claude.artifacts)
    opencode_blob = " ".join(a.content for a in opencode.artifacts)
    assert "Skill body." in text_blob
    assert "Skill body." in opencode_blob
    # Same logical content, different harness envelope: the core never
    # rewrites the shared definition per provider/model.
    assert resolved.agent.stable_key in text_blob
    assert resolved.runtime is not None
    assert resolved.runtime.target.provider_ref == "provider_a"


async def test_p13_client_harness_mismatch_is_explicit_never_silent(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    owner = await load_principal(db_session, machine[0])
    await _library_world(db_session, owner, project)
    # Replace the harness-less binding with an explicit harness claim.
    bindings = await bindings_service.list_bindings(
        db_session, owner, level=RuntimeLevel.USER, kind=AGENT, stable_key="e2e-agent"
    )
    await bindings_service.delete_binding(db_session, owner, bindings[0])
    await bindings_service.create_binding(
        db_session,
        owner,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key="e2e-agent",
            target=RuntimeTarget(
                harness_ref="harness_a",
                provider_ref="provider_a",
                model_ref="model_a",
                capabilities=RuntimeCapabilities(coding=True),
            ),
        ),
    )

    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        resolved = await client.resolve_agent("e2e-agent")

    assert resolved.runtime is not None
    assert resolved.runtime.target.harness_ref == "harness_a"

    try:
        get_adapter("claude-code").translate(resolved)
    except AdapterError as error:
        assert error.code == AdapterErrorCode.HARNESS_MISMATCH
        assert error.details["harness_ref"] == "harness_a"
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("harness mismatch was silently accepted")


async def test_p13_client_materialization_safety(
    app_transport: ASGITransport,
    client_config: ClientConfig,
    token_store: MemoryTokenStore,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    tmp_path,
) -> None:
    owner = await load_principal(db_session, machine[0])
    await _library_world(db_session, owner, project)

    async with StudioApiClient(client_config, token_store, transport=app_transport) as client:
        resolved = await client.resolve_agent("e2e-agent")
        result = get_adapter("opencode").translate(resolved)

    written = materialize(result, tmp_path)
    assert written and all(path.exists() for path in written)

    try:
        materialize(result, tmp_path)
    except AdapterError as error:
        assert error.code == AdapterErrorCode.MATERIALIZATION_FAILED
    else:  # pragma: no cover - overwrite guard must fire
        raise AssertionError("materialize overwrote an existing file by default")

    before = {path: path.read_bytes() for path in written}
    materialize(result, tmp_path, overwrite=True)
    assert {path: path.read_bytes() for path in written} == before

    escaping = AdapterResult(
        adapter_id=result.adapter_id,
        artifacts=(AdapterArtifact(path="../escape.md", content="nope"),),
    )
    try:
        materialize(escaping, tmp_path)
    except AdapterError as error:
        assert error.code == AdapterErrorCode.MATERIALIZATION_FAILED
    else:  # pragma: no cover - traversal guard must fire
        raise AssertionError("materialize accepted a path escaping the root")
    assert not (tmp_path.parent / "escape.md").exists()
