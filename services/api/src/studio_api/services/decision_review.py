"""Decision-review helpers (DEC-0363): validate the `decisions` review carried
by a completion evidence, and re-surface missing reviews when a roadmap step
closes.

The review is persisted inside the existing `COMPLETION_EVIDENCE` JSON blob of
the AI work summary — no SQL migration. Referencing a `proposed` decision is
valid and never transitions it: the handoff accepts the reference, it does not
accept the decision. Every unresolvable reference (unknown id, another
project's decision, invisible decision) answers the same
`422 decision_reference_invalid` so the error reveals nothing about decisions
outside the caller's scope."""

from __future__ import annotations

import json
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.decision import DecisionModel
from studio_api.services import ai_work as ai_work_service
from studio_api.services.authz import Principal

EVIDENCE_MARKER = "COMPLETION_EVIDENCE "

DECISION_REVIEW_MISSING = "decision_review_missing"


def extract_evidence_decisions(summary: str | None) -> dict[str, object] | None:
    """The parsed `decisions` review of a handoff AI work summary, or `None`
    when the summary carries no completion evidence with a review. Never
    raises: a warning path must stay fail-open."""
    if not summary or EVIDENCE_MARKER not in summary:
        return None
    try:
        payload = json.loads(summary.split(EVIDENCE_MARKER, 1)[1])
    except (ValueError, IndexError):
        return None
    if not isinstance(payload, dict):
        return None
    decisions = payload.get("decisions")
    return decisions if isinstance(decisions, dict) else None


async def _resolve_decision(session: AsyncSession, ref: str) -> DecisionModel | None:
    """Resolve a decision reference: internal UUID first, then `DEC-NNNN`
    readable id. Returns `None` when unresolvable — the caller maps every
    miss to the same `decision_reference_invalid` error."""
    try:
        candidate = await session.get(DecisionModel, uuid.UUID(ref))
    except ValueError:
        candidate = None
    if candidate is not None:
        return candidate
    result = await session.execute(select(DecisionModel).where(DecisionModel.readable_id == ref))
    return result.scalars().first()


def decision_reference_invalid() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "error_code": "decision_reference_invalid",
            "message": "each decision reference must exist, belong to the project and be visible",
        },
    )


async def validate_decision_refs(
    session: AsyncSession,
    project_id: uuid.UUID,
    refs: list[str],
) -> None:
    """Every referenced decision must exist and belong to the handoff project
    (global, project-less decisions are not project evidence). A `proposed`
    decision is accepted as a reference without any status transition. Any
    miss raises the same `422 decision_reference_invalid`."""
    for ref in refs:
        decision = await _resolve_decision(session, ref)
        if decision is None or decision.project_id != project_id:
            raise decision_reference_invalid()


async def tasks_missing_decision_review(
    session: AsyncSession,
    principal: Principal,
    task_ids: list[uuid.UUID],
    *,
    limit: int = 20,
) -> list[str]:
    """Task ids (as `decision_review_missing:<task_id>` warnings) whose AI work
    carries no completion evidence with a `decisions` review. Read-only and
    fail-open: unreadable tasks are skipped, never a gate."""
    missing: list[str] = []
    for task_id in task_ids[: max(1, limit)]:
        try:
            entries = await ai_work_service.list_ai_work(session, principal, task_id=task_id)
        except HTTPException:
            continue
        if not any(extract_evidence_decisions(entry.summary) is not None for entry in entries):
            missing.append(f"{DECISION_REVIEW_MISSING}:{task_id}")
    return missing
