from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from studio_contracts.common import ContractModel

WorkKind = Literal["code", "audit", "diagnostic", "operation"]


class CompletionCheck(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["command", "review", "observation", "ci"] = "command"
    purpose: Literal["validation", "finding"] = "validation"
    status: Literal["passed", "failed", "not_run", "environment_unavailable"]
    exit_code: int | None = Field(default=None, strict=True)
    reference: str | None = Field(default=None, max_length=1000)


DecisionOutcome = Literal["new", "existing", "none"]

CompletionFormat = Literal["studio.completion/v1", "studio.completion/v2"]


class DecisionReview(ContractModel):
    """Structured review of the project decisions at handoff
    (additive): which decisions this work produced (`new`), reused
    (`existing`), or why none was needed (`none`). `decision_ids` names
    internal UUIDs or `DEC-NNNN` readable ids (<=20); the server resolves
    each one and rejects unknown, foreign or invisible ids with
    `422 decision_reference_invalid`. A `proposed` decision is a valid
    reference and is never auto-accepted by the handoff. `reason` is
    required (non-empty) when `outcome` is `none` — enforced for v2 by
    `check_completion` (`decision_reason_missing`)."""

    outcome: DecisionOutcome
    decision_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=20
    )
    reason: str | None = Field(default=None, max_length=2000)


class CompletionEvidence(ContractModel):
    format: CompletionFormat = "studio.completion/v1"
    kind: WorkKind
    artifacts: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        default_factory=list, max_length=10
    )
    checks: list[CompletionCheck] = Field(default_factory=list, max_length=20)
    versioned: bool = False
    revision: str | None = Field(default=None, max_length=200)
    target_branch: str | None = Field(default=None, max_length=200)
    integration_required: bool = False
    integrated: bool = False
    ci_required: bool = False
    ci_verified: bool = False
    effect_verified: bool = False
    deployed: bool = False
    decisions: DecisionReview | None = None


class CompletionReport(ContractModel):
    format: Literal["studio.completion-report/v1"] = "studio.completion-report/v1"
    authoritative: Literal[False] = False
    ready: bool
    issues: list[str] = Field(max_length=30)


def check_completion(evidence: CompletionEvidence) -> CompletionReport:
    issues: list[str] = []
    if not evidence.artifacts or any(
        not ref.strip() or len(ref) > 1000 for ref in evidence.artifacts
    ):
        issues.append("artifact_missing_or_invalid")
    validations = [check for check in evidence.checks if check.purpose == "validation"]
    if not validations:
        issues.append("validation_missing")
    for index, check in enumerate(evidence.checks):
        if check.purpose == "finding":
            if check.status == "not_run":
                issues.append(f"finding_not_observed:{index}")
            elif check.kind == "command" and check.exit_code is None:
                issues.append(f"command_exit_missing:{index}")
            elif check.status == "passed" and check.exit_code not in (None, 0):
                issues.append(f"finding_inconsistent:{index}")
            continue
        if check.status != "passed" or check.exit_code not in (None, 0):
            issues.append(f"validation_not_passed:{index}")
        elif check.kind == "command" and check.exit_code != 0:
            issues.append(f"command_exit_missing:{index}")
        elif check.kind == "ci" and not (check.reference or "").strip():
            issues.append(f"ci_reference_missing:{index}")
    if evidence.kind == "code" and (
        not evidence.versioned or not (evidence.revision or "").strip()
    ):
        issues.append("versioned_revision_required")
    if evidence.integration_required and (
        not evidence.integrated or not (evidence.target_branch or "").strip()
    ):
        issues.append("integration_required")
    if evidence.ci_required and (
        not evidence.ci_verified or not any(check.kind == "ci" for check in validations)
    ):
        issues.append("ci_required")
    if evidence.kind == "operation" and not evidence.effect_verified:
        issues.append("effect_not_verified")
    if evidence.format == "studio.completion/v2":
        review = evidence.decisions
        if review is None:
            issues.append("decision_review_missing")
        elif review.outcome == "none":
            if not (review.reason or "").strip():
                issues.append("decision_reason_missing")
        elif not review.decision_ids:
            issues.append("decision_ids_missing")
    # v1 carries no decision gate: a missing review is a non-blocking
    # `decision_review_missing` warning returned by the handoff caller, so
    # historical callers and non-terminal closures keep working unchanged.
    return CompletionReport(ready=not issues, issues=issues)
