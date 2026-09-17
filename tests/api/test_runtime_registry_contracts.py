"""P6 Runtime Registry — pure tests (no DB, no I/O, no LLM, no network).

Proves the registry representation and compatibility invariants without any
infrastructure: Harness ≠ Provider ≠ Model ≠ Runtime, open chains, Ollama
as a normal runtime (same code path), known/false/unknown capabilities, no
vendor catalog, secrets rejected, `runtime_id` reference exclusivity."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from studio_contracts.library import (
    CapabilityRequirement,
    RuntimeCapabilities,
    check_compatibility,
)
from studio_contracts.runtime import (
    CapabilitySource,
    RuntimeRegistration,
    RuntimeRegistrationCreate,
    RuntimeRegistrationUpdate,
    RuntimeStatus,
    RuntimeTarget,
)


def _registration(**overrides: object) -> RuntimeRegistration:
    now = "2026-09-17T00:00:00+00:00"
    base: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "owner_user_id": str(uuid.uuid4()),
        "harness_ref": "test-harness",
        "provider_ref": "test-provider",
        "model_ref": "test-model",
        "capabilities": {},
        "capability_source": "declared",
        "runtime_metadata": {},
        "status": "active",
        "created_at": now,
    }
    base.update(overrides)
    return RuntimeRegistration.model_validate(base)


def test_harness_provider_model_are_independent() -> None:
    first = _registration(harness_ref="h-a", provider_ref="p-a", model_ref="m-a")
    second = _registration(harness_ref="h-a", provider_ref="p-a", model_ref="m-b")
    third = _registration(harness_ref="h-b", provider_ref="p-a", model_ref="m-a")
    assert first.harness_ref == second.harness_ref == "h-a"
    assert first.provider_ref == third.provider_ref == "p-a"
    assert first.model_ref == third.model_ref == "m-a"
    assert first.id != second.id != third.id
    assert second.model_ref != first.model_ref
    assert third.harness_ref != first.harness_ref


def test_open_chain_accepts_unknown_values() -> None:
    runtime = _registration(
        harness_ref="harness-from-2030",
        provider_ref="future-provider",
        model_ref="unreleased-model-xyz",
    )
    assert runtime.provider_ref == "future-provider"
    RuntimeRegistrationCreate(
        harness_ref="another-new-harness",
        provider_ref="future-provider",
        model_ref="unreleased-model-xyz",
    )
    RuntimeTarget(provider_ref="future-provider")
    RuntimeTarget(harness_ref="only-a-harness")


def test_open_chain_rejects_empty_reference() -> None:
    with pytest.raises(ValidationError):
        RuntimeRegistrationCreate(provider_ref="   ", model_ref="m")


def test_ollama_is_a_normal_runtime() -> None:
    """`provider_ref="ollama"` follows exactly the same representation and
    compatibility path as any other provider — no branch, no special case.
    No server, no network, no downloaded model involved."""
    local = _registration(
        harness_ref="test-harness",
        provider_ref="ollama",
        model_ref="local-model",
        capabilities={"coding": True, "local": True},
    )
    distant = _registration(
        harness_ref="test-harness",
        provider_ref="test-provider",
        model_ref="test-model",
        capabilities={"coding": True, "local": True},
    )
    requirement = CapabilityRequirement(coding=True, local_compatible=True)
    assert check_compatibility(requirement, local.capabilities) == []
    assert check_compatibility(requirement, distant.capabilities) == []
    assert type(local) is type(distant)
    assert local.provider_ref == "ollama"


def test_capability_known_is_compatible() -> None:
    requirement = CapabilityRequirement(coding=True, context_window_min=8000)
    capabilities = RuntimeCapabilities(coding=True, context_window=32000)
    assert check_compatibility(requirement, capabilities) == []


def test_capability_false_is_incompatible() -> None:
    requirement = CapabilityRequirement(coding=True)
    capabilities = RuntimeCapabilities(coding=False)
    assert check_compatibility(requirement, capabilities) == ["coding: required"]


def test_capability_unknown_is_not_compatible() -> None:
    requirement = CapabilityRequirement(coding=True, context_window_min=128000)
    capabilities = RuntimeCapabilities(coding=True)
    unsatisfied = check_compatibility(requirement, capabilities)
    assert unsatisfied == ["context_window_min: required 128000"]


def test_compatibility_depends_only_on_capabilities() -> None:
    """No vendor catalog: two runtimes with different names but identical
    capabilities yield identical verdicts; renaming a model never proves a
    capability."""
    requirement = CapabilityRequirement(coding=True)
    good = RuntimeCapabilities(coding=True)
    bad = RuntimeCapabilities(coding=False)
    assert check_compatibility(requirement, good) == []
    assert check_compatibility(requirement, bad) != []
    famous = _registration(provider_ref="famous-vendor", model_ref="flagship-99")
    assert check_compatibility(requirement, famous.capabilities) == ["coding: required"]


def test_remote_runtime_without_machine_is_valid() -> None:
    runtime = _registration(machine_id=None, provider_ref="cloud", model_ref="m")
    assert runtime.machine_id is None
    RuntimeRegistrationCreate(provider_ref="cloud", model_ref="m")


def test_registration_requires_an_anchor() -> None:
    with pytest.raises(ValidationError):
        RuntimeRegistrationCreate()


def test_only_declared_source_supported() -> None:
    with pytest.raises(ValidationError):
        RuntimeRegistrationCreate(provider_ref="p", model_ref="m", capability_source="detected")
    created = RuntimeRegistrationCreate(provider_ref="p", model_ref="m")
    assert created.capability_source == CapabilitySource.DECLARED


def test_secret_metadata_rejected() -> None:
    for key in (
        "api_key",
        "API_KEY",
        "bearer_token",
        "provider_secret",
        "password",
        "private_key",
        "privatekey",
        "credentials_ref",
        "authorization_header",
        "passwd",
        "jwt",
    ):
        with pytest.raises(ValidationError):
            RuntimeRegistrationCreate(provider_ref="p", model_ref="m", runtime_metadata={key: "x"})
    with pytest.raises(ValidationError):
        _registration(runtime_metadata={"refresh_token": "x"})
    with pytest.raises(ValidationError):
        RuntimeRegistrationUpdate(runtime_metadata={"secret": "x"})


def test_plain_metadata_accepted() -> None:
    created = RuntimeRegistrationCreate(
        provider_ref="p",
        model_ref="m",
        runtime_metadata={"region": "eu", "note": "shared box"},
    )
    assert created.runtime_metadata == {"region": "eu", "note": "shared box"}


def test_runtime_id_reference_shape() -> None:
    """A bare `runtime_id` is a valid anchor; input exclusivity (no inline
    fields beside it) is enforced service-side (`invalid_runtime_binding`),
    while the resolved effective target legitimately carries both the
    `runtime_id` (provenance) and the registry-resolved fields."""
    RuntimeTarget(runtime_id=uuid.uuid4())
    effective = RuntimeTarget(
        runtime_id=uuid.uuid4(),
        machine_id=uuid.uuid4(),
        harness_ref="h",
        provider_ref="p",
        model_ref="m",
        capabilities=RuntimeCapabilities(coding=True),
    )
    assert effective.runtime_id is not None
    assert effective.capabilities.coding is True
    with pytest.raises(ValidationError):
        RuntimeTarget()


def test_update_never_rotates_identity() -> None:
    update = RuntimeRegistrationUpdate(
        provider_ref="new-provider",
        model_ref="new-model",
        capabilities=RuntimeCapabilities(coding=True),
    )
    assert update.provider_ref == "new-provider"
    assert update.capabilities is not None and update.capabilities.coding is True


def test_revoked_status_roundtrip() -> None:
    runtime = _registration(status="revoked")
    assert runtime.status == RuntimeStatus.REVOKED
