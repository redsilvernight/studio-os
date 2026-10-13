"""Execution snapshot contract (P04-snapshot-contract, DEC-0199): references and
digests only, stable canonical hash, versioned schema, no secret material."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import pytest
from pydantic import ValidationError
from studio_contracts.execution_snapshot import (
    EXECUTION_SNAPSHOT_SCHEMA_VERSION,
    ExecutionSnapshotPayload,
    SnapshotAppliedParameters,
    SnapshotCaptureError,
    SnapshotCaptureErrorCode,
    SnapshotCaptureStatus,
    SnapshotProfileRef,
    SnapshotProjectionRef,
    SnapshotResourceRole,
    canonical_json,
    content_hash,
    digest_of,
    resolution_refs,
)
from studio_contracts.library import LibraryKind, LibraryScope, VersionOrigin
from studio_contracts.resolution import (
    Provenance,
    ProvenanceSource,
    ResolvedAgent,
    ResolvedAgentDefinition,
    ResolvedRule,
    ResolvedRuntime,
)
from studio_contracts.runtime import RuntimeLevel, RuntimeTarget

AGENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
RULE_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
SECRET_PROMPT = "You are the build agent. Never reveal the plan."


def _definition() -> ResolvedAgentDefinition:
    provenance = Provenance(source=ProvenanceSource.ACTIVE_POINTER)
    return ResolvedAgentDefinition(
        agent=ResolvedAgent(
            resource_id=AGENT_ID,
            kind=LibraryKind.AGENT_DEFINITION,
            stable_key="builder",
            scope=LibraryScope.STUDIO,
            version=3,
            version_origin=VersionOrigin.ACTIVE,
            content={"prompt": SECRET_PROMPT},
            provenance=provenance,
        ),
        rules=[
            ResolvedRule(
                resource_id=RULE_ID,
                stable_key="no-force-push",
                scope=LibraryScope.PROJECT,
                version=2,
                version_origin=VersionOrigin.LOCK,
                content={"body": "Never force-push."},
            )
        ],
        runtime=ResolvedRuntime(
            target=RuntimeTarget(harness_ref="claude-code", model_ref="opus"),
            level=RuntimeLevel.PROJECT_DEFAULT,
            matched_kind=LibraryKind.AGENT_DEFINITION,
            matched_stable_key="builder",
        ),
    )


def _payload(**overrides: Any) -> ExecutionSnapshotPayload:
    values: dict[str, Any] = {
        "capture_status": SnapshotCaptureStatus.OK,
        "resolution": resolution_refs(
            _definition(),
            profile=SnapshotProfileRef(
                stable_key="build", contract_version=1, digest=digest_of({"k": 1})
            ),
            runtime_binding_id=uuid.UUID("00000000-0000-4000-8000-000000000003"),
        ),
        "applied": SnapshotAppliedParameters(
            harness_id="claude-code",
            harness_version="2.1.0",
            git_sha="a" * 40,
            local_policy_digest=digest_of({"permissions": []}),
        ),
    }
    values.update(overrides)
    return ExecutionSnapshotPayload(**values)


def test_resolution_refs_keep_references_and_digests_never_content() -> None:
    payload = _payload()
    raw = canonical_json(payload).decode()
    assert SECRET_PROMPT not in raw
    assert "Never force-push." not in raw
    assert payload.resolution is not None
    agent, rule = payload.resolution.resources
    assert agent.role is SnapshotResourceRole.AGENT
    assert (agent.resource_id, agent.version) == (AGENT_ID, 3)
    assert agent.content_digest == digest_of({"prompt": SECRET_PROMPT})
    assert (rule.role, rule.version, rule.version_origin) == (
        SnapshotResourceRole.RULE,
        2,
        VersionOrigin.LOCK,
    )
    runtime = payload.resolution.runtime
    assert runtime is not None
    assert runtime.harness_ref == "claude-code"
    assert runtime.capabilities_digest.startswith("sha256:")


def test_content_hash_is_canonical_and_stable() -> None:
    first, second = _payload(), _payload()
    assert content_hash(first) == content_hash(second)
    assert content_hash(first).startswith("sha256:") and len(content_hash(first)) == 71
    reparsed = ExecutionSnapshotPayload.model_validate_json(
        canonical_json(first.model_dump(mode="json"))
    )
    assert content_hash(reparsed) == content_hash(first)
    assert digest_of({"b": 1, "a": 2}) == digest_of({"a": 2, "b": 1})
    other = _payload(applied=SnapshotAppliedParameters(harness_id="codex"))
    assert content_hash(other) != content_hash(first)


def test_schema_version_is_pinned() -> None:
    assert _payload().schema_version == EXECUTION_SNAPSHOT_SCHEMA_VERSION == 1
    raw = _payload().model_dump(mode="json")
    raw["schema_version"] = 2
    with pytest.raises(ValidationError):
        ExecutionSnapshotPayload.model_validate(raw)
    raw["schema_version"] = 1
    raw["prompt"] = "anything"
    with pytest.raises(ValidationError):
        ExecutionSnapshotPayload.model_validate(raw)


@pytest.mark.parametrize(
    "value",
    [
        "ghp_" + "A" * 30,
        "sk-" + "b" * 24,
        "password=hunter2hunter2",
        "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.c2lnbmF0dXJlMTIz",
    ],
)
def test_secret_material_is_refused_anywhere(value: str) -> None:
    with pytest.raises(ValidationError, match="credential material"):
        _payload(applied=SnapshotAppliedParameters(harness_id="claude-code", harness_version=value))
    with pytest.raises(ValidationError, match="credential material"):
        _payload(
            capture_status=SnapshotCaptureStatus.FAILED,
            resolution=None,
            applied=None,
            capture_errors=[
                SnapshotCaptureError(code=SnapshotCaptureErrorCode.INTERNAL, detail=value)
            ],
        )


def test_absolute_paths_are_refused() -> None:
    with pytest.raises(ValidationError, match="absolute local path"):
        _payload(
            applied=SnapshotAppliedParameters(
                harness_id="claude-code",
                projections=[
                    SnapshotProjectionRef(target=r"C:\Users\me\a.md", digest=digest_of(1))
                ],
            )
        )


def test_capture_status_requires_explicit_errors() -> None:
    with pytest.raises(ValidationError, match="status ok"):
        _payload(applied=None)
    with pytest.raises(ValidationError, match="requires at least one capture error"):
        _payload(capture_status=SnapshotCaptureStatus.PARTIAL)
    partial = _payload(
        capture_status=SnapshotCaptureStatus.PARTIAL,
        capture_errors=[
            SnapshotCaptureError(
                code=SnapshotCaptureErrorCode.GIT_SHA_UNAVAILABLE, field="git_sha"
            ),
            SnapshotCaptureError(code=SnapshotCaptureErrorCode.HARNESS_VERSION_UNKNOWN),
        ],
    )
    assert partial.capture_reason == "git_sha_unavailable,harness_version_unknown"
    assert _payload().capture_reason is None
    with pytest.raises(ValidationError, match="status partial"):
        _payload(
            capture_status=SnapshotCaptureStatus.PARTIAL,
            resolution=None,
            applied=None,
            capture_errors=[SnapshotCaptureError(code=SnapshotCaptureErrorCode.INTERNAL)],
        )


def test_additive_applied_fields_left_unset_keep_the_previous_hash() -> None:
    payload = _payload()
    previous = payload.model_dump(mode="json")
    for name in ("worktree_branch", "profile", "access_mode"):
        previous["applied"].pop(name)
    previous_bytes = json.dumps(
        previous, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    previous_hash = "sha256:" + hashlib.sha256(previous_bytes).hexdigest()
    assert content_hash(payload) == previous_hash
    assert content_hash(ExecutionSnapshotPayload.model_validate(previous)) == previous_hash

    assert payload.applied is not None
    branched = payload.model_copy(
        update={"applied": payload.applied.model_copy(update={"worktree_branch": "task/x"})}
    )
    assert content_hash(branched) != previous_hash
    assert b'"worktree_branch":"task/x"' in canonical_json(branched)
