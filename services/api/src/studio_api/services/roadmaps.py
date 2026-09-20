"""Roadmap domain service (Roadmaps P2, DEC-0084/DEC-0085): creation, import,
read, header edits, lifecycle transitions and export.

The rules (transition table, authority, write matrix, validation) are the pure
ones of `studio_contracts.roadmaps`; this module only persists them. Routers
never touch the database: they call these functions. Structural edits live in
`roadmap_structure`, hydration in `roadmap_hydration`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.events import EventType
from studio_contracts.roadmaps import (
    HydrationApplyRequest,
    HydrationRequest,
    HydrationResult,
    LinkTask,
    ProposalCreate,
    ProposalReview,
    ReviewDecision,
    RevisionKind,
    RevisionStatus,
    Roadmap,
    RoadmapCreate,
    RoadmapDiff,
    RoadmapDocument,
    RoadmapErrorCode,
    RoadmapImport,
    RoadmapRevision,
    RoadmapRevisionSummary,
    RoadmapStatus,
    RoadmapSummary,
    RoadmapTransition,
    RoadmapUpdate,
    StepProgressUpdate,
    TransitionRequest,
    WriteKind,
    WriteProvenance,
    roadmap_document_errors,
    transition_requires_provision,
    transition_target,
)

from studio_api.db.models.project import ProjectModel
from studio_api.db.models.roadmap import (
    RoadmapModel,
    RoadmapPhaseModel,
    RoadmapRevisionModel,
    RoadmapStepDependencyModel,
    RoadmapStepModel,
)
from studio_api.services import roadmap_hydration as hydration_service
from studio_api.services.authz import Principal, ensure_can_provision, ensure_can_write
from studio_api.services.roadmap_support import (
    PendingEvent,
    ResolvedProvenance,
    add_revision,
    build_document,
    build_summary,
    check_version,
    compute_diff,
    content_changed,
    finish,
    finish_result,
    guard_write,
    invalid_roadmap,
    invalid_state,
    load_tree,
    lock_roadmap,
    next_revision_no,
    not_found,
    read_roadmap,
    reconcile_document,
    record_snapshot,
    reference_not_found,
    resolve_provenance,
    revision_summary_view,
    revision_view,
    roadmap_error,
    text_or_none,
)


async def _require_project(session: AsyncSession, project_id: uuid.UUID) -> ProjectModel:
    project = await session.get(ProjectModel, project_id)
    if project is None:
        raise reference_not_found("project")
    return project


# --- reads ---
async def list_roadmaps(
    session: AsyncSession,
    project_id: uuid.UUID,
    roadmap_status: RoadmapStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[RoadmapSummary]:
    if await session.get(ProjectModel, project_id) is None:
        raise not_found("project")
    stmt = (
        select(RoadmapModel)
        .where(RoadmapModel.project_id == project_id)
        .order_by(RoadmapModel.created_at.desc(), RoadmapModel.id)
        .limit(limit)
        .offset(offset)
    )
    if roadmap_status is not None:
        stmt = stmt.where(RoadmapModel.status == roadmap_status.value)
    rows = (await session.execute(stmt)).scalars().all()
    return [build_summary(await load_tree(session, row)) for row in rows]


async def get_roadmap(session: AsyncSession, roadmap_id: uuid.UUID) -> Roadmap:
    roadmap = await session.get(RoadmapModel, roadmap_id)
    if roadmap is None:
        raise not_found()
    return await read_roadmap(session, roadmap)


async def export_roadmap(session: AsyncSession, roadmap_id: uuid.UUID) -> RoadmapDocument:
    """Neutral `studio.roadmap/v1` document of the current state. Stamps are
    informative only; the document carries no id, status or provenance."""
    roadmap = await session.get(RoadmapModel, roadmap_id)
    if roadmap is None:
        raise not_found()
    document = build_document(await load_tree(session, roadmap))
    return document.model_copy(
        update={"exported_at": datetime.now(UTC), "revision_no": roadmap.revision_no}
    )


# --- creation ---
def _new_roadmap(
    project_id: uuid.UUID,
    prov: ResolvedProvenance,
    *,
    title: str,
    objective: str | None,
    context: str | None,
    metadata: dict[str, object],
) -> RoadmapModel:
    return RoadmapModel(
        project_id=project_id,
        title=title,
        objective=text_or_none(objective),
        context=text_or_none(context),
        roadmap_metadata=dict(metadata),
        **prov.columns(),
    )


def _created_event(roadmap: RoadmapModel) -> PendingEvent:
    return PendingEvent(
        EventType.ROADMAP_CREATED,
        {
            "roadmap_id": str(roadmap.id),
            "revision_no": roadmap.revision_no,
            "status": roadmap.status,
        },
    )


async def create_roadmap(
    session: AsyncSession, principal: Principal, payload: RoadmapCreate
) -> Roadmap:
    ensure_can_write(principal, "roadmap")
    prov = await resolve_provenance(session, principal, payload.provenance)
    await _require_project(session, payload.project_id)
    roadmap = _new_roadmap(
        payload.project_id,
        prov,
        title=payload.title,
        objective=payload.objective,
        context=payload.context,
        metadata=dict(payload.metadata),
    )
    session.add(roadmap)
    await session.flush()
    return await finish(session, principal, roadmap, prov, [_created_event(roadmap)])


async def insert_document(
    session: AsyncSession,
    roadmap: RoadmapModel,
    document: RoadmapDocument,
    prov: ResolvedProvenance,
) -> None:
    """Persist a validated document's phases, steps, dependencies and task
    plans under `roadmap`. Never creates a Task nor a link."""
    steps_by_key: dict[str, RoadmapStepModel] = {}
    for phase_position, phase_in in enumerate(document.phases):
        phase = RoadmapPhaseModel(
            roadmap_id=roadmap.id,
            key=phase_in.key,
            position=phase_position,
            title=phase_in.title,
            objective=text_or_none(phase_in.objective),
            **prov.columns(),
        )
        session.add(phase)
        await session.flush()
        for step_position, step_in in enumerate(phase_in.steps):
            step = RoadmapStepModel(
                roadmap_id=roadmap.id,
                phase_id=phase.id,
                key=step_in.key,
                position=step_position,
                title=step_in.title,
                objective=text_or_none(step_in.objective),
                context=text_or_none(step_in.context),
                instructions=text_or_none(step_in.instructions),
                acceptance_criteria=list(step_in.acceptance_criteria),
                criteria_checked=[],
                notes=text_or_none(step_in.notes),
                step_metadata=dict(step_in.metadata),
                task_plan=[item.model_dump(mode="json") for item in step_in.tasks],
                **prov.columns(),
            )
            session.add(step)
            steps_by_key[step_in.key] = step
    await session.flush()
    for phase_in in document.phases:
        for step_in in phase_in.steps:
            for dependency in step_in.depends_on:
                session.add(
                    RoadmapStepDependencyModel(
                        step_id=steps_by_key[step_in.key].id,
                        depends_on_step_id=steps_by_key[dependency].id,
                        roadmap_id=roadmap.id,
                    )
                )
    await session.flush()


async def import_roadmap(
    session: AsyncSession, principal: Principal, payload: RoadmapImport
) -> Roadmap:
    """Create a `draft` (or a `proposed` roadmap with `submit`) from a neutral
    document, atomically. The document is validated before any write."""
    ensure_can_write(principal, "roadmap")
    prov = await resolve_provenance(session, principal, payload.provenance)
    errors = roadmap_document_errors(payload.document)
    if errors:
        raise invalid_roadmap(errors[0]["reason"], errors[0]["field"])
    await _require_project(session, payload.project_id)
    document = payload.document
    roadmap = _new_roadmap(
        payload.project_id,
        prov,
        title=document.title,
        objective=document.objective,
        context=document.context,
        metadata=dict(document.metadata),
    )
    session.add(roadmap)
    await session.flush()
    await insert_document(session, roadmap, document, prov)
    pending = [_created_event(roadmap)]
    if payload.submit:
        pending.append(await _submit(session, roadmap, prov))
    return await finish(session, principal, roadmap, prov, pending)


# --- header edit ---
async def update_roadmap(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    payload: RoadmapUpdate,
    expected_version: int,
) -> Roadmap:
    roadmap = await lock_roadmap(session, roadmap_id)
    guard_write(principal, roadmap, WriteKind.CONTENT, payload.provenance)
    prov = await resolve_provenance(session, principal, payload.provenance)
    check_version(roadmap.version, expected_version)
    if payload.title is not None:
        roadmap.title = payload.title
    if payload.objective is not None:
        roadmap.objective = text_or_none(payload.objective)
    if payload.context is not None:
        roadmap.context = text_or_none(payload.context)
    if payload.metadata is not None:
        roadmap.roadmap_metadata = dict(payload.metadata)
    event = await content_changed(session, roadmap, prov, "roadmap")
    return await finish(session, principal, roadmap, prov, [event])


# --- lifecycle ---
async def _submit(
    session: AsyncSession, roadmap: RoadmapModel, prov: ResolvedProvenance
) -> PendingEvent:
    """`draft -> proposed`: the content is frozen as a `proposal` revision."""
    revision_no = await next_revision_no(session, roadmap)
    roadmap.revision_no = revision_no
    document = build_document(await load_tree(session, roadmap))
    add_revision(
        session,
        roadmap,
        prov,
        kind="proposal",
        revision_no=revision_no,
        document=document,
        status_value="pending",
        base_revision_no=roadmap.approved_revision_no,
    )
    roadmap.status = RoadmapStatus.PROPOSED.value
    return PendingEvent(
        EventType.ROADMAP_PROPOSED,
        {
            "roadmap_id": str(roadmap.id),
            "revision_no": roadmap.revision_no,
            "status": roadmap.status,
            "transition": RoadmapTransition.SUBMIT.value,
        },
    )


async def _pending_proposal(
    session: AsyncSession, roadmap: RoadmapModel
) -> RoadmapRevisionModel | None:
    result = await session.execute(
        select(RoadmapRevisionModel)
        .where(
            RoadmapRevisionModel.roadmap_id == roadmap.id,
            RoadmapRevisionModel.kind == "proposal",
            RoadmapRevisionModel.status == "pending",
        )
        .order_by(RoadmapRevisionModel.revision_no.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _ensure_no_other_active(session: AsyncSession, roadmap: RoadmapModel) -> None:
    other = await session.execute(
        select(RoadmapModel.id).where(
            RoadmapModel.project_id == roadmap.project_id,
            RoadmapModel.status == RoadmapStatus.ACTIVE.value,
            RoadmapModel.id != roadmap.id,
        )
    )
    if other.first() is not None:
        raise roadmap_error(
            status.HTTP_409_CONFLICT,
            RoadmapErrorCode.ACTIVE_ROADMAP_EXISTS,
            message="the project already has an active roadmap",
        )


_TRANSITION_EVENTS: dict[RoadmapTransition, EventType] = {
    RoadmapTransition.APPROVE: EventType.ROADMAP_APPROVED,
    RoadmapTransition.REQUEST_CHANGES: EventType.ROADMAP_CHANGES_REQUESTED,
    RoadmapTransition.REJECT: EventType.ROADMAP_REJECTED,
    RoadmapTransition.ACTIVATE: EventType.ROADMAP_ACTIVATED,
    RoadmapTransition.REOPEN: EventType.ROADMAP_ACTIVATED,
    RoadmapTransition.COMPLETE: EventType.ROADMAP_COMPLETED,
    RoadmapTransition.ARCHIVE: EventType.ROADMAP_ARCHIVED,
}


async def _flush_status(session: AsyncSession) -> None:
    """Flush a status change now so the partial unique index (one `active`
    roadmap per project) is what arbitrates a concurrent activation of two
    sibling roadmaps: the loser gets `409 active_roadmap_exists`."""
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise roadmap_error(
            status.HTTP_409_CONFLICT,
            RoadmapErrorCode.ACTIVE_ROADMAP_EXISTS,
            message="the project already has an active roadmap",
        ) from error


async def transition_roadmap(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    payload: TransitionRequest,
) -> Roadmap:
    """Closed lifecycle (`ROADMAP_TRANSITIONS`); authority per
    `transition_requires_provision` (only `admin`/`developer` activate,
    approve, reject, complete, reopen or archive an approved plan). Activating
    an already `active` roadmap is a successful no-op."""
    roadmap = await lock_roadmap(session, roadmap_id)
    ensure_can_write(principal, "roadmap")
    current = RoadmapStatus(roadmap.status)
    transition = payload.transition
    if transition_requires_provision(current, transition):
        ensure_can_provision(principal, "roadmap")
    prov = await resolve_provenance(session, principal, payload.provenance)
    if current is RoadmapStatus.ACTIVE and transition is RoadmapTransition.ACTIVATE:
        return await read_roadmap(session, roadmap)
    check_version(roadmap.version, payload.expected_version)
    target = transition_target(current, transition)
    if target is None:
        raise invalid_state(
            current, f"transition {transition.value} is not allowed", transition=transition
        )

    pending: list[PendingEvent] = []
    if target is RoadmapStatus.ACTIVE:
        await _ensure_no_other_active(session, roadmap)

    roadmap.version += 1
    if transition is RoadmapTransition.SUBMIT:
        pending.append(await _submit(session, roadmap, prov))
    else:
        proposal: RoadmapRevisionModel | None = None
        if current is RoadmapStatus.PROPOSED:
            proposal = await _pending_proposal(session, roadmap)
        roadmap.status = target.value
        await _flush_status(session)
        if proposal is not None:
            proposal.status = {
                RoadmapTransition.APPROVE: "approved",
                RoadmapTransition.REQUEST_CHANGES: "changes_requested",
                RoadmapTransition.REJECT: "rejected",
            }[transition]
            proposal.reviewed_by_user_id = principal.user.id
            proposal.reviewed_at = datetime.now(UTC)
            proposal.review_comment = payload.comment
            if transition is RoadmapTransition.APPROVE:
                roadmap.approved_revision_no = proposal.revision_no
        elif transition in (RoadmapTransition.ACTIVATE, RoadmapTransition.APPROVE):
            await record_snapshot(session, roadmap, prov)
        payload_body: dict[str, object] = {
            "roadmap_id": str(roadmap.id),
            "revision_no": roadmap.revision_no,
            "status": roadmap.status,
            "transition": transition.value,
        }
        if transition in (
            RoadmapTransition.APPROVE,
            RoadmapTransition.REQUEST_CHANGES,
            RoadmapTransition.REJECT,
        ):
            payload_body["scope"] = "roadmap"
        if payload.comment:
            payload_body["comment"] = payload.comment
        pending.append(PendingEvent(_TRANSITION_EVENTS[transition], payload_body))
        if transition is RoadmapTransition.APPROVE:
            pending.append(
                PendingEvent(
                    EventType.ROADMAP_ACTIVATED,
                    {**payload_body, "transition": RoadmapTransition.APPROVE.value},
                )
            )
    return await finish(session, principal, roadmap, prov, pending)


# --- revisions and proposals (Roadmaps P8, DEC-0084 §6/DEC-0085) ---------------
async def _revision_row(
    session: AsyncSession, roadmap_id: uuid.UUID, revision_no: int
) -> RoadmapRevisionModel | None:
    result = await session.execute(
        select(RoadmapRevisionModel)
        .where(
            RoadmapRevisionModel.roadmap_id == roadmap_id,
            RoadmapRevisionModel.revision_no == revision_no,
        )
        .order_by(RoadmapRevisionModel.kind)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _proposal_row(
    session: AsyncSession, roadmap_id: uuid.UUID, revision_no: int
) -> RoadmapRevisionModel | None:
    result = await session.execute(
        select(RoadmapRevisionModel).where(
            RoadmapRevisionModel.roadmap_id == roadmap_id,
            RoadmapRevisionModel.revision_no == revision_no,
            RoadmapRevisionModel.kind == RevisionKind.PROPOSAL.value,
        )
    )
    return result.scalar_one_or_none()


def _revision_provenance(revision: RoadmapRevisionModel) -> ResolvedProvenance:
    return ResolvedProvenance(
        revision.origin,
        revision.actor_type,
        revision.actor_id,
        revision.agent_id,
        revision.machine_id,
    )


async def list_revisions(
    session: AsyncSession,
    roadmap_id: uuid.UUID,
    kind: RevisionKind | None = None,
    revision_status: RevisionStatus | None = None,
) -> list[RoadmapRevisionSummary]:
    """Revision history, newest first; content is omitted (see `get_revision`)."""
    if await session.get(RoadmapModel, roadmap_id) is None:
        raise not_found()
    stmt = (
        select(RoadmapRevisionModel)
        .where(RoadmapRevisionModel.roadmap_id == roadmap_id)
        .order_by(RoadmapRevisionModel.revision_no.desc())
    )
    if kind is not None:
        stmt = stmt.where(RoadmapRevisionModel.kind == kind.value)
    if revision_status is not None:
        stmt = stmt.where(RoadmapRevisionModel.status == revision_status.value)
    rows = (await session.execute(stmt)).scalars().all()
    return [revision_summary_view(row) for row in rows]


async def get_revision(
    session: AsyncSession, roadmap_id: uuid.UUID, revision_no: int
) -> RoadmapRevision:
    if await session.get(RoadmapModel, roadmap_id) is None:
        raise not_found()
    row = await _revision_row(session, roadmap_id, revision_no)
    if row is None:
        raise reference_not_found("revision")
    return revision_view(row)


async def create_proposal(
    session: AsyncSession, principal: Principal, roadmap_id: uuid.UUID, payload: ProposalCreate
) -> RoadmapRevision:
    """Record a pending `proposal` revision against an `active` roadmap. The
    roadmap content is untouched (a proposal is not a mutation until approved);
    a previous pending proposal is superseded. Any writer may propose; only a
    reviewer may approve (see `review_proposal`)."""
    roadmap = await lock_roadmap(session, roadmap_id)
    guard_write(principal, roadmap, WriteKind.PROPOSAL, payload.provenance)
    prov = await resolve_provenance(session, principal, payload.provenance)
    errors = roadmap_document_errors(payload.document)
    if errors:
        raise invalid_roadmap(errors[0]["reason"], errors[0]["field"])
    pending = (
        (
            await session.execute(
                select(RoadmapRevisionModel).where(
                    RoadmapRevisionModel.roadmap_id == roadmap.id,
                    RoadmapRevisionModel.kind == RevisionKind.PROPOSAL.value,
                    RoadmapRevisionModel.status == RevisionStatus.PENDING.value,
                )
            )
        )
        .scalars()
        .all()
    )
    for previous in pending:
        previous.status = RevisionStatus.SUPERSEDED.value
    revision = add_revision(
        session,
        roadmap,
        prov,
        kind=RevisionKind.PROPOSAL.value,
        revision_no=await next_revision_no(session, roadmap),
        document=payload.document,
        status_value=RevisionStatus.PENDING.value,
        base_revision_no=payload.base_revision_no,
        summary=payload.summary,
    )
    event = PendingEvent(
        EventType.ROADMAP_PROPOSED,
        {
            "roadmap_id": str(roadmap.id),
            "revision_no": revision.revision_no,
            "base_revision_no": payload.base_revision_no,
            "status": roadmap.status,
            "scope": "revision",
        },
    )
    await finish_result(session, principal, roadmap, prov, [event])
    await session.refresh(revision)
    return revision_view(revision)


async def proposal_diff(
    session: AsyncSession, roadmap_id: uuid.UUID, revision_no: int
) -> RoadmapDiff:
    """Diff between the proposal's base revision and the proposal, by `key`
    (P8.3). Computed at read time; never stored."""
    if await session.get(RoadmapModel, roadmap_id) is None:
        raise not_found()
    revision = await _proposal_row(session, roadmap_id, revision_no)
    if revision is None:
        raise reference_not_found("revision")
    base_document: RoadmapDocument | None = None
    if revision.base_revision_no is not None:
        base_row = await _revision_row(session, roadmap_id, revision.base_revision_no)
        if base_row is not None and base_row.content is not None:
            base_document = RoadmapDocument.model_validate(base_row.content)
    return RoadmapDiff(
        base_revision_no=revision.base_revision_no,
        proposal_revision_no=revision.revision_no,
        entries=compute_diff(base_document, RoadmapDocument.model_validate(revision.content)),
    )


async def review_proposal(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    revision_no: int,
    payload: ProposalReview,
) -> Roadmap:
    """Approve / request changes / reject a pending proposal (`admin`/`developer`
    only). Approval applies the proposal atomically by matching steps on `key`;
    a base revision that moved meanwhile is `409 base_revision_stale` and the
    agent must re-propose (P8.6). The other decisions only record the review."""
    roadmap = await lock_roadmap(session, roadmap_id)
    ensure_can_write(principal, "roadmap")
    ensure_can_provision(principal, "roadmap")
    revision = await _proposal_row(session, roadmap_id, revision_no)
    if revision is None:
        raise reference_not_found("revision")
    current = RoadmapStatus(roadmap.status)
    if current is not RoadmapStatus.ACTIVE:
        raise invalid_state(current, "a proposal can only be reviewed while the roadmap is active")
    if revision.status != RevisionStatus.PENDING.value:
        raise invalid_state(current, f"proposal {revision_no} is {revision.status}, not pending")
    check_version(roadmap.version, payload.expected_version)
    prov = await resolve_provenance(session, principal, WriteProvenance())
    if payload.decision is ReviewDecision.APPROVE:
        if revision.base_revision_no != roadmap.approved_revision_no:
            raise roadmap_error(
                status.HTTP_409_CONFLICT,
                RoadmapErrorCode.BASE_REVISION_STALE,
                server_revision_no=roadmap.approved_revision_no,
            )
        tree = await load_tree(session, roadmap)
        await reconcile_document(
            session,
            tree,
            RoadmapDocument.model_validate(revision.content),
            _revision_provenance(revision),
        )
        roadmap.version += 1
        roadmap.revision_no = revision.revision_no
        roadmap.approved_revision_no = revision.revision_no
        revision.status = RevisionStatus.APPROVED.value
        event_type = EventType.ROADMAP_APPROVED
    elif payload.decision is ReviewDecision.REQUEST_CHANGES:
        revision.status = RevisionStatus.CHANGES_REQUESTED.value
        event_type = EventType.ROADMAP_CHANGES_REQUESTED
    else:
        revision.status = RevisionStatus.REJECTED.value
        event_type = EventType.ROADMAP_REJECTED
    revision.reviewed_by_user_id = principal.user.id
    revision.reviewed_at = datetime.now(UTC)
    revision.review_comment = payload.comment
    body: dict[str, object] = {
        "roadmap_id": str(roadmap.id),
        "revision_no": revision.revision_no,
        "base_revision_no": revision.base_revision_no,
        "status": roadmap.status,
        "scope": "revision",
    }
    if payload.comment:
        body["comment"] = payload.comment
    return await finish(session, principal, roadmap, prov, [PendingEvent(event_type, body)])


# --- RoadmapServicePort adapters (Roadmaps P4/P5, DEC-0087) -------------------
# The MCP surface and project initialization call the domain through the typed
# port `studio_api.services.roadmap_port`. Hydration and step linking live in
# their own modules; these module-level functions expose them here with the
# port's names. No business logic: pure delegation to the canonical services.


async def preview_hydration(
    session: AsyncSession, roadmap_id: uuid.UUID, payload: HydrationRequest
) -> HydrationResult:
    """Read-only hydration preview; see `roadmap_hydration.preview_hydration`."""
    return await hydration_service.preview_hydration(session, roadmap_id, payload)


async def apply_hydration(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    payload: HydrationApplyRequest,
) -> HydrationResult:
    """Idempotent hydration apply; see `roadmap_hydration.apply_hydration`."""
    return await hydration_service.apply_hydration(session, principal, roadmap_id, payload)


async def link_task_by_step_key(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    step_key: str,
    task_id: uuid.UUID,
) -> None:
    """Link one Task to a step by key; re-linking is a no-op in `link_task`."""
    from studio_api.services import roadmap_structure as structure_service

    await structure_service.link_task(
        session, principal, roadmap_id, step_key, LinkTask(task_id=task_id)
    )


async def submit_roadmap(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    provenance: WriteProvenance,
) -> None:
    """`draft -> proposed` through the canonical `submit` transition; any other
    status is left untouched (a replay never re-submits or reopens a roadmap)."""
    current = await get_roadmap(session, roadmap_id)
    if current.status is not RoadmapStatus.DRAFT:
        return
    await transition_roadmap(
        session,
        principal,
        roadmap_id,
        TransitionRequest(
            transition=RoadmapTransition.SUBMIT,
            expected_version=current.version,
            provenance=provenance,
        ),
    )


async def update_step_progress(
    session: AsyncSession,
    principal: Principal,
    roadmap_id: uuid.UUID,
    step_key: str,
    payload: StepProgressUpdate,
    expected_version: int,
) -> Roadmap:
    """Bounded progress write; see `roadmap_structure.update_step_progress`."""
    from studio_api.services import roadmap_structure as structure_service

    return await structure_service.update_step_progress(
        session, principal, roadmap_id, step_key, payload, expected_version
    )
