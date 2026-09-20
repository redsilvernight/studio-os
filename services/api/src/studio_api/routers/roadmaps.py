"""Canonical HTTP surface of the Roadmap domain (Roadmaps P3, DEC-0084/DEC-0085).

Thin adapters over `services.roadmaps`, `services.roadmap_structure` and
`services.roadmap_hydration`: no SQL and no business rule here. Reads are open
to any authenticated machine (including `readonly`, DEC-0063); writes go through
the services' write guard. Every mutation answers the resulting `Roadmap`, which
carries the new roadmap and step versions the next write needs.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from studio_contracts.roadmaps import (
    DependencyChange,
    HydrationApplyRequest,
    HydrationRequest,
    HydrationResult,
    LinkTask,
    PhaseCreate,
    PhaseUpdate,
    Reorder,
    Roadmap,
    RoadmapCreate,
    RoadmapDocument,
    RoadmapImport,
    RoadmapStatus,
    RoadmapSummary,
    RoadmapUpdate,
    StepCreate,
    StepProgressUpdate,
    StepUpdate,
    TransitionRequest,
    WriteProvenance,
)

from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    IF_MATCH_VERSION_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    ErrorResponses,
    merge_status,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import roadmap_hydration as hydration_service
from studio_api.services import roadmap_structure as structure_service
from studio_api.services import roadmaps as roadmaps_service

router = APIRouter(prefix="/api/v1", tags=["roadmaps"])

_ENVELOPE = 'Errors use the platform envelope `{"detail": {"error_code": ...}}` '
IdempotencyKey = Header(
    default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
)
IfMatchVersion = Header(alias="If-Match-Version", description=IF_MATCH_VERSION_DESCRIPTION)


def _resp(code: int, description: str, error_code: str, **extra: Any) -> ErrorResponses:
    return {
        code: {
            "description": description,
            "content": {
                "application/json": {"example": {"detail": {"error_code": error_code, **extra}}}
            },
        }
    }


RESP_404 = _resp(
    404,
    _ENVELOPE + "`not_found` (unknown roadmap or project) or `reference_not_found` "
    "(unknown phase/step key or task in the request).",
    "reference_not_found",
    message="step P1.1",
)
RESP_409_WRITE = merge_status(
    409,
    _resp(
        409,
        "`version_conflict` (stale `If-Match-Version` / `expected_*version`, carries "
        "`server_version`), `invalid_state` (the roadmap status does not accept this "
        "write, or the transition is not in the closed table; carries `status`), "
        "`active_roadmap_exists`, `dependency_cycle` (carries `path`), `step_has_links`, "
        "`duplicate_key` (carries `field`), `actor_not_owned` (declared `agent_id` not "
        "attached to the caller's machine) and, on replayable POSTs, "
        "`idempotency_key_payload_mismatch` / `idempotency_key_in_progress`.",
        "version_conflict",
        server_version=3,
    ),
)
RESP_422 = _resp(
    422,
    "`invalid_roadmap` (submitted document or edit is semantically invalid; `reason` "
    "is one of `duplicate_phase_key`, `duplicate_step_key`, `duplicate_hydration_key`, "
    "`unknown_dependency`, `self_dependency`, `duplicate_dependency`, "
    "`dependency_cycle`, `limit_exceeded`, `invalid_reorder`; `field` names the "
    "offending path), `task_project_mismatch`, or `limit_exceeded` (per-request bound; "
    "`limit` names it). A schema-shape error is the framework's native 422.",
    "invalid_roadmap",
    reason="duplicate_step_key",
    field="steps.P1.1",
)
_READ: ErrorResponses = {**RESP_401_UNAUTHORIZED, **RESP_404}
_WRITE: ErrorResponses = {
    **RESP_401_UNAUTHORIZED,
    **RESP_403_FORBIDDEN,
    **RESP_404,
    **RESP_409_WRITE,
    **RESP_422,
}


# --- roadmaps ---
@router.get(
    "/projects/{project_id}/roadmaps",
    response_model=list[RoadmapSummary],
    description=(
        "List a project's roadmaps (newest first), optionally by `status`. Any "
        "authenticated machine may read. A project may have several roadmaps but "
        "at most one `active`."
    ),
    responses=_READ,
)
async def list_roadmaps(
    project_id: UUID,
    session: DbSession,
    machine: CurrentMachine,
    roadmap_status: RoadmapStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[RoadmapSummary]:
    return await roadmaps_service.list_roadmaps(session, project_id, roadmap_status, limit, offset)


@router.post(
    "/roadmaps",
    response_model=Roadmap,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create an empty `draft` roadmap in a project. Requires a writer role. Accepts "
        "`Idempotency-Key`. A whole plan goes through `POST /roadmaps/import`."
    ),
    responses=_WRITE,
)
async def create_roadmap(
    payload: RoadmapCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = IdempotencyKey,
) -> Roadmap:
    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /roadmaps",
        Roadmap,
        lambda: roadmaps_service.create_roadmap(session, principal, payload),
        status.HTTP_201_CREATED,
    )


@router.post(
    "/roadmaps/import",
    response_model=Roadmap,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Create a `draft` (or `proposed` with `submit=true`) roadmap from a neutral "
        "`studio.roadmap/v1` document, atomically and without creating any Task. The "
        "document is validated before any write (`422 invalid_roadmap`). Requires a "
        "writer role. Accepts `Idempotency-Key`."
    ),
    responses=_WRITE,
)
async def import_roadmap(
    payload: RoadmapImport,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = IdempotencyKey,
) -> Roadmap:
    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /roadmaps/import",
        Roadmap,
        lambda: roadmaps_service.import_roadmap(session, principal, payload),
        status.HTTP_201_CREATED,
    )


@router.get(
    "/roadmaps/{roadmap_id}",
    response_model=Roadmap,
    description=(
        "Roadmap detail: phases and steps in stable order with derived state, "
        "availability, progress and `current_step_key`. Any authenticated machine may read."
    ),
    responses=_READ,
)
async def get_roadmap(roadmap_id: UUID, session: DbSession, machine: CurrentMachine) -> Roadmap:
    return await roadmaps_service.get_roadmap(session, roadmap_id)


@router.patch(
    "/roadmaps/{roadmap_id}",
    response_model=Roadmap,
    description=(
        "Edit the roadmap header (title, objective, context, metadata). Requires a writer "
        "role and the roadmap's `If-Match-Version`. Omitted or null = unchanged; an empty "
        "string clears an optional text field; `{}` clears `metadata`."
    ),
    responses=_WRITE,
)
async def update_roadmap(
    roadmap_id: UUID,
    payload: RoadmapUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
    if_match_version: int = IfMatchVersion,
) -> Roadmap:
    return await roadmaps_service.update_roadmap(
        session, principal, roadmap_id, payload, if_match_version
    )


@router.post(
    "/roadmaps/{roadmap_id}/transitions",
    response_model=Roadmap,
    description=(
        "Lifecycle change (closed table): `submit`, `approve`, `request_changes`, `reject`, "
        "`activate`, `complete`, `reopen`, `archive` — `archive` is the archival. `draft -> "
        "proposed` and `draft -> archived` need a writer role; every other transition needs "
        "`admin`/`developer` (the `agent` role can never activate, approve, reject, complete "
        "or archive an approved plan). `comment` is required for `request_changes`, "
        "`reject` and `reopen`. Activating an already active roadmap is a successful no-op. "
        "A project has at most one active roadmap."
    ),
    responses=_WRITE,
)
async def transition_roadmap(
    roadmap_id: UUID, payload: TransitionRequest, session: DbSession, principal: CurrentPrincipal
) -> Roadmap:
    return await roadmaps_service.transition_roadmap(session, principal, roadmap_id, payload)


@router.get(
    "/roadmaps/{roadmap_id}/export",
    response_model=RoadmapDocument,
    description=(
        "Export the current plan as the neutral, versioned `studio.roadmap/v1` document "
        "(no id, status, provenance or Task link). `format=pdf` is delivered by the export "
        "lane and currently answers `501`."
    ),
    responses={
        **_READ,
        501: {
            "description": "PDF export is not implemented by this surface yet.",
            "content": {
                "application/json": {"example": {"detail": {"error_code": "not_implemented"}}}
            },
        },
    },
)
async def export_roadmap(
    roadmap_id: UUID,
    session: DbSession,
    machine: CurrentMachine,
    export_format: Literal["json", "pdf"] = Query(default="json", alias="format"),
) -> RoadmapDocument:
    if export_format == "pdf":
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={"error_code": "not_implemented", "message": "pdf export is not available"},
        )
    return await roadmaps_service.export_roadmap(session, roadmap_id)


# --- phases ---
@router.post(
    "/roadmaps/{roadmap_id}/phases",
    response_model=Roadmap,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Append a phase. Body carries `expected_roadmap_version`. Accepts `Idempotency-Key`. "
        "Answers the updated roadmap."
    ),
    responses=_WRITE,
)
async def create_phase(
    roadmap_id: UUID,
    payload: PhaseCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = IdempotencyKey,
) -> Roadmap:
    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /roadmaps/{roadmap_id}/phases",
        Roadmap,
        lambda: structure_service.create_phase(session, principal, roadmap_id, payload),
        status.HTTP_201_CREATED,
    )


@router.post(
    "/roadmaps/{roadmap_id}/phases/reorder",
    response_model=Roadmap,
    description=(
        "Atomic reorder: `ordered_keys` must be a permutation of the current phase keys "
        "(`422 invalid_roadmap`/`invalid_reorder` otherwise). Checks and bumps the roadmap "
        "version."
    ),
    responses=_WRITE,
)
async def reorder_phases(
    roadmap_id: UUID, payload: Reorder, session: DbSession, principal: CurrentPrincipal
) -> Roadmap:
    return await structure_service.reorder_phases(session, principal, roadmap_id, payload)


@router.patch(
    "/roadmaps/{roadmap_id}/phases/{phase_key}",
    response_model=Roadmap,
    description="Edit a phase's title/objective. `If-Match-Version` = the phase's version.",
    responses=_WRITE,
)
async def update_phase(
    roadmap_id: UUID,
    phase_key: str,
    payload: PhaseUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
    if_match_version: int = IfMatchVersion,
) -> Roadmap:
    return await structure_service.update_phase(
        session, principal, roadmap_id, phase_key, payload, if_match_version
    )


@router.delete(
    "/roadmaps/{roadmap_id}/phases/{phase_key}",
    response_model=Roadmap,
    description=(
        "Delete a phase and its steps from a `draft` roadmap only (else `409 invalid_state`; "
        "mark steps `skipped` instead). Refused with `409 step_has_links` if any step is "
        "linked to a Task. `If-Match-Version` = the roadmap's version."
    ),
    responses=_WRITE,
)
async def delete_phase(
    roadmap_id: UUID,
    phase_key: str,
    session: DbSession,
    principal: CurrentPrincipal,
    if_match_version: int = IfMatchVersion,
) -> Roadmap:
    return await structure_service.delete_phase(
        session, principal, roadmap_id, phase_key, if_match_version, WriteProvenance()
    )


# --- steps ---
@router.post(
    "/roadmaps/{roadmap_id}/phases/{phase_key}/steps/reorder",
    response_model=Roadmap,
    description=(
        "Atomic reorder of a phase's steps: `ordered_keys` must be a permutation of its "
        "current step keys. Moving a step across phases is not supported in v1."
    ),
    responses=_WRITE,
)
async def reorder_steps(
    roadmap_id: UUID,
    phase_key: str,
    payload: Reorder,
    session: DbSession,
    principal: CurrentPrincipal,
) -> Roadmap:
    return await structure_service.reorder_steps(session, principal, roadmap_id, phase_key, payload)


@router.post(
    "/roadmaps/{roadmap_id}/phases/{phase_key}/steps",
    response_model=Roadmap,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Append a step (content, dependencies by key, task plan) to a phase. Body carries "
        "`expected_roadmap_version`. Accepts `Idempotency-Key`. Never creates a Task."
    ),
    responses=_WRITE,
)
async def create_step(
    roadmap_id: UUID,
    phase_key: str,
    payload: StepCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = IdempotencyKey,
) -> Roadmap:
    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /roadmaps/{roadmap_id}/phases/{phase_key}/steps",
        Roadmap,
        lambda: structure_service.create_step(session, principal, roadmap_id, phase_key, payload),
        status.HTTP_201_CREATED,
    )


@router.patch(
    "/roadmaps/{roadmap_id}/steps/{step_key}",
    response_model=Roadmap,
    description=(
        "Edit a step's content. `If-Match-Version` = the step's version. On an `active` "
        "roadmap, a content change by an agent (role `agent`, declared `agent_id` or "
        "`origin=ai_proposal`) is refused with `409 invalid_state` (proposals are a later "
        "lot); a human change is applied and snapshotted. Editing `tasks` never touches "
        "existing Tasks or links; editing `acceptance_criteria` clears `criteria_checked`."
    ),
    responses=_WRITE,
)
async def update_step(
    roadmap_id: UUID,
    step_key: str,
    payload: StepUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
    if_match_version: int = IfMatchVersion,
) -> Roadmap:
    return await structure_service.update_step(
        session, principal, roadmap_id, step_key, payload, if_match_version
    )


@router.patch(
    "/roadmaps/{roadmap_id}/steps/{step_key}/progress",
    response_model=Roadmap,
    description=(
        "Bounded progress update (`state_override` done/skipped, notes, checked criteria). "
        "Applied directly for any writer, including an agent; never a proposal. "
        "`If-Match-Version` = the step's version."
    ),
    responses=_WRITE,
)
async def update_step_progress(
    roadmap_id: UUID,
    step_key: str,
    payload: StepProgressUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
    if_match_version: int = IfMatchVersion,
) -> Roadmap:
    return await structure_service.update_step_progress(
        session, principal, roadmap_id, step_key, payload, if_match_version
    )


@router.delete(
    "/roadmaps/{roadmap_id}/steps/{step_key}",
    response_model=Roadmap,
    description=(
        "Delete a step from a `draft` roadmap only (else `409 invalid_state`). Refused with "
        "`409 step_has_links` if it is linked to a Task. Dependency edges to and from it are "
        "removed with it. `If-Match-Version` = the roadmap's version."
    ),
    responses=_WRITE,
)
async def delete_step(
    roadmap_id: UUID,
    step_key: str,
    session: DbSession,
    principal: CurrentPrincipal,
    if_match_version: int = IfMatchVersion,
) -> Roadmap:
    return await structure_service.delete_step(
        session, principal, roadmap_id, step_key, if_match_version, WriteProvenance()
    )


# --- dependencies ---
@router.post(
    "/roadmaps/{roadmap_id}/dependencies",
    response_model=Roadmap,
    description=(
        "Add `step_key -> depends_on_key`. An existing edge is a successful no-op; a cycle is "
        "`409 dependency_cycle` with the offending `path`; a self-edge is `422 invalid_roadmap`."
    ),
    responses=_WRITE,
)
async def add_dependency(
    roadmap_id: UUID, payload: DependencyChange, session: DbSession, principal: CurrentPrincipal
) -> Roadmap:
    return await structure_service.add_dependency(session, principal, roadmap_id, payload)


@router.post(
    "/roadmaps/{roadmap_id}/dependencies/remove",
    response_model=Roadmap,
    description="Remove `step_key -> depends_on_key`. Removing an absent edge is a no-op.",
    responses=_WRITE,
)
async def remove_dependency(
    roadmap_id: UUID, payload: DependencyChange, session: DbSession, principal: CurrentPrincipal
) -> Roadmap:
    return await structure_service.remove_dependency(session, principal, roadmap_id, payload)


# --- Step <-> Task links ---
@router.post(
    "/roadmaps/{roadmap_id}/steps/{step_key}/links",
    response_model=Roadmap,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Link an existing Task of the same project to a step (`422 task_project_mismatch` "
        "otherwise). Linking twice is a successful no-op. Accepts `Idempotency-Key`."
    ),
    responses=_WRITE,
)
async def link_task(
    roadmap_id: UUID,
    step_key: str,
    payload: LinkTask,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = IdempotencyKey,
) -> Roadmap:
    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /roadmaps/{roadmap_id}/steps/{step_key}/links",
        Roadmap,
        lambda: structure_service.link_task(session, principal, roadmap_id, step_key, payload),
        status.HTTP_201_CREATED,
    )


@router.delete(
    "/roadmaps/{roadmap_id}/steps/{step_key}/links/{task_id}",
    response_model=Roadmap,
    description=(
        "Remove the join between a step and a Task. The Task itself is never touched; "
        "removing an absent link is a successful no-op."
    ),
    responses=_WRITE,
)
async def unlink_task(
    roadmap_id: UUID, step_key: str, task_id: UUID, session: DbSession, principal: CurrentPrincipal
) -> Roadmap:
    return await structure_service.unlink_task(
        session, principal, roadmap_id, step_key, task_id, WriteProvenance()
    )


# --- hydration ---
@router.post(
    "/roadmaps/{roadmap_id}/hydration/preview",
    response_model=HydrationResult,
    description=(
        "What hydration would do, without writing: per plan item `create`, `reuse` (a Task is "
        "already linked under its `hydration_key`) or `skip` (step done/skipped). Any "
        "non-archived status; a non-`active` roadmap answers `applicable=false`."
    ),
    responses=_READ,
)
async def preview_hydration(
    roadmap_id: UUID, payload: HydrationRequest, session: DbSession, machine: CurrentMachine
) -> HydrationResult:
    return await hydration_service.preview_hydration(session, roadmap_id, payload)


@router.post(
    "/roadmaps/{roadmap_id}/hydration/apply",
    response_model=HydrationResult,
    description=(
        "Create the missing Tasks of the plan and link them, in one transaction. Requires an "
        "`active` roadmap (`409 invalid_state`), a writer role, and the `expected_version` read "
        "at preview (`409 version_conflict`). Idempotent: `Idempotency-Key` replays the original "
        "response, and a retry under a fresh key finds its links via `hydration_key` (`reuse`), "
        "never a duplicate. An existing Task is never modified or deleted."
    ),
    responses=_WRITE,
)
async def apply_hydration(
    roadmap_id: UUID,
    payload: HydrationApplyRequest,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = IdempotencyKey,
) -> HydrationResult:
    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        f"POST /roadmaps/{roadmap_id}/hydration/apply",
        HydrationResult,
        lambda: hydration_service.apply_hydration(session, principal, roadmap_id, payload),
        status.HTTP_200_OK,
    )
