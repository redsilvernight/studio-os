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
    Roadmap,
    RoadmapCreate,
    RoadmapDocument,
    RoadmapErrorCode,
    RoadmapImport,
    RoadmapStatus,
    RoadmapSummary,
    RoadmapTransition,
    RoadmapUpdate,
    StepProgressUpdate,
    TransitionRequest,
    WriteKind,
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
    content_changed,
    finish,
    guard_write,
    invalid_roadmap,
    invalid_state,
    load_tree,
    lock_roadmap,
    not_found,
    read_roadmap,
    record_snapshot,
    reference_not_found,
    resolve_provenance,
    roadmap_error,
)


def text_or_none(value: str | None) -> str | None:
    """PATCH semantics of P1: an empty string clears an optional text field."""
    return value or None


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
    roadmap.revision_no += 1
    document = build_document(await load_tree(session, roadmap))
    add_revision(
        session,
        roadmap,
        prov,
        kind="proposal",
        revision_no=roadmap.revision_no,
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
