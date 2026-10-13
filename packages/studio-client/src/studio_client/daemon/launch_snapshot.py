"""Execution snapshot capture on the machine (P04-snapshot-capture, DEC-0199).

Turns what the executor observed for one launch attempt into an immutable
`ExecutionSnapshotPayload`: the resolver output and the profile pin the launch
was previewed against (`resolution`) beside what this machine really applied
(`applied`: harness version, digests of the projected files, the commit and
branch git reports for the worktree, the local policy digest, the profile pin
recomputed at run start and the enforced mode).

Pure and deterministic: the same observations always give the same payload,
hence the same `content_hash`, so a replayed capture is a no-op server-side.
No prompt, file content, absolute path or secret is ever copied: bodies become
digests, and a value that looks like a secret or a local path is dropped and
named by a `redaction_required` error — never masked, never logged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from studio_contracts.execution_snapshot import (
    ExecutionSnapshotPayload,
    SnapshotAppliedParameters,
    SnapshotCaptureError,
    SnapshotCaptureErrorCode,
    SnapshotCaptureStatus,
    SnapshotProfileRef,
    SnapshotProjectionRef,
    SnapshotResolution,
    digest_of,
    resolution_refs,
)
from studio_contracts.local.common import (
    contains_absolute_path,
    contains_secret_material,
)
from studio_contracts.profiles import LaunchProfilePin, MachinePolicy
from studio_contracts.resolution import ResolvedAgentDefinition

from studio_client.daemon.launch_prepare import WorktreeObservation

Code = SnapshotCaptureErrorCode


@dataclass(frozen=True)
class SnapshotInputs:
    """Everything the executor observed, as data. `not_prepared` is a closed
    token (`profile_refused`, `preparation_failed:<step>`) set when no
    worktree exists; `projections` is `None` when the digests could not be
    computed; `definition_error` names why the resolver output is missing."""

    harness_id: str
    agent_stable_key: str | None = None
    definition: ResolvedAgentDefinition | None = None
    definition_error: str | None = None
    preview_profile: LaunchProfilePin | None = None
    applied_profile: LaunchProfilePin | None = None
    access_mode: str | None = None
    harness_version: str | None = None
    worktree: WorktreeObservation | None = None
    not_prepared: str | None = None
    projections: Sequence[tuple[str, str]] | None = field(default_factory=tuple)
    local_policy: MachinePolicy | None = None


def _safe(value: str) -> bool:
    return not contains_secret_material(value) and not contains_absolute_path(value)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for key, item in value.items() for s in (*_strings(str(key)), *_strings(item))]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _profile_ref(pin: LaunchProfilePin | None) -> SnapshotProfileRef | None:
    if pin is None:
        return None
    return SnapshotProfileRef(
        stable_key=pin.stable_key, contract_version=pin.contract_version, digest=pin.digest
    )


def _error(
    code: SnapshotCaptureErrorCode, field_name: str, detail: str = ""
) -> SnapshotCaptureError:
    return SnapshotCaptureError(code=code, field=field_name, detail=detail)


class _Capture:
    def __init__(self) -> None:
        self.errors: list[SnapshotCaptureError] = []

    def keep(self, value: str | None, field_name: str) -> str | None:
        if not value:
            return None
        if _safe(value):
            return value
        self.errors.append(_error(Code.REDACTION_REQUIRED, field_name))
        return None

    def resolution(self, inputs: SnapshotInputs) -> SnapshotResolution | None:
        agent_key = self.keep(inputs.agent_stable_key, "resolution.agent_stable_key")
        preview = _profile_ref(inputs.preview_profile)
        if agent_key is None:
            if not inputs.agent_stable_key:
                self.errors.append(
                    _error(Code.RESOLUTION_UNAVAILABLE, "resolution", "no_agent_definition")
                )
            return None
        if inputs.definition is None:
            self.errors.append(
                _error(
                    Code.RESOLUTION_UNAVAILABLE,
                    "resolution",
                    inputs.definition_error or "unavailable",
                )
            )
            resolution = SnapshotResolution(agent_stable_key=agent_key, profile=preview)
        else:
            resolution = resolution_refs(inputs.definition, profile=preview)
        if all(_safe(text) for text in _strings(resolution.model_dump(mode="json"))):
            return resolution
        self.errors.append(_error(Code.REDACTION_REQUIRED, "resolution"))
        return None

    def applied(self, inputs: SnapshotInputs) -> SnapshotAppliedParameters:
        version = self.keep(inputs.harness_version, "applied.harness_version")
        if not inputs.harness_version:
            self.errors.append(_error(Code.HARNESS_VERSION_UNKNOWN, "applied.harness_version"))
        git_sha: str | None = None
        dirty: bool | None = None
        branch: str | None = None
        observed = inputs.worktree
        if observed is None:
            self.errors.append(
                _error(Code.GIT_SHA_UNAVAILABLE, "applied.git_sha", inputs.not_prepared or "")
            )
        else:
            git_sha, dirty = observed.git_sha, observed.dirty
            branch = self.keep(observed.branch, "applied.worktree_branch")
            if git_sha is None:
                self.errors.append(
                    _error(Code.GIT_SHA_UNAVAILABLE, "applied.git_sha", observed.problem or "")
                )
            elif observed.problem is not None:
                self.errors.append(
                    _error(Code.WORKTREE_UNVERIFIED, "applied.worktree_branch", observed.problem)
                )
        projections: list[SnapshotProjectionRef] = []
        if observed is not None and inputs.projections is None:
            self.errors.append(_error(Code.PROJECTION_DIGEST_UNAVAILABLE, "applied.projections"))
        for target, digest in inputs.projections or ():
            if _safe(target):
                projections.append(SnapshotProjectionRef(target=target, digest=digest))
            else:
                self.errors.append(_error(Code.REDACTION_REQUIRED, "applied.projections"))
        policy_digest: str | None = None
        if inputs.local_policy is None:
            self.errors.append(_error(Code.LOCAL_POLICY_UNAVAILABLE, "applied.local_policy_digest"))
        else:
            policy_digest = digest_of(inputs.local_policy)
        return SnapshotAppliedParameters(
            harness_id=inputs.harness_id,
            harness_version=version,
            projections=projections,
            git_sha=git_sha,
            git_dirty=dirty,
            local_policy_digest=policy_digest,
            worktree_branch=branch,
            profile=_profile_ref(inputs.applied_profile),
            access_mode=inputs.access_mode,
        )


def build_snapshot_payload(inputs: SnapshotInputs) -> ExecutionSnapshotPayload:
    """`ok` only when every piece is present and proven; otherwise `partial`
    with each missing piece named. A payload the contract still refuses
    becomes a `failed` snapshot carrying no observed value at all."""
    try:
        capture = _Capture()
        resolution = capture.resolution(inputs)
        applied = capture.applied(inputs)
        status = SnapshotCaptureStatus.PARTIAL if capture.errors else SnapshotCaptureStatus.OK
        return ExecutionSnapshotPayload(
            capture_status=status,
            resolution=resolution,
            applied=applied,
            capture_errors=capture.errors,
        )
    except ValidationError:
        return failed_payload(Code.REDACTION_REQUIRED, "payload_refused")


def failed_payload(code: SnapshotCaptureErrorCode, detail: str) -> ExecutionSnapshotPayload:
    return ExecutionSnapshotPayload(
        capture_status=SnapshotCaptureStatus.FAILED,
        capture_errors=[SnapshotCaptureError(code=code, detail=detail)],
    )
