"""P04-replay-option contract: closed limitation vocabulary, verdict derived
from severities, a digest that ignores `generated_at`, additive retry/view."""

from __future__ import annotations

import uuid

from studio_contracts.task_launch import TaskLaunchRetry
from studio_contracts.task_launch_replay import (
    REFUSAL_CODES,
    ReplayChange,
    ReplayDifference,
    ReplayLimitationCode,
    ReplaySeverity,
    ReplaySubjectKind,
    ReplayVerdict,
    limitation,
    preview_digest,
    substitutions,
    verdict_for,
)


def _diff(change: ReplayChange) -> ReplayDifference:
    return ReplayDifference(
        subject_kind=ReplaySubjectKind.HARNESS,
        stable_key="harness",
        recorded="claude-code",
        current="claude-code" if change is ReplayChange.UNCHANGED else "codex",
        change=change,
    )


def test_severity_follows_the_refusal_set() -> None:
    for code in ReplayLimitationCode:
        expected = ReplaySeverity.REFUSAL if code in REFUSAL_CODES else ReplaySeverity.LIMITATION
        assert limitation(code).severity is expected
    assert ReplayLimitationCode.SOURCE_WORKTREE_DIRTY not in REFUSAL_CODES
    assert ReplayLimitationCode.SNAPSHOT_MISSING in REFUSAL_CODES


def test_verdict_is_derived_from_limitations() -> None:
    assert verdict_for([]) is ReplayVerdict.READY
    assert verdict_for([limitation(ReplayLimitationCode.GIT_STATE_NOT_PINNED)]) is (
        ReplayVerdict.LIMITED
    )
    assert (
        verdict_for(
            [
                limitation(ReplayLimitationCode.GIT_STATE_NOT_PINNED),
                limitation(ReplayLimitationCode.ALREADY_RETRIED),
            ]
        )
        is ReplayVerdict.REFUSED
    )


def test_digest_is_stable_and_sensitive_to_sources() -> None:
    launch_id = uuid.uuid4()
    args = {
        "source_launch_id": launch_id,
        "snapshot_content_hash": "sha256:" + "a" * 64,
        "verdict": ReplayVerdict.LIMITED,
        "differences": [_diff(ReplayChange.UNCHANGED)],
        "limitations": [limitation(ReplayLimitationCode.OUTPUT_NOT_REPRODUCIBLE)],
    }
    first = preview_digest(**args)  # type: ignore[arg-type]
    assert first == preview_digest(**args)  # type: ignore[arg-type]
    assert first.startswith("sha256:")
    changed = {**args, "differences": [_diff(ReplayChange.CHANGED)]}
    assert preview_digest(**changed) != first  # type: ignore[arg-type]


def test_substitutions_drop_unchanged_elements() -> None:
    kept = substitutions([_diff(ReplayChange.UNCHANGED), _diff(ReplayChange.CHANGED)])
    assert [item.change for item in kept] == [ReplayChange.CHANGED]


def test_retry_body_stays_optional_and_additive() -> None:
    assert TaskLaunchRetry().replay is None
    retry = TaskLaunchRetry.model_validate(
        {
            "replay": {
                "snapshot_content_hash": "sha256:" + "a" * 64,
                "preview_digest": "sha256:" + "b" * 64,
            }
        }
    )
    assert retry.replay is not None
