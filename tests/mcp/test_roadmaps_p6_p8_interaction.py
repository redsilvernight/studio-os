"""Roadmaps P6 x P8: `studio_prepare_context` only ever reflects the approved
roadmap. A pending, superseded, rejected, change-requested or stale proposal never
becomes the active content; an approval shows up on the next call. Real MCP tool,
real Roadmap services, real Postgres (same fixtures as the P6 context tests)."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.project import ProjectModel
from studio_api.services import roadmaps
from studio_api.services.authz import Principal
from studio_contracts.auth import Role
from studio_contracts.roadmaps import (
    ProposalCreate,
    ProposalReview,
    ReviewDecision,
    RevisionStatus,
    Roadmap,
    RoadmapDocument,
    RoadmapStatus,
)

from tests.mcp.conftest import FakeContext
from tests.mcp.test_prepare_context import Machine, _principal, _project
from tests.mcp.test_prepare_context_roadmap import (
    _all_strings,
    _doc,
    _import,
    _prepare,
    _step,
)

APPROVED_STEP = "Baseline step"
PROPOSED_STEP = "Proposed step"


def _document(step_title: str, *, title: str = "Plan") -> dict[str, Any]:
    return _doc(("P", [_step("a", title=step_title)]), title=title)


async def _active(
    db_session: AsyncSession, machine: Machine, project: ProjectModel
) -> tuple[Principal, Roadmap]:
    principal = await _principal(db_session, machine)
    roadmap = await _import(
        db_session, principal, project, _document(APPROVED_STEP), to=RoadmapStatus.ACTIVE
    )
    return principal, roadmap


async def _propose(
    db_session: AsyncSession,
    principal: Principal,
    roadmap: Roadmap,
    step_title: str,
    *,
    base_revision_no: int | None = None,
) -> int:
    author = dataclasses.replace(principal, role=Role.AGENT)
    revision = await roadmaps.create_proposal(
        db_session,
        author,
        roadmap.id,
        ProposalCreate(
            base_revision_no=(
                roadmap.approved_revision_no if base_revision_no is None else base_revision_no
            ),
            document=RoadmapDocument.model_validate(_document(step_title)),
            summary="Rename the step",
        ),
    )
    return revision.revision_no


async def _review(
    db_session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    revision_no: int,
    decision: ReviewDecision,
    *,
    role: Role = Role.ADMIN,
    comment: str | None = "reviewed",
) -> Roadmap:
    current = await roadmaps.get_roadmap(db_session, roadmap_id)
    return await roadmaps.review_proposal(
        db_session,
        dataclasses.replace(principal, role=role),
        roadmap_id,
        revision_no,
        ProposalReview(decision=decision, expected_version=current.version, comment=comment),
    )


def _step_titles(payload: dict[str, Any]) -> set[str]:
    return {s for s in _all_strings(payload) if s in (APPROVED_STEP, PROPOSED_STEP)}


async def test_a_pending_proposal_never_becomes_the_active_context(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    project = await _project(db_session)
    principal, roadmap = await _active(db_session, machine, project)
    before = await _prepare(auth_ctx, project, "work on the plan")

    await _propose(db_session, principal, roadmap, PROPOSED_STEP)

    after = await _prepare(auth_ctx, project, "work on the plan")
    assert after == before
    assert _step_titles(after) == {APPROVED_STEP}
    assert after["roadmap"]["status"] == "active"
    assert "roadmap_overview" not in after and "unavailable" not in after


async def test_an_approved_proposal_is_reflected_on_the_next_call(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    project = await _project(db_session)
    principal, roadmap = await _active(db_session, machine, project)
    revision_no = await _propose(db_session, principal, roadmap, PROPOSED_STEP)
    assert _step_titles(await _prepare(auth_ctx, project, "work on the plan")) == {APPROVED_STEP}

    approved = await _review(
        db_session, principal, roadmap.id, revision_no, ReviewDecision.APPROVE, comment=None
    )

    payload = await _prepare(auth_ctx, project, "work on the plan")
    assert approved.approved_revision_no == revision_no
    assert _step_titles(payload) == {PROPOSED_STEP}
    assert payload["roadmap"]["roadmap_id"] == str(roadmap.id)
    assert payload["roadmap"]["current_step"]["key"] == "a"
    assert payload["roadmap"]["status"] == "active"


@pytest.mark.parametrize("decision", [ReviewDecision.REJECT, ReviewDecision.REQUEST_CHANGES])
async def test_a_rejected_or_change_requested_proposal_does_not_touch_the_context(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext, decision: ReviewDecision
) -> None:
    project = await _project(db_session)
    principal, roadmap = await _active(db_session, machine, project)
    before = await _prepare(auth_ctx, project, "work on the plan")
    revision_no = await _propose(db_session, principal, roadmap, PROPOSED_STEP)

    await _review(db_session, principal, roadmap.id, revision_no, decision, comment="not now")

    assert await _prepare(auth_ctx, project, "work on the plan") == before


async def test_a_superseded_proposal_does_not_touch_the_context(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    project = await _project(db_session)
    principal, roadmap = await _active(db_session, machine, project)
    before = await _prepare(auth_ctx, project, "work on the plan")
    first = await _propose(db_session, principal, roadmap, "First attempt")
    await _propose(db_session, principal, roadmap, "Second attempt")

    revisions = await roadmaps.list_revisions(db_session, roadmap.id)
    statuses = {r.revision_no: r.status for r in revisions if r.kind.value == "proposal"}
    assert statuses[first] is RevisionStatus.SUPERSEDED
    assert await _prepare(auth_ctx, project, "work on the plan") == before


async def test_a_stale_proposal_is_refused_and_the_context_keeps_the_approved_content(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    project = await _project(db_session)
    principal, roadmap = await _active(db_session, machine, project)
    base = roadmap.approved_revision_no
    winner = await _propose(db_session, principal, roadmap, PROPOSED_STEP)
    await _review(db_session, principal, roadmap.id, winner, ReviewDecision.APPROVE, comment=None)
    approved_view = await _prepare(auth_ctx, project, "work on the plan")
    stale = await _propose(db_session, principal, roadmap, "Stale idea", base_revision_no=base)

    with pytest.raises(HTTPException) as refused:
        await _review(
            db_session, principal, roadmap.id, stale, ReviewDecision.APPROVE, comment=None
        )

    assert refused.value.status_code == 409
    assert await _prepare(auth_ctx, project, "work on the plan") == approved_view
    assert _step_titles(approved_view) == {PROPOSED_STEP}


async def test_an_agent_cannot_approve_its_own_proposal(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    project = await _project(db_session)
    principal, roadmap = await _active(db_session, machine, project)
    before = await _prepare(auth_ctx, project, "work on the plan")
    revision_no = await _propose(db_session, principal, roadmap, PROPOSED_STEP)

    for role in (Role.AGENT, Role.READONLY):
        with pytest.raises(HTTPException) as refused:
            await _review(
                db_session,
                principal,
                roadmap.id,
                revision_no,
                ReviewDecision.APPROVE,
                role=role,
                comment=None,
            )
        assert refused.value.status_code == 403

    assert await _prepare(auth_ctx, project, "work on the plan") == before


def test_a_comment_is_required_unless_the_decision_is_an_approval() -> None:
    for decision in (ReviewDecision.REJECT, ReviewDecision.REQUEST_CHANGES):
        with pytest.raises(ValidationError):
            ProposalReview(decision=decision, expected_version=1, comment="  ")
    ProposalReview(decision=ReviewDecision.APPROVE, expected_version=1)
