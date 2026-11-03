"""P04 profile resolution — pure tests (no DB, no I/O).

The agent definition is produced by the common P5 core `resolve_agent`, then
composed by `resolve_profile`: determinism, origins, capability refusal,
machine-policy capping and N-1 policy input."""

from __future__ import annotations

import uuid

from studio_contracts.library import LibraryKind, LibraryScope, VersionOrigin
from studio_contracts.profiles import (
    MachinePolicy,
    reference_work_profile,
    resolve_profile,
)
from studio_contracts.resolution import (
    AgentResolutionSnapshot,
    ResolutionNode,
    ResolvedAgentDefinition,
    RuntimeCandidate,
    resolve_agent,
)
from studio_contracts.runtime import RuntimeLevel, RuntimeTarget

AGENT_KEY = "dev-agent"


def _definition(
    level: RuntimeLevel | None = RuntimeLevel.USER,
    harness: str = "claude",
    **capabilities: object,
) -> ResolvedAgentDefinition:
    node = ResolutionNode(
        resource_id=uuid.uuid5(uuid.NAMESPACE_URL, "studio-os:p04:agent"),
        kind=LibraryKind.AGENT_DEFINITION,
        stable_key=AGENT_KEY,
        scope=LibraryScope.STUDIO,
        version=3,
        version_origin=VersionOrigin.ACTIVE,
        content={"content_schema": "studio.library.agent_definition/v1", "summary": "x"},
    )
    candidates = []
    if level is not None:
        target = RuntimeTarget(
            harness_ref=harness,
            model_ref="model_a",
            capabilities=capabilities,  # type: ignore[arg-type]
        )
        candidates.append(
            RuntimeCandidate(
                level=level, kind=LibraryKind.AGENT_DEFINITION, stable_key=AGENT_KEY, target=target
            )
        )
    return resolve_agent(AgentResolutionSnapshot(agent=node, runtime_candidates=candidates))


CODING_CAPS = {"coding": True, "tools": ["command_execution", "file_read", "file_write"]}
OPEN_POLICY = MachinePolicy(
    opt_in=True,
    max_concurrent=1,
    allowed_harnesses=["claude"],
    permissions=["read", "write", "execute", "network", "launch"],
)


def test_resolution_is_deterministic_and_carries_origins() -> None:
    profile = reference_work_profile("coding", AGENT_KEY)
    first = resolve_profile(profile, _definition(**CODING_CAPS), OPEN_POLICY)
    second = resolve_profile(profile, _definition(**CODING_CAPS), OPEN_POLICY)
    assert first.model_dump_json() == second.model_dump_json()
    assert first.accepted and first.authoritative is False
    assert first.elements[0].origin == "library" and first.elements[0].version == 3
    assert first.runtime_origin == "runtime_binding"
    assert first.effective_permissions == ["read", "write", "execute", "launch"]
    assert {d.origin for d in first.permissions} == {"machine_policy"}


def test_session_override_origin_is_reported() -> None:
    profile = reference_work_profile("coding", AGENT_KEY)
    preview = resolve_profile(
        profile, _definition(level=RuntimeLevel.SESSION, **CODING_CAPS), OPEN_POLICY
    )
    assert preview.runtime_origin == "session_override"


def test_capability_incompatible_runtime_is_refused() -> None:
    profile = reference_work_profile("coding", AGENT_KEY)
    preview = resolve_profile(profile, _definition(coding=False, tools=["file_read"]), OPEN_POLICY)
    assert not preview.accepted
    codes = [r.code for r in preview.refusals]
    assert codes == ["capability_incompatible"]
    assert preview.refusals[0].details["unsatisfied"]


def test_read_only_profile_fits_a_read_only_runtime() -> None:
    profile = reference_work_profile("architecture-read-only", AGENT_KEY)
    preview = resolve_profile(profile, _definition(tools=["file_read"]), OPEN_POLICY)
    assert preview.accepted
    assert preview.effective_permissions == ["read"]


def test_no_runtime_is_refused() -> None:
    profile = reference_work_profile("architecture-read-only", AGENT_KEY)
    preview = resolve_profile(profile, _definition(level=None), OPEN_POLICY)
    assert [r.code for r in preview.refusals] == ["no_runtime_selected"]


def test_permissions_are_capped_by_machine_policy() -> None:
    profile = reference_work_profile("coding", AGENT_KEY)
    policy = MachinePolicy(
        opt_in=True, max_concurrent=1, allowed_harnesses=["claude"], permissions=["read", "network"]
    )
    preview = resolve_profile(profile, _definition(**CODING_CAPS), policy)
    assert preview.effective_permissions == ["read"]
    assert "network" not in preview.effective_permissions  # never beyond the ask either
    denied = sorted(r.subject for r in preview.refusals if r.code == "permission_denied")
    assert denied == ["execute", "launch", "write"]


def test_machine_without_opt_in_or_harness_grants_nothing() -> None:
    profile = reference_work_profile("coding", AGENT_KEY)
    policy = MachinePolicy(
        opt_in=False, max_concurrent=1, allowed_harnesses=[], permissions=["read", "write"]
    )
    preview = resolve_profile(profile, _definition(**CODING_CAPS), policy)
    assert preview.effective_permissions == []
    assert {r.code for r in preview.refusals} == {"machine_opt_in_off", "harness_not_allowed"}


def test_n_minus_one_policy_without_permissions_fails_closed() -> None:
    profile = reference_work_profile("architecture-read-only", AGENT_KEY)
    legacy = MachinePolicy.model_validate(
        {"opt_in": True, "max_concurrent": 1, "allowed_harnesses": ["claude"]}
    )
    preview = resolve_profile(profile, _definition(tools=["file_read"]), legacy)
    assert preview.effective_permissions == []
    assert [r.code for r in preview.refusals] == ["permission_denied"]
