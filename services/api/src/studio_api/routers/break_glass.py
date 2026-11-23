"""Break-glass exception access routes (DEC-0384, 0055).

An instance operator opens a motivated request; the studio owner alone lists,
approves (a window of at most 24 hours) or denies it, and may revoke an open
window at any time. The append-only journal is readable by the studio's
`admin`/`owner` (Réglages > Confidentialité). No route here reads client
content: the declared scope is `metadata` or `support`, nothing else.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator

from studio_api.db.models.break_glass import (
    MAX_BREAK_GLASS_HOURS,
    BreakGlassAuditModel,
    BreakGlassRequestModel,
    BreakGlassScope,
)
from studio_api.db.models.studio import StudioRole
from studio_api.deps import CurrentPrincipal, DbSession, require_operator
from studio_api.openapi_meta import RESP_401_UNAUTHORIZED, RESP_403_FORBIDDEN, RESP_404_NOT_FOUND
from studio_api.services import break_glass as break_glass_service
from studio_api.services import studios as studios_service
from studio_api.services.authz import Principal, ensure_studio_role

router = APIRouter(prefix="/api/v1/studios", tags=["studios"])

Operator = Annotated[Principal, Depends(require_operator)]


class BreakGlassCreate(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)
    scope: BreakGlassScope = BreakGlassScope.METADATA

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must not be blank")
        return stripped


class BreakGlassApproval(BaseModel):
    duration_hours: int = Field(..., ge=1, le=MAX_BREAK_GLASS_HOURS)


class BreakGlassRequestRead(BaseModel):
    id: uuid.UUID
    studio_id: uuid.UUID
    operator_ref: str
    reason: str
    scope: str
    requested_at: datetime
    status: str
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None
    expires_at: datetime | None


class BreakGlassAuditRead(BaseModel):
    id: uuid.UUID
    event: str
    request_id: uuid.UUID
    studio_id: uuid.UUID
    actor: str
    at: datetime


def _request(row: BreakGlassRequestModel) -> BreakGlassRequestRead:
    return BreakGlassRequestRead(
        id=row.id,
        studio_id=row.studio_id,
        operator_ref=row.operator_ref,
        reason=row.reason,
        scope=row.scope,
        requested_at=row.requested_at,
        status=row.status,
        decided_by_user_id=row.decided_by_user_id,
        decided_at=row.decided_at,
        expires_at=row.expires_at,
    )


def _audit(row: BreakGlassAuditModel) -> BreakGlassAuditRead:
    return BreakGlassAuditRead(
        id=row.id,
        event=row.event,
        request_id=row.request_id,
        studio_id=row.studio_id,
        actor=row.actor,
        at=row.at,
    )


async def _manager(session: DbSession, principal: Principal, studio_id: uuid.UUID) -> Principal:
    actor = await studios_service.studio_principal(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.ADMIN)
    return actor


async def _owner(session: DbSession, principal: Principal, studio_id: uuid.UUID) -> Principal:
    actor = await studios_service.studio_principal(session, principal, studio_id)
    ensure_studio_role(actor, StudioRole.OWNER)
    return actor


@router.post(
    "/{studio_id}/break-glass/requests",
    response_model=BreakGlassRequestRead,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Open a motivated break-glass request for one studio. Instance operator "
        "only (`is_operator`); the request grants nothing by itself — the studio "
        "owner must approve it. `scope` is `metadata` or `support`; there is no "
        "content scope. Every request appends one audit row."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_404_NOT_FOUND},
)
async def create_request(
    studio_id: uuid.UUID,
    body: BreakGlassCreate,
    session: DbSession,
    operator: Operator,
) -> BreakGlassRequestRead:
    row = await break_glass_service.create_request(
        session,
        studio_id=studio_id,
        operator_ref=operator.user.email,
        reason=body.reason,
        scope=body.scope,
    )
    return _request(row)


@router.get(
    "/{studio_id}/break-glass/requests",
    response_model=list[BreakGlassRequestRead],
    description=(
        "Break-glass requests of this studio, newest first (`owner`/`admin`), "
        "with their status. Pending requests past 24 hours and elapsed approved "
        "windows are expired here, each appending its own audit row."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_requests(
    studio_id: uuid.UUID,
    session: DbSession,
    principal: CurrentPrincipal,
) -> list[BreakGlassRequestRead]:
    await _manager(session, principal, studio_id)
    return [_request(row) for row in await break_glass_service.list_requests(session, studio_id)]


@router.post(
    "/{studio_id}/break-glass/requests/{request_id}/approve",
    response_model=BreakGlassRequestRead,
    description=(
        "Approve a pending request for a bounded window (`duration_hours`, 1 to "
        "24). Studio `owner` only; another studio's request answers 404 and an "
        "already decided one `409 break_glass_not_pending`."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        "409": {"description": "The request is no longer awaiting a decision."},
    },
)
async def approve_request(
    studio_id: uuid.UUID,
    request_id: uuid.UUID,
    body: BreakGlassApproval,
    session: DbSession,
    principal: CurrentPrincipal,
) -> BreakGlassRequestRead:
    owner = await _owner(session, principal, studio_id)
    row = await break_glass_service.approve_request(
        session, owner, studio_id, request_id, duration_hours=body.duration_hours
    )
    return _request(row)


@router.post(
    "/{studio_id}/break-glass/requests/{request_id}/deny",
    response_model=BreakGlassRequestRead,
    description=(
        "Refuse a pending request: nothing is opened and the refusal is journaled. "
        "Studio `owner` only; another studio's request answers 404."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        "409": {"description": "The request is no longer awaiting a decision."},
    },
)
async def deny_request(
    studio_id: uuid.UUID,
    request_id: uuid.UUID,
    session: DbSession,
    principal: CurrentPrincipal,
) -> BreakGlassRequestRead:
    owner = await _owner(session, principal, studio_id)
    row = await break_glass_service.deny_request(session, owner, studio_id, request_id)
    return _request(row)


@router.post(
    "/{studio_id}/break-glass/requests/{request_id}/revoke",
    response_model=BreakGlassRequestRead,
    description=(
        "Revoke an approved window at any time. Studio `owner` only; a request "
        "without an open window answers `409 break_glass_not_open`."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        **RESP_404_NOT_FOUND,
        "409": {"description": "No open window to revoke."},
    },
)
async def revoke_request(
    studio_id: uuid.UUID,
    request_id: uuid.UUID,
    session: DbSession,
    principal: CurrentPrincipal,
) -> BreakGlassRequestRead:
    owner = await _owner(session, principal, studio_id)
    row = await break_glass_service.revoke_request(session, owner, studio_id, request_id)
    return _request(row)


@router.get(
    "/{studio_id}/break-glass/audit",
    response_model=list[BreakGlassAuditRead],
    description=(
        "Append-only break-glass journal of this studio, oldest first, visible to "
        "the studio's `owner`/`admin` (Réglages > Confidentialité): request, "
        "decision, expiry and revocation, with the actor and the timestamp. Never "
        "a content excerpt."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN},
)
async def list_audit(
    studio_id: uuid.UUID,
    session: DbSession,
    principal: CurrentPrincipal,
) -> list[BreakGlassAuditRead]:
    await _manager(session, principal, studio_id)
    return [_audit(row) for row in await break_glass_service.list_audit(session, studio_id)]
