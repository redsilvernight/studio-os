"""P04 — immutable execution snapshot (DEC-0199).

What a run (one `TaskLaunch` attempt) was effectively configured with,
recorded once and never rewritten. References and fingerprints only:

- the *output* of the common resolver (`resolve_agent` / `resolve_profile`):
  Library ids, versions and content digests, the work profile key/version/
  digest, the runtime binding and model profile references;
- the parameters Bloc B really applied: harness version, digests of the
  projected files, Git SHA, digest of the local policy.

Never a prompt, a rule/skill body, a file content or a secret: bodies are
reduced to a sha256 digest by `digest_of`. Every string of the payload is
scanned for credential material and absolute local paths and refused (there is
no silent masking: a capture that would need redaction is a capture error).

No second resolver: `resolution_refs` only projects an already resolved
`ResolvedAgentDefinition`; it never picks a version.

Identity is `content_hash` — `sha256:` + hex of the canonical JSON (sorted
keys, compact separators, UTF-8) of the payload. The payload does not carry the
launch id, so the same configuration hashes identically across launches.
Replaying the recorded parameters does not guarantee reproducing the AI output.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from studio_contracts.common import ContractModel
from studio_contracts.library import LibraryKind, LibraryScope, VersionOrigin
from studio_contracts.local.common import (
    contains_absolute_path,
    contains_secret_material,
    is_secret_key_name,
)
from studio_contracts.resolution import (
    PreservedReference,
    ResolvedAgentDefinition,
    ResolvedRuntime,
)
from studio_contracts.runtime import RuntimeLevel

EXECUTION_SNAPSHOT_SCHEMA_VERSION: Literal[1] = 1
"""Payload schema version. Bumped on any non-additive change; readers refuse an
unknown version instead of guessing."""

MAX_PAYLOAD_BYTES = 256 * 1024
"""Upper bound of the canonical payload: references only, a larger payload means
content leaked in."""

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
SafeLabel = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class SnapshotCaptureStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class SnapshotCaptureErrorCode(StrEnum):
    """Closed vocabulary of explicit capture errors: a missing piece is named,
    never silently omitted."""

    RESOLUTION_UNAVAILABLE = "resolution_unavailable"
    PROFILE_UNAVAILABLE = "profile_unavailable"
    HARNESS_VERSION_UNKNOWN = "harness_version_unknown"
    PROJECTION_DIGEST_UNAVAILABLE = "projection_digest_unavailable"
    GIT_SHA_UNAVAILABLE = "git_sha_unavailable"
    LOCAL_POLICY_UNAVAILABLE = "local_policy_unavailable"
    REDACTION_REQUIRED = "redaction_required"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    INTERNAL = "internal"
    WORKTREE_UNVERIFIED = "worktree_unverified"
    """Additive: git could not prove that the run's
    worktree (top-level, branch) is the one prepared for the launch."""


class SnapshotResourceRole(StrEnum):
    AGENT = "agent"
    RULE = "rule"
    SKILL = "skill"
    MODEL_PROFILE = "model_profile"
    WORKFLOW = "workflow"
    COMPOSED_AGENT = "composed_agent"


class SnapshotResourceRef(ContractModel):
    """One Library version the resolver selected, with the digest of its
    content (the content itself is never copied)."""

    role: SnapshotResourceRole
    resource_id: UUID
    kind: LibraryKind
    stable_key: SafeLabel
    scope: LibraryScope
    version: int = Field(ge=1)
    version_origin: VersionOrigin
    content_digest: Digest | None = None


class SnapshotRuntimeRef(ContractModel):
    """The runtime the resolver picked: references only, capabilities reduced
    to a digest."""

    level: RuntimeLevel
    matched_kind: LibraryKind
    matched_stable_key: SafeLabel
    runtime_id: UUID | None = None
    runtime_binding_id: UUID | None = None
    harness_ref: SafeLabel | None = None
    provider_ref: SafeLabel | None = None
    model_ref: SafeLabel | None = None
    capabilities_digest: Digest


class SnapshotProfileRef(ContractModel):
    stable_key: SafeLabel
    contract_version: int = Field(ge=1)
    digest: Digest


class SnapshotResolution(ContractModel):
    """Projection of the resolver output. `profile` is the
    pin the launch was previewed/admitted against; `applied.profile` is the
    pin recomputed when the run starts."""

    agent_stable_key: SafeLabel
    profile: SnapshotProfileRef | None = None
    resources: list[SnapshotResourceRef] = Field(default_factory=list, max_length=500)
    runtime: SnapshotRuntimeRef | None = None


class SnapshotProjectionRef(ContractModel):
    """One file the harness adapter projected. `target` is a logical,
    repository-relative identifier — never an absolute path."""

    target: SafeLabel
    digest: Digest


class SnapshotAppliedParameters(ContractModel):
    """What Bloc B really applied on the machine.

    Additive: `worktree_branch` is the branch git
    reports for the run's worktree (observed, never the declared one);
    `profile` is the work profile pin recomputed when the run starts — compare
    it with `resolution.profile`, the pin the launch was previewed/admitted
    against; `access_mode` is the mode the machine finally enforced (`None`
    when it refused to run)."""

    harness_id: SafeLabel
    harness_version: SafeLabel | None = None
    projections: list[SnapshotProjectionRef] = Field(default_factory=list, max_length=500)
    git_sha: GitSha | None = None
    git_dirty: bool | None = None
    local_policy_digest: Digest | None = None
    worktree_branch: SafeLabel | None = None
    profile: SnapshotProfileRef | None = None
    access_mode: SafeLabel | None = None


class SnapshotCaptureError(ContractModel):
    code: SnapshotCaptureErrorCode
    field: SafeLabel | None = None
    detail: Annotated[str, StringConstraints(max_length=500)] = ""


class ExecutionSnapshotPayload(ContractModel):
    """The hashed, immutable body of a snapshot."""

    schema_version: Literal[1] = EXECUTION_SNAPSHOT_SCHEMA_VERSION
    capture_status: SnapshotCaptureStatus
    resolution: SnapshotResolution | None = None
    applied: SnapshotAppliedParameters | None = None
    capture_errors: list[SnapshotCaptureError] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _consistent_status(self) -> ExecutionSnapshotPayload:
        complete = self.resolution is not None and self.applied is not None
        if self.capture_status is SnapshotCaptureStatus.OK:
            if self.capture_errors or not complete:
                raise ValueError("status ok requires resolution, applied and no capture error")
        elif not self.capture_errors:
            raise ValueError(f"status {self.capture_status} requires at least one capture error")
        elif self.capture_status is SnapshotCaptureStatus.PARTIAL and (
            self.resolution is None and self.applied is None
        ):
            raise ValueError("status partial requires resolution or applied")
        return self

    @model_validator(mode="after")
    def _no_secret_material(self) -> ExecutionSnapshotPayload:
        for path, value in _walk(self.model_dump(mode="json")):
            if contains_secret_material(value):
                raise ValueError(f"{path}: value looks like credential material")
            if contains_absolute_path(value):
                raise ValueError(f"{path}: value contains an absolute local path")
        return self

    @property
    def profile_drift(self) -> bool | None:
        """Whether the profile previewed at admission differs from the one
        recomputed when the run started; `None` when either side is unknown."""
        preview = None if self.resolution is None else self.resolution.profile
        applied = None if self.applied is None else self.applied.profile
        if preview is None or applied is None:
            return None
        return preview != applied

    @property
    def capture_reason(self) -> str | None:
        """Short machine-readable reason stored beside the status."""
        if not self.capture_errors:
            return None
        return ",".join(sorted({error.code.value for error in self.capture_errors}))


class ExecutionSnapshot(ContractModel):
    """Read model: one recorded snapshot of one launch attempt."""

    id: UUID
    project_id: UUID
    task_launch_id: UUID
    content_hash: Digest
    schema_version: int
    capture_status: SnapshotCaptureStatus
    capture_reason: str | None = None
    payload: ExecutionSnapshotPayload
    created_at: datetime
    retention_until: datetime


def _walk(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            if is_secret_key_name(str(key)):
                raise ValueError(f"{path}.{key}: secret-named field")
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def canonical_json(value: Any) -> bytes:
    """Deterministic bytes: sorted keys, compact separators, UTF-8."""
    if isinstance(value, ContractModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def digest_of(value: Any) -> str:
    """`sha256:<hex>` of the canonical JSON — how a body becomes a reference."""
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def content_hash(payload: ExecutionSnapshotPayload) -> str:
    return digest_of(payload)


def check_payload_size(payload: ExecutionSnapshotPayload) -> None:
    if len(canonical_json(payload)) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"snapshot payload exceeds {MAX_PAYLOAD_BYTES} bytes")


def _preserved(role: SnapshotResourceRole, ref: PreservedReference) -> SnapshotResourceRef:
    return SnapshotResourceRef(
        role=role,
        resource_id=ref.resource_id,
        kind=ref.kind,
        stable_key=ref.stable_key,
        scope=ref.scope,
        version=ref.version,
        version_origin=ref.version_origin,
    )


def _resources(definition: ResolvedAgentDefinition) -> Iterator[SnapshotResourceRef]:
    agent = definition.agent
    yield SnapshotResourceRef(
        role=SnapshotResourceRole.AGENT,
        resource_id=agent.resource_id,
        kind=agent.kind,
        stable_key=agent.stable_key,
        scope=agent.scope,
        version=agent.version,
        version_origin=agent.version_origin,
        content_digest=digest_of(agent.content),
    )
    for rule in definition.rules:
        yield SnapshotResourceRef(
            role=SnapshotResourceRole.RULE,
            resource_id=rule.resource_id,
            kind=LibraryKind.RULE,
            stable_key=rule.stable_key,
            scope=rule.scope,
            version=rule.version,
            version_origin=rule.version_origin,
            content_digest=digest_of(rule.content),
        )
    for skill in definition.skills:
        yield SnapshotResourceRef(
            role=SnapshotResourceRole.SKILL,
            resource_id=skill.resource_id,
            kind=LibraryKind.SKILL,
            stable_key=skill.stable_key,
            scope=skill.scope,
            version=skill.version,
            version_origin=skill.version_origin,
            content_digest=digest_of(skill.content),
        )
    profile = definition.model_profile
    if profile is not None:
        yield SnapshotResourceRef(
            role=SnapshotResourceRole.MODEL_PROFILE,
            resource_id=profile.resource_id,
            kind=LibraryKind.MODEL_PROFILE,
            stable_key=profile.stable_key,
            scope=profile.scope,
            version=profile.version,
            version_origin=profile.version_origin,
            content_digest=digest_of(profile.requirements),
        )
    for workflow in definition.workflows:
        yield _preserved(SnapshotResourceRole.WORKFLOW, workflow)
    for composed in definition.composed_agents:
        yield _preserved(SnapshotResourceRole.COMPOSED_AGENT, composed.reference)


def _runtime(runtime: ResolvedRuntime, runtime_binding_id: UUID | None) -> SnapshotRuntimeRef:
    target = runtime.target
    return SnapshotRuntimeRef(
        level=runtime.level,
        matched_kind=runtime.matched_kind,
        matched_stable_key=runtime.matched_stable_key,
        runtime_id=target.runtime_id,
        runtime_binding_id=runtime_binding_id,
        harness_ref=target.harness_ref,
        provider_ref=target.provider_ref,
        model_ref=target.model_ref,
        capabilities_digest=digest_of(target.capabilities),
    )


def resolution_refs(
    definition: ResolvedAgentDefinition,
    *,
    profile: SnapshotProfileRef | None = None,
    runtime_binding_id: UUID | None = None,
) -> SnapshotResolution:
    """Project a resolver output into references and digests. Pure, and never a
    second resolution: it only reads what `resolve_agent` already chose."""
    runtime = definition.runtime
    return SnapshotResolution(
        agent_stable_key=definition.agent.stable_key,
        profile=profile,
        resources=list(_resources(definition)),
        runtime=None if runtime is None else _runtime(runtime, runtime_binding_id),
    )
