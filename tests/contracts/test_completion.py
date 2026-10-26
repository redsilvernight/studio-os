from __future__ import annotations

import pytest
from pydantic import ValidationError
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


@pytest.mark.parametrize("kind", ["audit", "diagnostic"])
def test_verified_non_code_deliverable_does_not_require_git_or_ci(kind: str) -> None:
    report = check_completion(_evidence(kind))
    assert report.ready
    assert report.authoritative is False


@pytest.mark.parametrize(
    "check",
    [
        {"name": "pytest", "status": "passed", "exit_code": 1},
        {"name": "pytest", "status": "passed"},
        {"name": "pytest", "status": "not_run"},
        {"name": "postgres", "status": "environment_unavailable", "exit_code": 2},
    ],
)
def test_failed_missing_or_unexecuted_command_cannot_validate_completion(
    check: dict[str, object],
) -> None:
    assert not check_completion(_evidence(checks=[check])).ready


def test_code_requires_revision_and_declared_repository_gates_without_fixed_branch() -> None:
    assert not check_completion(_evidence("code")).ready
    pending = _evidence("code", versioned=True, revision="abc123", integration_required=True)
    assert check_completion(pending).issues == ["integration_required"]
    complete = pending.model_copy(update={"integrated": True, "target_branch": "release/candidate"})
    assert check_completion(complete).ready


def test_operational_completion_requires_observed_effect_without_implying_deployment() -> None:
    assert not check_completion(_evidence("operation")).ready
    complete = _evidence("operation", effect_verified=True)
    assert check_completion(complete).ready
    assert not complete.deployed


def test_diagnosed_environment_failure_is_a_finding_and_needs_separate_validation() -> None:
    finding = {
        "name": "database probe",
        "status": "environment_unavailable",
        "exit_code": 2,
        "purpose": "finding",
    }
    assert not check_completion(_evidence("diagnostic", checks=[finding])).ready
    evidence = _evidence(
        "diagnostic",
        checks=[finding, {"name": "report review", "kind": "review", "status": "passed"}],
    )
    assert check_completion(evidence).ready


def test_boolean_is_not_a_real_command_exit_code() -> None:
    with pytest.raises(ValidationError):
        _evidence(checks=[{"name": "pytest", "status": "passed", "exit_code": False}])


def test_ci_requirement_needs_a_check_with_its_reference() -> None:
    assert not check_completion(_evidence(ci_required=True, ci_verified=True)).ready
    evidence = _evidence(
        ci_required=True,
        ci_verified=True,
        checks=[
            {
                "name": "CI",
                "kind": "ci",
                "status": "passed",
                "reference": "https://example.test/run/1",
            }
        ],
    )
    assert check_completion(evidence).ready
