from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import library as library_service
from studio_api.services import runtime_bindings as runtime_service
from studio_api.services.authz import Principal, load_principal
from studio_api.services.provisioning import create_machine
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
)
from studio_contracts.runtime import (
    RuntimeBindingCreate,
    RuntimeLevel,
    RuntimeTarget,
)

AGENT = LibraryKind.AGENT_DEFINITION
PROFILE = LibraryKind.MODEL_PROFILE


def _agent_content() -> dict[str, object]:
    return {
        "content_schema": "studio.library.agent_definition/v1",
        "summary": "Shared debugger.",
        "intended_use": "Exercises.",
    }


def _profile_content(**requirements: object) -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": dict(requirements),
        "description": "Fictional profile.",
    }


async def _principal(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> Principal:
    return await load_principal(db_session, machine[0])


async def _create_library(
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
    return resource


async def _bind(
    db_session: AsyncSession,
    principal: Principal,
    level: RuntimeLevel,
    kind: LibraryKind,
    key: str,
    target: RuntimeTarget,
    project_id: UUID | None = None,
):
    return await runtime_service.create_binding(
        db_session,
        principal,
        RuntimeBindingCreate(
            level=level,
            project_id=project_id,
            target_kind=kind,
            target_stable_key=key,
            target=target,
        ),
    )


def _target(machine_id: UUID | None = None, model: str = "model_x") -> RuntimeTarget:
    return RuntimeTarget(machine_id=machine_id, provider_ref="provider_a", model_ref=model)


# --- Gate: two users, one shared definition ---------------------------------


async def test_two_users_configure_shared_definition_differently(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    agent = await _create_library(db_session, mine, AGENT, "godot-debugger", _agent_content())
    await _bind(
        db_session,
        mine,
        RuntimeLevel.USER,
        AGENT,
        "godot-debugger",
        _target(machine[0].id, "model_x"),
    )
    await _bind(
        db_session,
        other,
        RuntimeLevel.USER,
        AGENT,
        "godot-debugger",
        _target(other_machine[0].id, "model_y"),
    )
    resolved_a = await runtime_service.resolve_runtime(db_session, mine, AGENT, "godot-debugger")
    resolved_b = await runtime_service.resolve_runtime(db_session, other, AGENT, "godot-debugger")
    assert resolved_a.target is not None and resolved_a.target.model_ref == "model_x"
    assert resolved_a.target.machine_id == machine[0].id
    assert resolved_a.level == RuntimeLevel.USER
    assert resolved_b.target is not None and resolved_b.target.model_ref == "model_y"
    assert resolved_b.target.machine_id == other_machine[0].id
    versions = await library_service.list_versions(db_session, agent.id)
    assert len(versions) == 1


# --- ModelProfile binding + agent override ----------------------------------


async def test_profile_binding_used_when_agent_has_none(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, PROFILE, "prof-a", _profile_content())
    await _create_library(
        db_session,
        mine,
        AGENT,
        "agent-a",
        _agent_content(),
        dependencies=[DependencyPin(kind=PROFILE, stable_key="prof-a", version=1)],
    )
    await _bind(
        db_session, mine, RuntimeLevel.USER, PROFILE, "prof-a", _target(machine[0].id, "prof-model")
    )
    resolved = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-a")
    assert resolved.target is not None and resolved.target.model_ref == "prof-model"
    assert resolved.matched_kind == PROFILE
    assert resolved.matched_stable_key == "prof-a"


async def test_agent_override_beats_profile_binding(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, PROFILE, "prof-b", _profile_content())
    await _create_library(
        db_session,
        mine,
        AGENT,
        "agent-b",
        _agent_content(),
        dependencies=[DependencyPin(kind=PROFILE, stable_key="prof-b", version=1)],
    )
    await _bind(
        db_session, mine, RuntimeLevel.USER, PROFILE, "prof-b", _target(machine[0].id, "prof-model")
    )
    await _bind(
        db_session, mine, RuntimeLevel.USER, AGENT, "agent-b", _target(machine[0].id, "agent-model")
    )
    resolved = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-b")
    assert resolved.target is not None and resolved.target.model_ref == "agent-model"
    assert resolved.matched_kind == AGENT


# --- Precedence ---------------------------------------------------------------


async def test_session_beats_project_beats_user(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, AGENT, "agent-c", _agent_content())
    await _bind(
        db_session, mine, RuntimeLevel.USER, AGENT, "agent-c", _target(machine[0].id, "user-model")
    )
    await _bind(
        db_session,
        mine,
        RuntimeLevel.PROJECT_OVERRIDE,
        AGENT,
        "agent-c",
        _target(machine[0].id, "project-model"),
        project_id=project.id,
    )
    resolved = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-c", project.id)
    assert resolved.target is not None and resolved.target.model_ref == "project-model"
    assert resolved.level == RuntimeLevel.PROJECT_OVERRIDE
    session_target = _target(machine[0].id, "session-model")
    resolved_session = await runtime_service.resolve_runtime(
        db_session,
        mine,
        AGENT,
        "agent-c",
        project.id,
        session_overrides={(AGENT, "agent-c"): session_target},
    )
    assert resolved_session.target is not None
    assert resolved_session.target.model_ref == "session-model"
    assert resolved_session.level == RuntimeLevel.SESSION


async def test_user_beats_defaults_and_removal_falls_back(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, AGENT, "agent-d", _agent_content())
    await _bind(
        db_session,
        mine,
        RuntimeLevel.PROJECT_DEFAULT,
        AGENT,
        "agent-d",
        _target(machine[0].id, "project-default"),
        project_id=project.id,
    )
    user_binding = await _bind(
        db_session, mine, RuntimeLevel.USER, AGENT, "agent-d", _target(machine[0].id, "user-model")
    )
    resolved = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-d", project.id)
    assert resolved.target is not None and resolved.target.model_ref == "user-model"
    await runtime_service.delete_binding(db_session, mine, user_binding)
    fallen = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-d", project.id)
    assert fallen.target is not None and fallen.target.model_ref == "project-default"
    assert fallen.level == RuntimeLevel.PROJECT_DEFAULT


async def test_studio_default_is_last_resort(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, AGENT, "agent-e", _agent_content())
    admin_machine_row = (
        await create_machine(db_session, (await _admin(db_session)).id, "admin-rt-machine")
    )[0]
    admin = await load_principal(db_session, admin_machine_row)
    await _bind(
        db_session,
        admin,
        RuntimeLevel.STUDIO_DEFAULT,
        AGENT,
        "agent-e",
        RuntimeTarget(model_ref="studio-model"),
    )
    resolved = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-e")
    assert resolved.target is not None and resolved.target.model_ref == "studio-model"
    assert resolved.level == RuntimeLevel.STUDIO_DEFAULT
    with pytest.raises(HTTPException) as exc_info:
        await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-e-missing")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {"error_code": "definition_not_found"}


async def _admin(db_session: AsyncSession):
    from studio_api.services import provisioning as provisioning_service

    return await provisioning_service.create_user(
        db_session, "RT Admin", "rt-admin@example.test", "admin"
    )


# --- Isolation -----------------------------------------------------------------


async def test_cross_user_isolation(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    await _create_library(db_session, mine, AGENT, "agent-f", _agent_content())
    binding = await _bind(
        db_session, mine, RuntimeLevel.USER, AGENT, "agent-f", _target(machine[0].id, "mine-only")
    )
    assert await runtime_service.get_binding(db_session, other, binding.id) is None
    listed = await runtime_service.list_bindings(db_session, other)
    assert all(b.owner_user_id == other.user.id for b in listed if b.level == "user")
    assert binding.id not in [b.id for b in listed]
    with pytest.raises(HTTPException) as exc_info:
        await runtime_service.delete_binding(db_session, other, binding)
    assert exc_info.value.status_code == 403
    own = await _bind(
        db_session,
        other,
        RuntimeLevel.USER,
        AGENT,
        "agent-f",
        _target(other_machine[0].id, "other-model"),
    )
    assert own.owner_user_id == other.user.id


# --- Machines ---------------------------------------------------------------------


async def test_unknown_machine_is_not_found(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    from uuid import uuid4

    mine = await _principal(db_session, machine)
    with pytest.raises(HTTPException) as exc_info:
        await _bind(db_session, mine, RuntimeLevel.USER, AGENT, "agent-g", _target(uuid4(), "x"))
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {"error_code": "runtime_target_not_found"}


async def test_other_user_machine_is_forbidden(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    with pytest.raises(HTTPException) as exc_info:
        await _bind(
            db_session, mine, RuntimeLevel.USER, AGENT, "agent-h", _target(other_machine[0].id, "x")
        )
    assert exc_info.value.status_code == 403


async def test_revoked_machine_falls_through_to_default(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    from datetime import UTC, datetime

    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, AGENT, "agent-i", _agent_content())
    await _bind(
        db_session, mine, RuntimeLevel.USER, AGENT, "agent-i", _target(machine[0].id, "user-model")
    )
    await _bind(
        db_session,
        mine,
        RuntimeLevel.PROJECT_DEFAULT,
        AGENT,
        "agent-i",
        RuntimeTarget(model_ref="fallback-model"),
        project_id=project.id,
    )
    machine[0].credential_revoked_at = datetime.now(UTC)
    await db_session.flush()
    resolved = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-i", project.id)
    assert resolved.target is not None and resolved.target.model_ref == "fallback-model"
    assert resolved.level == RuntimeLevel.PROJECT_DEFAULT


# --- Compatibility -------------------------------------------------------------------


async def test_compatible_and_incompatible_targets(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    from studio_contracts.library import RuntimeCapabilities
    from studio_contracts.runtime import RuntimeTarget as Target

    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, PROFILE, "prof-j", _profile_content(coding=True))
    await _create_library(
        db_session,
        mine,
        AGENT,
        "agent-j",
        _agent_content(),
        dependencies=[DependencyPin(kind=PROFILE, stable_key="prof-j", version=1)],
    )
    await _bind(
        db_session,
        mine,
        RuntimeLevel.USER,
        PROFILE,
        "prof-j",
        Target(model_ref="ok", capabilities=RuntimeCapabilities(coding=True)),
    )
    resolved = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-j")
    assert resolved.compatible is True
    assert resolved.unsatisfied == []
    await runtime_service.delete_binding(
        db_session,
        mine,
        (await runtime_service.list_bindings(db_session, mine, kind=PROFILE))[0],
    )
    await _bind(
        db_session,
        mine,
        RuntimeLevel.USER,
        PROFILE,
        "prof-j",
        Target(model_ref="weak", capabilities=RuntimeCapabilities()),
    )
    bad = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-j")
    assert bad.compatible is False
    assert bad.unsatisfied != []
    assert bad.target is not None and bad.target.model_ref == "weak"


# --- Secrets / shape ----------------------------------------------------------------------


def test_target_has_no_secret_field() -> None:
    with pytest.raises(ValidationError):
        RuntimeTarget(  # type: ignore[call-arg]
            model_ref="m",
            api_key="sk-secret",  # noqa: F821
        )


def test_empty_target_rejected() -> None:
    with pytest.raises(ValidationError):
        RuntimeTarget()


async def test_stored_payload_contains_no_secrets(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    binding = await _bind(
        db_session, mine, RuntimeLevel.USER, AGENT, "agent-k", _target(machine[0].id, "m")
    )
    assert set(binding.target.keys()) <= {
        # P6/DEC-0070 adds two non-secret anchors; the intent is unchanged:
        # nowhere to put a key, token or credential.
        "runtime_id",
        "machine_id",
        "harness_ref",
        "provider_ref",
        "model_ref",
        "capabilities",
    }
    assert "sk-" not in str(binding.target)


async def test_ephemeral_level_and_bad_kind_rejected(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    with pytest.raises(HTTPException) as exc_info:
        await _bind(
            db_session, mine, RuntimeLevel.SESSION, AGENT, "agent-l", _target(machine[0].id, "m")
        )
    assert exc_info.value.detail["error_code"] == "invalid_runtime_binding"
    with pytest.raises(HTTPException) as exc_info:
        await _bind(
            db_session,
            mine,
            RuntimeLevel.USER,
            LibraryKind.RULE,
            "rule-l",
            _target(machine[0].id, "m"),
        )
    assert exc_info.value.detail["error_code"] == "invalid_runtime_binding"
    await _bind(db_session, mine, RuntimeLevel.USER, AGENT, "agent-l", _target(machine[0].id, "m"))
    with pytest.raises(HTTPException) as exc_info:
        await _bind(
            db_session, mine, RuntimeLevel.USER, AGENT, "agent-l", _target(machine[0].id, "m2")
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {"error_code": "already_bound"}


# --- Determinism ------------------------------------------------------------------------------


async def test_resolution_is_deterministic(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, AGENT, "agent-m", _agent_content())
    await _bind(db_session, mine, RuntimeLevel.USER, AGENT, "agent-m", _target(machine[0].id, "m"))
    first = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-m")
    second = await runtime_service.resolve_runtime(db_session, mine, AGENT, "agent-m")
    assert first == second


async def test_readonly_cannot_create_binding(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    readonly_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    reader = await _principal(db_session, readonly_machine)
    await _create_library(db_session, mine, AGENT, "agent-n", _agent_content())
    with pytest.raises(HTTPException) as exc_info:
        await _bind(
            db_session, reader, RuntimeLevel.USER, AGENT, "agent-n", RuntimeTarget(model_ref="m")
        )
    assert exc_info.value.status_code == 403
