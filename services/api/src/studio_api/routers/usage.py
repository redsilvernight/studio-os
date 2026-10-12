from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status
from pydantic import AwareDatetime
from studio_contracts.usage import UsageLedgerCorrection, UsageLedgerEntry, UsageLedgerEntryCreate

from studio_api.deps import CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_404_NOT_FOUND,
    RESP_409_IDEMPOTENCY,
    ErrorResponses,
    merge_conflict,
)
from studio_api.services import idempotency as idempotency_service
from studio_api.services import usage as usage_service

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])

_RESP_409_USAGE_IDENTITY: ErrorResponses = {
    409: {
        "description": (
            "Usage identity rejected: machine_id must equal the authenticated machine, "
            "including for an admin (actor_not_owned). A source event cannot change its "
            "project, links or collector (usage_identity_conflict). Linked resources must "
            "belong to the same project and agree on task and session (invalid_usage_link)."
        ),
        "content": {
            "application/json": {"example": {"detail": {"error_code": "usage_identity_conflict"}}}
        },
    }
}
_RESP_409_USAGE_VERSION: ErrorResponses = {
    409: {
        "description": (
            "Stale expected_version: version_conflict carries the current server_version. "
            "Read the entry and submit a new correction with its current version. "
            "An exact Idempotency-Key replay returns its original response before this check."
        ),
        "content": {
            "application/json": {
                "example": {"detail": {"error_code": "version_conflict", "server_version": 2}}
            }
        },
    }
}


@router.get(
    "",
    response_model=list[UsageLedgerEntry],
    description="List project-scoped usage entries ordered by update time, including corrections.",
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_usage(
    session: DbSession,
    principal: CurrentPrincipal,
    project_id: UUID | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
    session_id: UUID | None = Query(default=None),
    task_launch_id: UUID | None = Query(default=None),
    since: AwareDatetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[UsageLedgerEntry]:
    rows = await usage_service.list_usage(
        session,
        principal,
        project_id=project_id,
        task_id=task_id,
        session_id=session_id,
        task_launch_id=task_launch_id,
        since=since,
        limit=limit,
    )
    return [usage_service.to_entry(row) for row in rows]


@router.post(
    "",
    response_model=UsageLedgerEntry,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Record a fact on the authenticated machine. Replaying machine_id/source_event_id "
        "returns its existing entry. Identity changes fail with usage_identity_conflict. "
        "Supports Idempotency-Key; project, machine and linked resources are checked on replay."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **merge_conflict(_RESP_409_USAGE_IDENTITY, RESP_409_IDEMPOTENCY),
    },
)
async def create_usage(
    entry: UsageLedgerEntryCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> UsageLedgerEntry:
    await usage_service.validate_identity(session, principal, entry)

    async def _create() -> UsageLedgerEntry:
        return usage_service.to_entry(
            await usage_service.create_usage(
                session, principal, entry, commit=idempotency_key is None
            )
        )

    result = await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /usage",
        UsageLedgerEntry,
        _create,
        status.HTTP_201_CREATED,
    )
    await usage_service.validate_identity(session, principal, result)
    return result


@router.post(
    "/corrections",
    response_model=UsageLedgerEntry,
    description=(
        "Replace the whole measurement, provenance, period and pricing block of an owned "
        "fact. Identity and collector stay fixed. A stale expected_version fails with "
        "version_conflict and server_version. Exact Idempotency-Key replay precedes the "
        "version check and does not increment the entry again."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        **merge_conflict(_RESP_409_USAGE_IDENTITY, RESP_409_IDEMPOTENCY, _RESP_409_USAGE_VERSION),
    },
)
async def correct_usage(
    correction: UsageLedgerCorrection,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> UsageLedgerEntry:
    await usage_service.authorize_correction(session, principal, correction)

    async def _correct() -> UsageLedgerEntry:
        return usage_service.to_entry(
            await usage_service.correct_usage(
                session, principal, correction, commit=idempotency_key is None
            )
        )

    result = await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /usage/corrections",
        UsageLedgerEntry,
        _correct,
        status.HTTP_200_OK,
    )
    await usage_service.authorize_correction(session, principal, correction)
    return result
