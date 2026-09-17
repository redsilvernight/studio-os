"""P6 Runtime Registry — DB/service tests (real Postgres, no HTTP, no LLM).

Covers the registry lifecycle, ownership, Machine relation, binding
integration (P4), the full P4+P5+P6 gate via `resolve_full`, and the
Ollama/local architectural test (same code path, no server, no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.services import library as library_service
from studio_api.services import resolution as resolution_service
from studio_api.services import runtime_bindings as bindings_service
from studio_api.services import runtime_registry as registry_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
    RuntimeCapabilities,
)
from studio_contracts.resolution import ResolutionErrorCode
from studio_contracts.runtime import (
    RuntimeBindingCreate,
    RuntimeLevel,
    RuntimeRegistrationCreate,
    RuntimeRegistrationUpdate,
    RuntimeStatus,
    RuntimeTarget,
)

AGENT = LibraryKind.AGENT_DEFINITION
PROFILE = LibraryKind.MODEL_PROFILE


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


async def _register(
    db_session: AsyncSession,
    principal: Principal,
    machine_id: UUID | None = None,
    *,
    harness: str | None = "test-harness",
    provider: str | None = "test-provider",
    model: str | None = "test-model",
    capabilities: RuntimeCapabilities | None = None,
    metadata: dict[str, object] | None = None,
):
    return await registry_service.register_runtime(
        db_session,
        principal,
        RuntimeRegistrationCreate(
            machine_id=machine_id,
            harness_ref=harness,
            provider_ref=provider,
            model_ref=model,
            capabilities=capabilities or RuntimeCapabilities(),
            runtime_metadata=metadata or {},
        ),
    )


async def _bind_runtime_id(
    db_session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    key: str,
    runtime_id: UUID,
):
    return await bindings_service.create_binding(
        db_session,
        principal,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=kind,
            target_stable_key=key,
            target=RuntimeTarget(runtime_id=runtime_id),
        ),
    )


# --- Registry lifecycle ----------------------------------------------------


async def test_register_returns_stable_id(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    row = await _register(db_session, mine, machine[0].id)
    assert row.id is not None
    assert row.owner_user_id == mine.user.id
    assert row.machine_id == machine[0].id
    assert row.status == RuntimeStatus.ACTIVE.value
    fetched = await registry_service.get_runtime(db_session, mine, row.id)
    assert fetched is not None and fetched.id == row.id
    contract = registry_service.to_contract(fetched)
    assert contract.harness_ref == "test-harness"
    assert contract.provider_ref == "test-provider"
    assert contract.model_ref == "test-model"
    assert contract.capability_source.value == "declared"


async def test_multiple_runtimes_share_provider_and_model(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    first = await _register(db_session, mine, machine[0].id, model="shared-model")
    second = await _register(db_session, mine, None, harness="other-harness", model="shared-model")
    assert first.id != second.id
    assert first.provider_ref == second.provider_ref == "test-provider"
    assert first.model_ref == second.model_ref == "shared-model"
    rows = await registry_service.list_runtimes(db_session, mine)
    assert {row.id for row in rows} == {first.id, second.id}


async def test_capabilities_persisted_and_updatable(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    row = await _register(
        db_session, mine, machine[0].id, capabilities=RuntimeCapabilities(coding=True)
    )
    assert registry_service.to_contract(row).capabilities.coding is True
    assert row.version == 1
    updated = await registry_service.update_runtime(
        db_session,
        mine,
        row,
        RuntimeRegistrationUpdate(capabilities=RuntimeCapabilities(coding=False)),
        row.version,
    )
    assert updated.id == row.id
    assert updated.version == 2
    assert registry_service.to_contract(updated).capabilities.coding is False


async def test_stale_update_is_version_conflict(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    row = await _register(db_session, mine, machine[0].id)
    await registry_service.update_runtime(
        db_session, mine, row, RuntimeRegistrationUpdate(model_ref="v2"), row.version
    )
    with pytest.raises(HTTPException) as exc:
        await registry_service.update_runtime(
            db_session, mine, row, RuntimeRegistrationUpdate(model_ref="stale"), 1
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == "version_conflict"
    assert exc.value.detail["server_version"] == 2


async def test_update_cannot_remove_last_anchor(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    row = await _register(db_session, mine, machine[0].id, harness=None, provider=None, model=None)
    with pytest.raises(HTTPException) as exc:
        await registry_service.update_runtime(
            db_session,
            mine,
            row,
            RuntimeRegistrationUpdate(detach_machine=True),
            row.version,
        )
    assert exc.value.status_code == 422


async def test_revoke_is_logical_and_idempotent(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    row = await _register(db_session, mine, machine[0].id)
    revoked = await registry_service.revoke_runtime(db_session, mine, row)
    assert revoked.status == RuntimeStatus.REVOKED.value
    assert revoked.id == row.id
    again = await registry_service.revoke_runtime(db_session, mine, revoked)
    assert again.status == RuntimeStatus.REVOKED.value
    assert await registry_service.get_runtime(db_session, mine, row.id) is not None
    assert await registry_service.list_runtimes(db_session, mine) == []
    assert len(await registry_service.list_runtimes(db_session, mine, include_revoked=True)) == 1


# --- Ownership / isolation -------------------------------------------------


async def test_register_on_other_users_machine_is_forbidden(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    with pytest.raises(HTTPException) as exc:
        await _register(db_session, mine, other_machine[0].id)
    assert exc.value.status_code == 403


async def test_register_on_unknown_machine_is_not_found(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    with pytest.raises(HTTPException) as exc:
        await _register(db_session, mine, uuid4())
    assert exc.value.status_code == 404


async def test_user_isolation_no_cross_user_oracle(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    row = await _register(db_session, mine, machine[0].id)
    assert await registry_service.get_runtime(db_session, other, row.id) is None
    assert await registry_service.list_runtimes(db_session, other) == []
    with pytest.raises(HTTPException) as exc:
        await registry_service.update_runtime(
            db_session, other, row, RuntimeRegistrationUpdate(model_ref="hijack"), row.version
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await registry_service.revoke_runtime(db_session, other, row)
    assert exc.value.status_code == 403


async def test_owner_is_server_derived(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    row = await _register(db_session, mine, machine[0].id)
    assert row.owner_user_id == mine.user.id


# --- Bindings toward the registry (P4 integration) -------------------------


async def test_binding_to_valid_runtime_resolves_registry_data(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, AGENT, "agent-a", _agent_content())
    row = await _register(
        db_session,
        mine,
        machine[0].id,
        harness="h",
        provider="p",
        model="m",
        capabilities=RuntimeCapabilities(coding=True),
    )
    await _bind_runtime_id(db_session, mine, AGENT, "agent-a", row.id)
    resolved = await bindings_service.resolve_runtime(db_session, mine, AGENT, "agent-a")
    assert resolved.target is not None
    assert resolved.target.runtime_id == row.id
    assert resolved.target.provider_ref == "p"
    assert resolved.target.model_ref == "m"
    assert resolved.target.harness_ref == "h"
    assert resolved.target.machine_id == machine[0].id
    assert resolved.target.capabilities.coding is True
    assert resolved.compatible is True


async def test_binding_to_unknown_runtime_is_not_found(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    with pytest.raises(HTTPException) as exc:
        await _bind_runtime_id(db_session, mine, AGENT, "agent-a", uuid4())
    assert exc.value.status_code == 404
    assert exc.value.detail["error_code"] == "runtime_not_found"


async def test_binding_with_mixed_reference_and_inline_is_rejected(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    row = await _register(db_session, mine, machine[0].id)
    with pytest.raises(HTTPException) as exc:
        await bindings_service.create_binding(
            db_session,
            mine,
            RuntimeBindingCreate(
                level=RuntimeLevel.USER,
                target_kind=AGENT,
                target_stable_key="agent-a",
                target=RuntimeTarget(runtime_id=row.id, provider_ref="p"),
            ),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["reason"] == "runtime_id_must_be_exclusive"


async def test_binding_to_other_users_runtime_is_forbidden(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    mine = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    row = await _register(db_session, other, other_machine[0].id)
    with pytest.raises(HTTPException) as exc:
        await _bind_runtime_id(db_session, mine, AGENT, "agent-a", row.id)
    assert exc.value.status_code == 403


async def test_binding_to_revoked_runtime_falls_through(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, AGENT, "agent-a", _agent_content())
    row = await _register(db_session, mine, machine[0].id)
    await _bind_runtime_id(db_session, mine, AGENT, "agent-a", row.id)
    await registry_service.revoke_runtime(db_session, mine, row)
    resolved = await bindings_service.resolve_runtime(db_session, mine, AGENT, "agent-a")
    assert resolved.target is None
    assert resolved.compatible is True


async def test_p4_inline_binding_still_resolves_untouched(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    """P4 backward compatibility: bindings created before the registry (no
    `runtime_id`) resolve exactly as before — deterministic no-op migration."""
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, AGENT, "agent-a", _agent_content())
    await bindings_service.create_binding(
        db_session,
        mine,
        RuntimeBindingCreate(
            level=RuntimeLevel.USER,
            target_kind=AGENT,
            target_stable_key="agent-a",
            target=RuntimeTarget(machine_id=machine[0].id, provider_ref="p", model_ref="m"),
        ),
    )
    resolved = await bindings_service.resolve_runtime(db_session, mine, AGENT, "agent-a")
    assert resolved.target is not None
    assert resolved.target.runtime_id is None
    assert resolved.target.model_ref == "m"


# --- Full gate P4 + P5 + P6 -------------------------------------------------


async def _agent_with_profile(
    db_session: AsyncSession, principal: Principal, agent_key: str, profile_key: str
) -> None:
    await _create_library(
        db_session, principal, PROFILE, profile_key, _profile_content(coding=True)
    )
    await _create_library(
        db_session,
        principal,
        AGENT,
        agent_key,
        _agent_content(),
        dependencies=[DependencyPin(kind=PROFILE, stable_key=profile_key, version=1)],
    )


async def test_gate_compatible_then_incompatible(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    await _agent_with_profile(db_session, mine, "agent-gate", "prof-gate")
    row = await _register(
        db_session,
        mine,
        machine[0].id,
        capabilities=RuntimeCapabilities(coding=True),
    )
    await _bind_runtime_id(db_session, mine, AGENT, "agent-gate", row.id)
    resolved = await resolution_service.resolve_full(db_session, mine, AGENT, "agent-gate")
    assert resolved.runtime is not None
    assert resolved.runtime.target.runtime_id == row.id
    assert resolved.runtime.compatible is True
    assert resolved.requirements.coding is True
    assert resolved.runtime.provenance is not None
    assert resolved.runtime.provenance.binding_level == RuntimeLevel.USER

    await registry_service.update_runtime(
        db_session,
        mine,
        row,
        RuntimeRegistrationUpdate(capabilities=RuntimeCapabilities()),
        row.version,
    )
    with pytest.raises(HTTPException) as exc:
        await resolution_service.resolve_full(db_session, mine, AGENT, "agent-gate")
    assert exc.value.status_code == 422
    assert exc.value.detail["error_code"] == "runtime_incompatible"
    assert exc.value.detail["unsatisfied"] == ["coding: required"]


async def test_gate_unknown_capability_is_incompatible(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    await _agent_with_profile(db_session, mine, "agent-unk", "prof-unk")
    row = await _register(db_session, mine, machine[0].id)
    await _bind_runtime_id(db_session, mine, AGENT, "agent-unk", row.id)
    with pytest.raises(HTTPException) as exc:
        await resolution_service.resolve_full(db_session, mine, AGENT, "agent-unk")
    assert exc.value.detail["error_code"] == "runtime_incompatible"


# --- Ollama / local: no special case ---------------------------------------


async def test_ollama_local_runtime_uses_generic_path(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    """Local runtimes are normal registry rows: same service, same binding,
    same P5 core — no Ollama server, no network, no downloaded model."""
    mine = await _principal(db_session, machine)
    await _agent_with_profile(db_session, mine, "agent-local", "prof-local")
    row = await _register(
        db_session,
        mine,
        machine[0].id,
        harness="test-harness",
        provider="ollama",
        model="local-model",
        capabilities=RuntimeCapabilities(coding=True, local=True),
    )
    await _bind_runtime_id(db_session, mine, AGENT, "agent-local", row.id)
    resolved = await resolution_service.resolve_full(db_session, mine, AGENT, "agent-local")
    assert resolved.runtime is not None
    assert resolved.runtime.target.provider_ref == "ollama"
    assert resolved.runtime.target.model_ref == "local-model"
    assert resolved.runtime.compatible is True


async def test_revoked_machine_under_runtime_is_non_live(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    mine = await _principal(db_session, machine)
    await _create_library(db_session, mine, AGENT, "agent-a", _agent_content())
    row = await _register(db_session, mine, machine[0].id)
    await _bind_runtime_id(db_session, mine, AGENT, "agent-a", row.id)
    machine[0].credential_revoked_at = datetime.now(UTC)
    await db_session.flush()
    resolved = await bindings_service.resolve_runtime(db_session, mine, AGENT, "agent-a")
    assert resolved.target is None


def test_error_vocabulary_is_closed() -> None:
    assert ResolutionErrorCode.RUNTIME_INCOMPATIBLE.value == "runtime_incompatible"
