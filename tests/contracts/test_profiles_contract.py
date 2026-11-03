"""P04 profile contract (DEC-0198): versioning N/N-1, closed vocabularies,
reference profiles, fail-closed machine policy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from studio_contracts import PROFILE_CONTRACT_VERSION
from studio_contracts.local.launch import LaunchSettings
from studio_contracts.profiles import (
    PROFILE_MIN_COMPATIBLE_VERSION,
    REFERENCE_PROFILES,
    MachinePolicy,
    WorkProfile,
    effective_permissions,
    reference_work_profile,
)


def _profile(**overrides: object) -> dict[str, object]:
    return {"stable_key": "p", "title": "P", "agent_stable_key": "a", **overrides}


def test_current_and_previous_versions_are_read() -> None:
    assert WorkProfile.model_validate(_profile()).contract_version == PROFILE_CONTRACT_VERSION
    legacy = WorkProfile.model_validate(_profile(contract_version=PROFILE_MIN_COMPATIBLE_VERSION))
    assert legacy.contract_version == max(1, PROFILE_CONTRACT_VERSION - 1)


@pytest.mark.parametrize(
    "version", [PROFILE_CONTRACT_VERSION + 1, PROFILE_MIN_COMPATIBLE_VERSION - 1]
)
def test_other_versions_fail_closed(version: int) -> None:
    with pytest.raises(ValidationError):
        WorkProfile.model_validate(_profile(contract_version=version))


def test_permission_vocabulary_is_closed_and_unique() -> None:
    with pytest.raises(ValidationError):
        WorkProfile.model_validate(_profile(permissions=["admin"]))
    with pytest.raises(ValidationError):
        WorkProfile.model_validate(_profile(permissions=["read", "read"]))
    with pytest.raises(ValidationError):
        MachinePolicy(opt_in=True, max_concurrent=1, permissions=["sudo"])  # type: ignore[list-item]


def test_n_minus_one_launch_settings_parse_as_policy_granting_nothing() -> None:
    legacy = LaunchSettings(opt_in=True, max_concurrent=1, allowed_harnesses=["claude"])
    policy = MachinePolicy.model_validate(legacy.model_dump())
    assert policy.permissions is None
    decisions = effective_permissions(["read", "write"], policy)
    assert [d.granted for d in decisions] == [False, False]


def test_reference_profiles_declare_capabilities_and_refusals() -> None:
    assert set(REFERENCE_PROFILES) == {"coding", "architecture-read-only"}
    coding = REFERENCE_PROFILES["coding"]
    assert coding.required_capabilities.coding is True
    assert "file_write" in coding.required_capabilities.tools_required
    read_only = REFERENCE_PROFILES["architecture-read-only"]
    assert read_only.permissions == ["read"]
    for ref in REFERENCE_PROFILES.values():
        assert "capability_incompatible" in ref.refusal_reasons
    profile = reference_work_profile("coding", "dev-agent")
    assert profile.agent_stable_key == "dev-agent"
    assert profile.permissions == ["read", "write", "execute", "launch"]
    with pytest.raises(KeyError):
        reference_work_profile("unknown", "dev-agent")
