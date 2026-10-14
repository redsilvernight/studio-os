"""Replay preview (P04-replay-option, additive): compare the execution
snapshot of a terminal attempt with what a retry would use today.

The preview is read-only: it never creates a launch. A replay is the P02
retry (`POST /task-launches/{id}/retry`) carrying a `TaskLaunchReplayConfirmation`
that names the snapshot and the preview it accepts; the server recomputes the
preview, refuses a stale one, and records the accepted basis on the new
attempt. The source snapshot is never rewritten.

A replay re-runs with the *current* Library resolution, rights and machine
policy, on the task branch as it is now: recorded versions that changed or
disappeared are substitutions the requester must accept, never silently
re-pinned.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from studio_contracts.common import ContractModel
from studio_contracts.execution_snapshot import Digest, SnapshotResourceRole

REPLAY_MAX_DIFFERENCES = 500
ReplayLabel = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ReplayVerdict(StrEnum):
    READY = "ready"
    LIMITED = "limited"
    REFUSED = "refused"


class ReplaySeverity(StrEnum):
    REFUSAL = "refusal"
    LIMITATION = "limitation"


class ReplayLimitationCode(StrEnum):
    """Closed vocabulary. Refusals block the replay; limitations must be
    accepted with the preview."""

    LAUNCH_NOT_TERMINAL = "launch_not_terminal"
    ALREADY_RETRIED = "already_retried"
    SNAPSHOT_MISSING = "snapshot_missing"
    SNAPSHOT_CAPTURE_FAILED = "snapshot_capture_failed"
    NOT_AUTHORIZED = "not_authorized"
    TARGET_NOT_ADMISSIBLE = "target_not_admissible"
    AGENT_UNRESOLVABLE = "agent_unresolvable"
    RESOLUTION_UNRECORDED = "resolution_unrecorded"
    LIBRARY_VERSION_UNAVAILABLE = "library_version_unavailable"
    SOURCE_WORKTREE_DIRTY = "source_worktree_dirty"
    SOURCE_GIT_UNRECORDED = "source_git_unrecorded"
    GIT_STATE_NOT_PINNED = "git_state_not_pinned"
    PROFILE_RECHECKED_ON_MACHINE = "profile_rechecked_on_machine"
    OUTPUT_NOT_REPRODUCIBLE = "output_not_reproducible"


REFUSAL_CODES: frozenset[ReplayLimitationCode] = frozenset(
    {
        ReplayLimitationCode.LAUNCH_NOT_TERMINAL,
        ReplayLimitationCode.ALREADY_RETRIED,
        ReplayLimitationCode.SNAPSHOT_MISSING,
        ReplayLimitationCode.SNAPSHOT_CAPTURE_FAILED,
        ReplayLimitationCode.NOT_AUTHORIZED,
        ReplayLimitationCode.TARGET_NOT_ADMISSIBLE,
        ReplayLimitationCode.AGENT_UNRESOLVABLE,
    }
)


class ReplayLimitation(ContractModel):
    code: ReplayLimitationCode
    severity: ReplaySeverity
    subject: ReplayLabel | None = None


class ReplayChange(StrEnum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    ADDED = "added"
    REMOVED = "removed"
    UNAVAILABLE = "unavailable"


class ReplaySubjectKind(StrEnum):
    HARNESS = "harness"
    RESOURCE = "resource"
    RUNTIME = "runtime"


class ReplayDifference(ContractModel):
    """One compared element. `recorded` / `current` are short references
    (`v3 sha256:…`, a harness id, a runtime key), never content."""

    subject_kind: ReplaySubjectKind
    role: SnapshotResourceRole | None = None
    stable_key: ReplayLabel
    recorded: ReplayLabel | None = None
    current: ReplayLabel | None = None
    change: ReplayChange


class TaskLaunchReplayPreview(ContractModel):
    """Read model of `GET /task-launches/{id}/replay-preview`. `preview_digest`
    covers every field except itself and `generated_at`: the same sources
    give the same digest, and a retry confirming another digest is stale."""

    source_launch_id: UUID
    snapshot_id: UUID | None = None
    snapshot_content_hash: Digest | None = None
    verdict: ReplayVerdict
    differences: list[ReplayDifference] = Field(
        default_factory=list, max_length=REPLAY_MAX_DIFFERENCES
    )
    limitations: list[ReplayLimitation] = Field(default_factory=list)
    preview_digest: Digest
    generated_at: datetime


class TaskLaunchReplayConfirmation(ContractModel):
    """Optional part of a retry body: the requester accepts this preview of
    this snapshot, limitations and substitutions included."""

    snapshot_content_hash: Digest
    preview_digest: Digest


class TaskLaunchReplayBasis(ContractModel):
    """Recorded on the attempt a replay created (additive on the view):
    which snapshot it replays and which substitutions were accepted."""

    source_launch_id: UUID
    snapshot_content_hash: Digest
    preview_digest: Digest
    verdict: ReplayVerdict
    substitutions: list[ReplayDifference] = Field(
        default_factory=list, max_length=REPLAY_MAX_DIFFERENCES
    )
    limitation_codes: list[ReplayLimitationCode] = Field(default_factory=list)


def verdict_for(limitations: list[ReplayLimitation]) -> ReplayVerdict:
    if any(item.severity is ReplaySeverity.REFUSAL for item in limitations):
        return ReplayVerdict.REFUSED
    if limitations:
        return ReplayVerdict.LIMITED
    return ReplayVerdict.READY


def limitation(code: ReplayLimitationCode, subject: str | None = None) -> ReplayLimitation:
    severity = ReplaySeverity.REFUSAL if code in REFUSAL_CODES else ReplaySeverity.LIMITATION
    return ReplayLimitation(code=code, severity=severity, subject=subject)


def preview_digest(
    *,
    source_launch_id: UUID,
    snapshot_content_hash: str | None,
    verdict: ReplayVerdict,
    differences: list[ReplayDifference],
    limitations: list[ReplayLimitation],
) -> str:
    body = {
        "source_launch_id": str(source_launch_id),
        "snapshot_content_hash": snapshot_content_hash,
        "verdict": verdict.value,
        "differences": [item.model_dump(mode="json") for item in differences],
        "limitations": [item.model_dump(mode="json") for item in limitations],
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def substitutions(differences: list[ReplayDifference]) -> list[ReplayDifference]:
    return [item for item in differences if item.change is not ReplayChange.UNCHANGED]
