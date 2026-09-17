"""P5 Resolution Engine — integration tests (real Postgres).

Proves the acquisition boundary: DB rows -> loader snapshot -> pure core ->
result. Business logic itself is covered without DB in
`test_resolution_engine.py`; here only the frontier is exercised (loading,
locks, visibility, liveness, error mapping) plus the full MVP gate
scenario."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import library as library_service
from studio_api.services import resolution as resolution_service
from studio_api.services import runtime_bindings as runtime_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryLockCreate,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersionCreate,
    RuntimeCapabilities,
    VersionOrigin,
)
from studio_contracts.resolution import ProvenanceSource
from studio_contracts.runtime import (
    RuntimeBindingCreate,
    RuntimeLevel,
    RuntimeTarget,
)

AGENT = LibraryKind.AGENT_DEFINITION
RULE = LibraryKind.RULE
SKILL = LibraryKind.SKILL
PROFILE = LibraryKind.MODEL_PROFILE


def _agent_content() -> dict[str, object]:
    return {
        "content_schema": "studio.library.agent_definition/v1",
        "summary": "Gate agent.",
    }


def _rule_content(text: str = "Gate rule.") -> dict[str, object]:
    return {"content_schema": "studio.library.rule/v1", "text": text}


def _skill_content(text: str = "Gate skill.") -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": text}


def _profile_content(**requirements: object) -> dict[str, object]:
    return {
        "content_schema": "studio.library.model_profile/v1",
        "requirements": dict(requirements),
        "description": "Gate profile.",
    }


async def _principal(db_session: AsyncSession, machine: tuple[MachineModel, str]) -> Principal:
    return await load_principal(db_session, machine[0])


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


async def _gate_world(
    db_session: AsyncSession,
    principal: Principal,
    project: ProjectModel,
    machine_id: UUID,
    profile_requirements: dict[str, object],
    target_capabilities: dict[str, object],
    binding_level: RuntimeLevel = RuntimeLevel.USER,
):
    """MVP gate fixture: A -> {R1, S1 -> R2, M}; one runtime binding."""
    await _create(db_session, principal, RULE, "gate-r1", _rule_content("Direct."))
    await _create(db_session, principal, RULE, "gate-r2", _rule_content("Transitive."))
    await _create(
        db_session,
        principal,
        SKILL,
        "gate-s1",
        _skill_content(),
        dependencies=[DependencyPin(kind=RULE, stable_key="gate-r2", version=1)],
    )
    await _create(
        db_session, principal, PROFILE, "gate-m", _profile_content(**profile_requirements)
    )
    agent = await _create(
        db_session,
        principal,
        AGENT,
        "gate-a",
        _agent_content(),
        dependencies=[
            DependencyPin(kind=RULE, stable_key="gate-r1", version=1),
            DependencyPin(kind=SKILL, stable_key="gate-s1", version=1),
            DependencyPin(kind=PROFILE, stable_key="gate-m", version=1),
        ],
    )
    await _bind(
        db_session,
        principal,
        binding_level,
        AGENT,
        "gate-a",
        RuntimeTarget(
            machine_id=machine_id,
            provider_ref="provider_a",
            model_ref="model_a",
            capabilities=RuntimeCapabilities.model_validate(target_capabilities),
        ),
        project_id=project.id
        if binding_level in (RuntimeLevel.PROJECT_OVERRIDE, RuntimeLevel.PROJECT_DEFAULT)
        else None,
    )
    return agent


async def test_mvp_gate_full_resolution(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _gate_world(
        db_session,
        mine,
        project,
        machine[0].id,
        {"coding": True},
        {"coding": True},
        RuntimeLevel.USER,
    )

    resolved = await resolution_service.resolve_full(db_session, mine, AGENT, "gate-a", project.id)

    assert resolved.agent.stable_key == "gate-a"
    assert resolved.agent.version == 1
    assert resolved.agent.version_origin == VersionOrigin.ACTIVE
    assert {r.stable_key for r in resolved.rules} == {"gate-r1", "gate-r2"}
    assert [s.stable_key for s in resolved.skills] == ["gate-s1"]
    assert resolved.model_profile is not None
    assert resolved.model_profile.stable_key == "gate-m"
    assert resolved.requirements.coding is True
    r2 = next(r for r in resolved.rules if r.stable_key == "gate-r2")
    assert len(r2.paths) == 1
    assert r2.paths[0].via_stable_key == "gate-s1"
    assert resolved.runtime is not None
    assert resolved.runtime.level == RuntimeLevel.USER
    assert resolved.runtime.matched_stable_key == "gate-a"
    assert resolved.runtime.compatible is True
    assert resolved.runtime.provenance is not None
    assert resolved.runtime.provenance.source == ProvenanceSource.RUNTIME_BINDING


async def test_mvp_gate_incompatible_has_no_fallback(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _gate_world(
        db_session,
        mine,
        project,
        machine[0].id,
        {"coding": True},
        {"coding": False},
        RuntimeLevel.PROJECT_OVERRIDE,
    )
    await _bind(
        db_session,
        mine,
        RuntimeLevel.STUDIO_DEFAULT,
        AGENT,
        "gate-a",
        RuntimeTarget(
            model_ref="good-model",
            capabilities=RuntimeCapabilities(coding=True),
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolution_service.resolve_full(db_session, mine, AGENT, "gate-a", project.id)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "runtime_incompatible"
    assert exc_info.value.detail["level"] == RuntimeLevel.PROJECT_OVERRIDE.value
    assert exc_info.value.detail["unsatisfied"] == ["coding: required"]


async def test_project_lock_determines_root_version(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    agent = await _create(db_session, mine, AGENT, "locked-a", _agent_content())
    await library_service.create_resource_version(
        db_session,
        mine,
        agent,
        LibraryVersionCreate(title="v2", content=_agent_content()),
    )
    await db_session.refresh(agent)
    await library_service.activate_resource_version(db_session, mine, agent, 2, agent.version)
    await db_session.refresh(agent)
    assert agent.active_version == 2
    await library_service.set_lock(
        db_session,
        mine,
        LibraryLockCreate(project_id=project.id, resource_id=agent.id, locked_version=1),
    )

    resolved = await resolution_service.resolve_full(
        db_session, mine, AGENT, "locked-a", project.id
    )

    assert resolved.agent.version == 1
    assert resolved.agent.version_origin == VersionOrigin.LOCK
    assert resolved.agent.provenance.locked is True
    assert resolved.agent.provenance.source == ProvenanceSource.PROJECT_LOCK


async def test_no_binding_is_valid_null_runtime(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    await _create(db_session, mine, AGENT, "bare-a", _agent_content())

    resolved = await resolution_service.resolve_full(db_session, mine, AGENT, "bare-a")

    assert resolved.agent.stable_key == "bare-a"
    assert resolved.runtime is None


async def test_revoked_machine_level_falls_through(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _create(db_session, mine, AGENT, "rev-a", _agent_content())
    await _bind(
        db_session,
        mine,
        RuntimeLevel.USER,
        AGENT,
        "rev-a",
        RuntimeTarget(machine_id=machine[0].id, model_ref="dead-model"),
    )
    await _bind(
        db_session,
        mine,
        RuntimeLevel.STUDIO_DEFAULT,
        AGENT,
        "rev-a",
        RuntimeTarget(model_ref="live-model"),
    )
    machine[0].credential_revoked_at = datetime.now(UTC)
    await db_session.flush()

    resolved = await resolution_service.resolve_full(db_session, mine, AGENT, "rev-a")

    assert resolved.runtime is not None
    assert resolved.runtime.level == RuntimeLevel.STUDIO_DEFAULT
    assert resolved.runtime.target.model_ref == "live-model"


async def test_invisible_definition_stays_not_found(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    from studio_contracts.library import LibraryScope as Scope

    mine = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    resource, _ = await library_service.create_resource(
        db_session,
        other,
        LibraryResourceCreate(
            kind=AGENT,
            stable_key="private-a",
            scope=Scope.USER,
            title="private",
            content=_agent_content(),
        ),
    )
    await db_session.refresh(resource)
    await library_service.activate_resource_version(
        db_session, other, resource, 1, resource.version
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolution_service.resolve_full(db_session, mine, AGENT, "private-a")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {"error_code": "definition_not_found"}


async def test_session_override_wins_and_invalid_errors(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    mine = await _principal(db_session, machine)
    await _create(db_session, mine, AGENT, "sess-a", _agent_content())
    await _bind(
        db_session,
        mine,
        RuntimeLevel.USER,
        AGENT,
        "sess-a",
        RuntimeTarget(machine_id=machine[0].id, model_ref="stored-model"),
    )

    resolved = await resolution_service.resolve_full(
        db_session,
        mine,
        AGENT,
        "sess-a",
        project.id,
        session_overrides={
            (AGENT, "sess-a"): RuntimeTarget(machine_id=machine[0].id, model_ref="session-model")
        },
    )
    assert resolved.runtime is not None
    assert resolved.runtime.level == RuntimeLevel.SESSION
    assert resolved.runtime.target.model_ref == "session-model"
    assert resolved.runtime.provenance is not None
    assert resolved.runtime.provenance.source == ProvenanceSource.SESSION_OVERRIDE

    with pytest.raises(HTTPException) as exc_info:
        await resolution_service.resolve_full(
            db_session,
            mine,
            AGENT,
            "sess-a",
            project.id,
            session_overrides={
                (AGENT, "sess-a"): RuntimeTarget(
                    machine_id="00000000-0000-0000-0000-000000000000",
                    model_ref="ghost-model",
                )
            },
        )
    assert exc_info.value.status_code == 404
