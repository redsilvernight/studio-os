"""DEC-0363: structured decision review in the completion evidence.

`studio.completion/v2` requires the `decisions` review (blocking issues);
`studio.completion/v1` stays gate-free (the missing review is a non-blocking
warning surfaced by the handoff caller, never a `check_completion` issue)."""

from __future__ import annotations

from studio_contracts.completion import CompletionEvidence, check_completion


def _evidence(kind: str = "audit", **extra: object) -> CompletionEvidence:
    return CompletionEvidence.model_validate(
        {
            "kind": kind,
            "artifacts": ["vault:report"],
            "checks": [{"name": "review", "kind": "review", "status": "passed"}],
            **extra,
        }
    )


def _review(outcome: str, **extra: object) -> dict[str, object]:
    return {"outcome": outcome, **extra}


def test_v2_new_decision_with_ids_is_ready() -> None:
    evidence = _evidence(
        format="studio.completion/v2",
        decisions=_review("new", decision_ids=["dec-001"]),
    )
    assert check_completion(evidence).ready


def test_v2_existing_decision_with_ids_is_ready() -> None:
    evidence = _evidence(
        format="studio.completion/v2",
        decisions=_review("existing", decision_ids=["dec-001", "dec-002"]),
    )
    assert check_completion(evidence).ready


def test_v2_motivated_absence_with_reason_is_ready() -> None:
    evidence = _evidence(
        format="studio.completion/v2",
        decisions=_review("none", reason="Exploratory probe, no project decision involved."),
    )
    assert check_completion(evidence).ready


def test_v2_missing_review_is_blocking() -> None:
    report = check_completion(_evidence(format="studio.completion/v2"))
    assert not report.ready
    assert report.issues == ["decision_review_missing"]


def test_v2_motivated_absence_without_reason_is_blocking() -> None:
    for reason in (None, "", "   "):
        report = check_completion(
            _evidence(format="studio.completion/v2", decisions=_review("none", reason=reason))
        )
        assert not report.ready
        assert report.issues == ["decision_reason_missing"]


def test_v2_new_or_existing_without_ids_is_blocking() -> None:
    for outcome in ("new", "existing"):
        report = check_completion(
            _evidence(format="studio.completion/v2", decisions=_review(outcome))
        )
        assert not report.ready
        assert report.issues == ["decision_ids_missing"]


def test_v1_without_review_has_no_gate() -> None:
    report = check_completion(_evidence())
    assert report.ready
    assert report.issues == []


def test_v1_with_review_is_accepted_without_gate() -> None:
    evidence = _evidence(decisions=_review("existing", decision_ids=["dec-001"]))
    assert check_completion(evidence).ready
    assert check_completion(_evidence(decisions=_review("none"))).ready
