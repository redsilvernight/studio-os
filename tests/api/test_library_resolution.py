from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.library import LibraryResourceModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import library as library_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.library import (
    CapabilityRequirement,
    DependencyPin,
    LibraryKind,
    LibraryLockCreate,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersionCreate,
    RuntimeCapabilities,
    VersionOrigin,
    check_compatibility,
)


async def _principal(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> Principal:
    model, _ = machine
    return await load_principal(db_session, model)


async def _create(
    db_session: AsyncSession,
    principal: Principal,
    key: str,
    scope: LibraryScope = LibraryScope.STUDIO,
    project_id: UUID | None = None,
    kind: LibraryKind = LibraryKind.RULE,
    dependencies: list[DependencyPin] | None = None,
):
    schema = "studio.library.skill/v1" if kind == LibraryKind.SKILL else "studio.library.rule/v1"
    resource, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=kind,
            stable_key=key,
            scope=scope,
            project_id=project_id,
            title=f"{key} title",
            description=None,
            content={"content_schema": schema, "text": key},
            dependencies=dependencies or [],
        ),
    )
    return resource


async def _activate(db_session: AsyncSession, principal: Principal, resource, version: int = 1):
    await db_session.refresh(resource)
    return await library_service.activate_resource_version(
        db_session, principal, resource, version, resource.version
    )


async def _resolve_error(
    db_session: AsyncSession,
    principal: Principal,
    key: str,
    project_id: UUID | None = None,
) -> HTTPException:
    with pytest.raises(HTTPException) as exc_info:
        await library_service.resolve_definition(
            db_session, principal, LibraryKind.RULE, key, project_id
        )
    return exc_info.value


async def test_studio_only_resolves(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    principal = await _principal(db_session, machine)
    resource = await _create(db_session, principal, "solo")
    await _activate(db_session, principal, resource)
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "solo"
    )
    assert resolved.resource_id == resource.id
    assert resolved.scope == LibraryScope.STUDIO
    assert (resolved.version, resolved.version_origin, resolved.deprecated) == (
        1,
        VersionOrigin.ACTIVE,
        False,
    )


async def test_project_shadows_studio(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    principal = await _principal(db_session, machine)
    studio = await _create(db_session, principal, "layered")
    await _activate(db_session, principal, studio)
    own = await _create(db_session, principal, "layered", LibraryScope.PROJECT, project.id)
    await _activate(db_session, principal, own)
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "layered", project.id
    )
    assert resolved.resource_id == own.id
    assert resolved.scope == LibraryScope.PROJECT


async def test_user_shadows_project_and_studio(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    principal = await _principal(db_session, machine)
    for scope, pid in (
        (LibraryScope.STUDIO, None),
        (LibraryScope.PROJECT, project.id),
        (LibraryScope.USER, None),
    ):
        resource = await _create(db_session, principal, "stacked", scope, pid)
        await _activate(db_session, principal, resource)
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "stacked", project.id
    )
    assert resolved.scope == LibraryScope.USER


async def test_fallback_project_to_studio(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    principal = await _principal(db_session, machine)
    studio = await _create(db_session, principal, "fallback")
    await _activate(db_session, principal, studio)
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "fallback", project.id
    )
    assert resolved.resource_id == studio.id


async def test_fallback_user_to_project(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    principal = await _principal(db_session, machine)
    studio = await _create(db_session, principal, "mid")
    await _activate(db_session, principal, studio)
    own = await _create(db_session, principal, "mid", LibraryScope.PROJECT, project.id)
    await _activate(db_session, principal, own)
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "mid", project.id
    )
    assert resolved.resource_id == own.id


async def test_user_isolation_between_principals(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    studio = await _create(db_session, mine, "shared-key")
    await _activate(db_session, mine, studio)
    private = await _create(db_session, mine, "shared-key", LibraryScope.USER)
    await _activate(db_session, mine, private)

    assert (
        await library_service.resolve_definition(db_session, mine, LibraryKind.RULE, "shared-key")
    ).resource_id == private.id
    assert (
        await library_service.resolve_definition(db_session, other, LibraryKind.RULE, "shared-key")
    ).resource_id == studio.id


async def test_absent_vs_invisible_indistinguishable(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    private = await _create(db_session, mine, "only-mine", LibraryScope.USER)
    await _activate(db_session, mine, private)

    missing = await _resolve_error(db_session, other, "never-existed")
    invisible = await _resolve_error(db_session, other, "only-mine")
    assert missing.status_code == invisible.status_code == 404
    assert missing.detail == invisible.detail == {"error_code": "definition_not_found"}


async def test_no_usable_version_is_not_found(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    principal = await _principal(db_session, machine)
    await _create(db_session, principal, "draft-only")
    error = await _resolve_error(db_session, principal, "draft-only")
    assert error.status_code == 404
    assert error.detail == {"error_code": "definition_not_found"}


async def test_exact_uuid_dependency_resolves(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    principal = await _principal(db_session, machine)
    rule = await _create(db_session, principal, "base")
    await _activate(db_session, principal, rule)
    skill = await _create(
        db_session,
        principal,
        "consumer",
        kind=LibraryKind.SKILL,
        dependencies=[DependencyPin(kind=LibraryKind.RULE, stable_key="base", version=1)],
    )
    await _activate(db_session, principal, skill)
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.SKILL, "consumer"
    )
    assert resolved.resource_id == skill.id
    assert resolved.version == 1


async def test_invisible_uuid_dependency_is_not_found(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    rule = await _create(db_session, mine, "my-rule", LibraryScope.USER)
    await _activate(db_session, mine, rule)
    skill = await _create(
        db_session,
        mine,
        "my-skill",
        LibraryScope.STUDIO,
        kind=LibraryKind.SKILL,
        dependencies=[DependencyPin(kind=LibraryKind.RULE, stable_key="my-rule", version=1)],
    )
    await _activate(db_session, mine, skill)

    assert (
        await library_service.resolve_definition(db_session, mine, LibraryKind.SKILL, "my-skill")
    ).resource_id == skill.id
    error = await _resolve_error(db_session, other, "never-existed")
    blocked = await _resolve_error(db_session, other, "my-skill")
    assert blocked.status_code == error.status_code == 404
    assert blocked.detail == error.detail == {"error_code": "definition_not_found"}


async def test_no_implicit_substitution_same_key_different_uuid(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    """Same `stable_key`, different UUIDs: resolving a skill pinned to an
    invisible rule must fail, never silently substitute the caller's own
    same-key rule."""
    mine = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    rule = await _create(db_session, mine, "rebound", LibraryScope.USER)
    await _activate(db_session, mine, rule)
    skill = await _create(
        db_session,
        mine,
        "rebound-skill",
        LibraryScope.STUDIO,
        kind=LibraryKind.SKILL,
        dependencies=[DependencyPin(kind=LibraryKind.RULE, stable_key="rebound", version=1)],
    )
    await _activate(db_session, mine, skill)
    decoy = await _create(db_session, other, "rebound", LibraryScope.USER)
    await _activate(db_session, other, decoy)
    assert decoy.id != rule.id

    error = await _resolve_error(db_session, other, "rebound-skill")
    assert error.status_code == 404
    assert error.detail == {"error_code": "definition_not_found"}


async def test_lock_selects_locked_version(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    principal = await _principal(db_session, machine)
    resource = await _create(db_session, principal, "pinned", LibraryScope.PROJECT, project.id)
    await _activate(db_session, principal, resource)
    await db_session.refresh(resource)
    await library_service.create_resource_version(
        db_session,
        principal,
        resource,
        LibraryVersionCreate(
            title="v2",
            content={"content_schema": "studio.library.rule/v1", "text": "v2"},
        ),
    )
    await db_session.refresh(resource)
    await library_service.activate_resource_version(
        db_session, principal, resource, 2, resource.version
    )
    await library_service.set_lock(
        db_session,
        principal,
        LibraryLockCreate(project_id=project.id, resource_id=resource.id, locked_version=1),
    )
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "pinned", project.id
    )
    assert (resolved.version, resolved.version_origin) == (1, VersionOrigin.LOCK)


async def test_no_lock_selects_active_version(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    principal = await _principal(db_session, machine)
    resource = await _create(db_session, principal, "floating", LibraryScope.PROJECT, project.id)
    await _activate(db_session, principal, resource)
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "floating", project.id
    )
    assert (resolved.version, resolved.version_origin) == (1, VersionOrigin.ACTIVE)


async def test_user_shadow_of_locked_project_definition(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    """Locks are advisory and UUID-bound: a private shadow is a different
    resource, so the project lock does not capture it (DEC-0065 §6)."""
    principal = await _principal(db_session, machine)
    shared = await _create(db_session, principal, "contested", LibraryScope.PROJECT, project.id)
    await _activate(db_session, principal, shared)
    await library_service.set_lock(
        db_session,
        principal,
        LibraryLockCreate(project_id=project.id, resource_id=shared.id, locked_version=1),
    )
    shadow = await _create(db_session, principal, "contested", LibraryScope.USER)
    await _activate(db_session, principal, shadow)
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "contested", project.id
    )
    assert resolved.resource_id == shadow.id
    assert resolved.version_origin == VersionOrigin.ACTIVE


async def test_deprecated_resolves_with_flag(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    principal = await _principal(db_session, machine)
    resource = await _create(db_session, principal, "aging")
    await _activate(db_session, principal, resource)
    await db_session.refresh(resource)
    await library_service.deprecate_resource(db_session, principal, resource, resource.version)
    resolved = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "aging"
    )
    assert resolved.version == 1
    assert resolved.deprecated is True


async def test_readonly_resolves_shared(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    readonly_machine: tuple[MachineModel, str],
) -> None:
    writer = await _principal(db_session, machine)
    reader = await _principal(db_session, readonly_machine)
    resource = await _create(db_session, writer, "public")
    await _activate(db_session, writer, resource)
    resolved = await library_service.resolve_definition(
        db_session, reader, LibraryKind.RULE, "public"
    )
    assert resolved.resource_id == resource.id


async def test_insertion_order_permutations_identical(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    principal = await _principal(db_session, machine)
    first_studio = await _create(db_session, principal, "order-a")
    await _activate(db_session, principal, first_studio)
    first_user = await _create(db_session, principal, "order-a", LibraryScope.USER)
    await _activate(db_session, principal, first_user)
    first_user_second = await _create(db_session, principal, "order-b", LibraryScope.USER)
    await _activate(db_session, principal, first_user_second)
    second_studio = await _create(db_session, principal, "order-b")
    await _activate(db_session, principal, second_studio)

    assert (
        await library_service.resolve_definition(db_session, principal, LibraryKind.RULE, "order-a")
    ).resource_id == first_user.id
    assert (
        await library_service.resolve_definition(db_session, principal, LibraryKind.RULE, "order-b")
    ).resource_id == first_user_second.id


async def test_repeated_resolutions_identical(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    principal = await _principal(db_session, machine)
    resource = await _create(db_session, principal, "stable", LibraryScope.PROJECT, project.id)
    await _activate(db_session, principal, resource)
    first = await library_service.resolve_definition(
        db_session, principal, LibraryKind.RULE, "stable", project.id
    )
    for _ in range(3):
        assert (
            await library_service.resolve_definition(
                db_session, principal, LibraryKind.RULE, "stable", project.id
            )
        ) == first


async def test_unknown_scope_is_fail_closed(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    """Fail-closed: a row carrying an out-of-band scope string (reachable
    only by direct DB tampering, never through the API) resolves exactly
    like a missing definition."""
    principal = await _principal(db_session, machine)
    db_session.add(
        LibraryResourceModel(
            kind=LibraryKind.RULE.value,
            stable_key="tampered",
            scope="bogus",
            status="draft",
            active_version=1,
        )
    )
    await db_session.flush()
    tampered = await _resolve_error(db_session, principal, "tampered")
    missing = await _resolve_error(db_session, principal, "never-existed")
    assert tampered.status_code == missing.status_code == 404
    assert tampered.detail == missing.detail == {"error_code": "definition_not_found"}


def test_unknown_is_not_compatible() -> None:
    assert check_compatibility(CapabilityRequirement(), RuntimeCapabilities()) == []
    assert (
        check_compatibility(CapabilityRequirement(tools_required=["mcp"]), RuntimeCapabilities())
        != []
    )
