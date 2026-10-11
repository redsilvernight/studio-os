"""P04 — composed work profiles (DEC-0198).

A work profile is a thin composition of existing primitives: one Library
`agent_definition` (resolved, with its rules/skills/model profile, by the
common P5 resolver `resolve_agent`), the runtime that resolver already picked
(RuntimeBinding levels, model profile key, session overrides — DEC-0068
precedence, not restated here) and a machine policy that reuses the local
`LaunchSettings`. No new configuration or authorization layer.

`resolve_profile` is pure and deterministic. Its output is an explanatory
preview with no authority: the machine applies the final decision locally.
Permissions are always the intersection of what the profile asks for and what
the machine policy allows; an absent machine `permissions` grants nothing.

Versioning: a profile document declares `contract_version`; N and N-1 are
read, anything else is refused. `MachinePolicy.permissions` is additive, so an
N-1 `LaunchSettings` payload still parses and fails closed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from studio_contracts import PROFILE_CONTRACT_VERSION
from studio_contracts.common import ContractModel
from studio_contracts.library import (
    CapabilityRequirement,
    LibraryKind,
    RuntimeCapabilities,
    check_compatibility,
)
from studio_contracts.local.launch import LaunchSettings
from studio_contracts.resolution import (
    ProvenanceSource,
    ResolvedAgentDefinition,
    ResolvedRuntime,
)

PROFILE_MIN_COMPATIBLE_VERSION = max(1, PROFILE_CONTRACT_VERSION - 1)

ProfilePermission = Literal["read", "write", "execute", "network", "launch"]
ValueOrigin = Literal[
    "library", "runtime_binding", "model_profile", "session_override", "machine_policy"
]
ProfileRefusalCode = Literal[
    "capability_incompatible",
    "no_runtime_selected",
    "machine_opt_in_off",
    "permission_denied",
    "harness_not_allowed",
]

_PERMISSION_ORDER: tuple[ProfilePermission, ...] = (
    "read",
    "write",
    "execute",
    "network",
    "launch",
)


class MachinePolicy(LaunchSettings):
    """The local launch settings plus optional permissions (additive).
    `None` (absent) authorizes nothing: fail closed. Never persisted to
    `launch.json` nor sent to a daemon without a negotiated capability: an
    N-1 `LaunchSettings` forbids the extra field."""

    permissions: list[ProfilePermission] | None = None


class WorkProfile(ContractModel):
    """What a profile asks for: an agent definition (by stable key, resolved by
    the common resolver), the capabilities the work needs, and permissions it
    requests. It declares no rule text and grants nothing by itself."""

    contract_version: int = PROFILE_CONTRACT_VERSION
    stable_key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    agent_stable_key: str = Field(min_length=1, max_length=200)
    required_capabilities: CapabilityRequirement = CapabilityRequirement()
    permissions: list[ProfilePermission] = []

    @field_validator("contract_version")
    @classmethod
    def _supported_version(cls, version: int) -> int:
        if version not in (PROFILE_MIN_COMPATIBLE_VERSION, PROFILE_CONTRACT_VERSION):
            raise ValueError(
                f"profile contract_version {version} unsupported "
                f"(accepted: {PROFILE_MIN_COMPATIBLE_VERSION}, {PROFILE_CONTRACT_VERSION})"
            )
        return version

    @field_validator("permissions")
    @classmethod
    def _unique_permissions(cls, permissions: list[ProfilePermission]) -> list[ProfilePermission]:
        if len(set(permissions)) != len(permissions):
            raise ValueError("a permission is requested at most once")
        return permissions


class ReferenceProfile(ContractModel):
    """A reference profile template: capabilities required, permissions asked,
    and the refusal reasons a preview of it can emit."""

    stable_key: str
    title: str
    required_capabilities: CapabilityRequirement
    permissions: list[ProfilePermission]
    refusal_reasons: list[ProfileRefusalCode]


_ALL_REFUSALS: list[ProfileRefusalCode] = [
    "capability_incompatible",
    "no_runtime_selected",
    "machine_opt_in_off",
    "permission_denied",
    "harness_not_allowed",
]

REFERENCE_PROFILES: dict[str, ReferenceProfile] = {
    "coding": ReferenceProfile(
        stable_key="coding",
        title="Coding",
        required_capabilities=CapabilityRequirement(
            coding=True, tools_required=["command_execution", "file_read", "file_write"]
        ),
        permissions=["read", "write", "execute", "launch"],
        refusal_reasons=_ALL_REFUSALS,
    ),
    "architecture-read-only": ReferenceProfile(
        stable_key="architecture-read-only",
        title="Architecture (read-only)",
        required_capabilities=CapabilityRequirement(tools_required=["file_read"]),
        permissions=["read"],
        refusal_reasons=_ALL_REFUSALS,
    ),
}


def reference_work_profile(stable_key: str, agent_stable_key: str) -> WorkProfile:
    """Materializes a reference profile for one agent definition.
    Raises `KeyError` for an unknown reference key (never a silent default)."""

    ref = REFERENCE_PROFILES[stable_key]
    return WorkProfile(
        stable_key=ref.stable_key,
        title=ref.title,
        agent_stable_key=agent_stable_key,
        required_capabilities=ref.required_capabilities,
        permissions=list(ref.permissions),
    )


class ProfileElement(ContractModel):
    kind: LibraryKind
    stable_key: str
    version: int
    origin: ValueOrigin


class PermissionDecision(ContractModel):
    permission: ProfilePermission
    granted: bool
    origin: Literal["machine_policy"] = "machine_policy"


class ProfileRefusal(ContractModel):
    code: ProfileRefusalCode
    subject: str
    details: dict[str, object] = {}


class ProfilePreview(ContractModel):
    """Explanatory preview: every effective value with its origin, every
    refusal. `authoritative` is always false — the machine decides."""

    contract_version: int = PROFILE_CONTRACT_VERSION
    stable_key: str
    authoritative: Literal[False] = False
    accepted: bool
    elements: list[ProfileElement]
    runtime: ResolvedRuntime | None = None
    runtime_origin: ValueOrigin | None = None
    permissions: list[PermissionDecision]
    effective_permissions: list[ProfilePermission]
    refusals: list[ProfileRefusal] = []


def effective_permissions(
    requested: list[ProfilePermission], policy: MachinePolicy
) -> list[PermissionDecision]:
    """Intersection of the request and the machine policy, canonical order.
    No opt-in or absent policy permissions → nothing granted."""

    allowed = set(policy.permissions or []) if policy.opt_in else set()
    return [
        PermissionDecision(permission=p, granted=p in allowed)
        for p in _PERMISSION_ORDER
        if p in requested
    ]


def _elements(definition: ResolvedAgentDefinition) -> list[ProfileElement]:
    agent = definition.agent
    elements = [
        ProfileElement(
            kind=agent.kind, stable_key=agent.stable_key, version=agent.version, origin="library"
        )
    ]
    elements += [
        ProfileElement(
            kind=LibraryKind.RULE, stable_key=r.stable_key, version=r.version, origin="library"
        )
        for r in definition.rules
    ]
    elements += [
        ProfileElement(
            kind=LibraryKind.SKILL, stable_key=s.stable_key, version=s.version, origin="library"
        )
        for s in definition.skills
    ]
    if definition.model_profile is not None:
        mp = definition.model_profile
        elements.append(
            ProfileElement(
                kind=LibraryKind.MODEL_PROFILE,
                stable_key=mp.stable_key,
                version=mp.version,
                origin="model_profile",
            )
        )
    return elements


def _runtime_origin(runtime: ResolvedRuntime) -> ValueOrigin:
    if (
        runtime.provenance is not None
        and runtime.provenance.source is ProvenanceSource.SESSION_OVERRIDE
    ):
        return "session_override"
    return "runtime_binding"


def resolve_profile(
    profile: WorkProfile, definition: ResolvedAgentDefinition, policy: MachinePolicy
) -> ProfilePreview:
    """Pure composition of an already-resolved agent definition (common P5
    resolver output) with the profile's asks and the machine policy."""

    if definition.agent.stable_key != profile.agent_stable_key:
        raise ValueError("definition does not match profile.agent_stable_key")

    refusals: list[ProfileRefusal] = []
    runtime = definition.runtime
    runtime_origin: ValueOrigin | None = None
    if runtime is None:
        refusals.append(ProfileRefusal(code="no_runtime_selected", subject=profile.stable_key))
    else:
        runtime_origin = _runtime_origin(runtime)
        unsatisfied = list(runtime.unsatisfied) + check_compatibility(
            profile.required_capabilities,
            runtime.target.capabilities or RuntimeCapabilities(),
        )
        if not runtime.compatible or unsatisfied:
            refusals.append(
                ProfileRefusal(
                    code="capability_incompatible",
                    subject=f"{runtime.matched_kind.value}:{runtime.matched_stable_key}",
                    details={"unsatisfied": sorted(set(unsatisfied)), "origin": runtime_origin},
                )
            )
        harness = runtime.target.harness_ref
        if harness is not None and harness not in policy.allowed_harnesses:
            refusals.append(ProfileRefusal(code="harness_not_allowed", subject=harness))

    if not policy.opt_in:
        refusals.append(ProfileRefusal(code="machine_opt_in_off", subject="machine"))
    decisions = effective_permissions(profile.permissions, policy)
    refusals += [
        ProfileRefusal(code="permission_denied", subject=d.permission)
        for d in decisions
        if not d.granted and policy.opt_in
    ]

    return ProfilePreview(
        stable_key=profile.stable_key,
        accepted=not refusals,
        elements=_elements(definition),
        runtime=runtime,
        runtime_origin=runtime_origin,
        permissions=decisions,
        effective_permissions=[d.permission for d in decisions if d.granted],
        refusals=sorted(refusals, key=lambda r: (r.code, r.subject)),
    )
