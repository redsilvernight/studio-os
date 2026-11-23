"""Break-glass exception access (DEC-0384).

Rules enforced here, not in the HTTP layer:

- an operator may only open a *request*: nothing is granted until the studio
  owner explicitly approves it;
- an approval carries a bounded window, at most 24 hours, and a declared scope
  (`metadata` or `support`) — content is not a scope;
- the owner may revoke at any time, and a pending or elapsed window expires on
  its own at read time;
- every transition appends one `break_glass_audit` row, in the same
  transaction as the transition it records.

The journal is append-only at the database level (0055 trigger): this module
never updates or deletes an audit row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.break_glass import (
    MAX_BREAK_GLASS_HOURS,
    BreakGlassAuditEvent,
    BreakGlassAuditModel,
    BreakGlassRequestModel,
    BreakGlassScope,
    BreakGlassStatus,
)
from studio_api.db.models.studio import StudioModel
from studio_api.services.authz import Principal

REQUEST_WINDOW = timedelta(hours=MAX_BREAK_GLASS_HOURS)


def _not_pending() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "error_code": "break_glass_not_pending",
            "message": "this request is not awaiting the owner's decision",
        },
    )


def _not_open() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "error_code": "break_glass_not_open",
            "message": "this request has no open access window to revoke",
        },
    )


def _audit(
    session: AsyncSession,
    event: BreakGlassAuditEvent,
    request: BreakGlassRequestModel,
    actor: str,
    at: datetime,
) -> None:
    session.add(
        BreakGlassAuditModel(
            event=event.value,
            request_id=request.id,
            studio_id=request.studio_id,
            actor=actor,
            at=at,
        )
    )


async def _studio_or_404(session: AsyncSession, studio_id: uuid.UUID) -> StudioModel:
    studio = await session.get(StudioModel, studio_id)
    if studio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "studio not found")
    return studio


async def _request_or_404(
    session: AsyncSession, studio_id: uuid.UUID, request_id: uuid.UUID, *, for_update: bool = False
) -> BreakGlassRequestModel:
    statement = select(BreakGlassRequestModel).where(
        BreakGlassRequestModel.id == request_id,
        BreakGlassRequestModel.studio_id == studio_id,
    )
    if for_update:
        statement = statement.with_for_update()
    request = await session.scalar(statement)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "break glass request not found")
    return request


async def expire_due(
    session: AsyncSession, studio_id: uuid.UUID, *, now: datetime | None = None
) -> list[BreakGlassRequestModel]:
    """Evaluate expiry at read time: a request still pending after 24 hours, or
    an approved window past its `expires_at`, becomes `expired` with one audit
    row each. Returns the requests that just expired."""
    moment = now or datetime.now(UTC)
    rows = (
        await session.scalars(
            select(BreakGlassRequestModel)
            .where(
                BreakGlassRequestModel.studio_id == studio_id,
                or_(
                    (
                        (BreakGlassRequestModel.status == BreakGlassStatus.REQUESTED.value)
                        & (BreakGlassRequestModel.requested_at <= moment - REQUEST_WINDOW)
                    ),
                    (
                        (BreakGlassRequestModel.status == BreakGlassStatus.APPROVED.value)
                        & (BreakGlassRequestModel.expires_at <= moment)
                    ),
                ),
            )
            .with_for_update()
        )
    ).all()
    for request in rows:
        request.status = BreakGlassStatus.EXPIRED.value
        _audit(session, BreakGlassAuditEvent.EXPIRED, request, "system", moment)
    return list(rows)


async def create_request(
    session: AsyncSession,
    *,
    studio_id: uuid.UUID,
    operator_ref: str,
    reason: str,
    scope: BreakGlassScope,
    now: datetime | None = None,
) -> BreakGlassRequestModel:
    await _studio_or_404(session, studio_id)
    moment = now or datetime.now(UTC)
    request = BreakGlassRequestModel(
        studio_id=studio_id,
        operator_ref=operator_ref,
        reason=reason,
        scope=scope.value,
        status=BreakGlassStatus.REQUESTED.value,
        requested_at=moment,
    )
    session.add(request)
    await session.flush()
    _audit(session, BreakGlassAuditEvent.REQUESTED, request, f"operator:{operator_ref}", moment)
    await session.commit()
    await session.refresh(request)
    return request


async def list_requests(
    session: AsyncSession,
    studio_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> list[BreakGlassRequestModel]:
    expired = await expire_due(session, studio_id, now=now)
    if expired:
        await session.commit()
    return list(
        (
            await session.scalars(
                select(BreakGlassRequestModel)
                .where(BreakGlassRequestModel.studio_id == studio_id)
                .order_by(
                    BreakGlassRequestModel.requested_at.desc(),
                    BreakGlassRequestModel.id.desc(),
                )
            )
        ).all()
    )


async def approve_request(
    session: AsyncSession,
    principal: Principal,
    studio_id: uuid.UUID,
    request_id: uuid.UUID,
    *,
    duration_hours: int,
    now: datetime | None = None,
) -> BreakGlassRequestModel:
    if not 1 <= duration_hours <= MAX_BREAK_GLASS_HOURS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "break_glass_duration_out_of_range",
                "message": f"duration must be between 1 and {MAX_BREAK_GLASS_HOURS} hours",
            },
        )
    moment = now or datetime.now(UTC)
    await expire_due(session, studio_id, now=moment)
    request = await _request_or_404(session, studio_id, request_id, for_update=True)
    if request.status != BreakGlassStatus.REQUESTED.value:
        raise _not_pending()
    request.status = BreakGlassStatus.APPROVED.value
    request.decided_by_user_id = principal.user.id
    request.decided_at = moment
    request.expires_at = moment + timedelta(hours=duration_hours)
    _audit(
        session,
        BreakGlassAuditEvent.APPROVED,
        request,
        f"user:{principal.user.email}",
        moment,
    )
    await session.commit()
    await session.refresh(request)
    return request


async def deny_request(
    session: AsyncSession,
    principal: Principal,
    studio_id: uuid.UUID,
    request_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> BreakGlassRequestModel:
    moment = now or datetime.now(UTC)
    await expire_due(session, studio_id, now=moment)
    request = await _request_or_404(session, studio_id, request_id, for_update=True)
    if request.status != BreakGlassStatus.REQUESTED.value:
        raise _not_pending()
    request.status = BreakGlassStatus.DENIED.value
    request.decided_by_user_id = principal.user.id
    request.decided_at = moment
    _audit(
        session,
        BreakGlassAuditEvent.DENIED,
        request,
        f"user:{principal.user.email}",
        moment,
    )
    await session.commit()
    await session.refresh(request)
    return request


async def revoke_request(
    session: AsyncSession,
    principal: Principal,
    studio_id: uuid.UUID,
    request_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> BreakGlassRequestModel:
    moment = now or datetime.now(UTC)
    await expire_due(session, studio_id, now=moment)
    request = await _request_or_404(session, studio_id, request_id, for_update=True)
    if request.status != BreakGlassStatus.APPROVED.value:
        raise _not_open()
    request.status = BreakGlassStatus.REVOKED.value
    _audit(
        session,
        BreakGlassAuditEvent.REVOKED,
        request,
        f"user:{principal.user.email}",
        moment,
    )
    await session.commit()
    await session.refresh(request)
    return request


async def list_audit(
    session: AsyncSession,
    studio_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> list[BreakGlassAuditModel]:
    expired = await expire_due(session, studio_id, now=now)
    if expired:
        await session.commit()
    return list(
        (
            await session.scalars(
                select(BreakGlassAuditModel)
                .where(BreakGlassAuditModel.studio_id == studio_id)
                .order_by(BreakGlassAuditModel.at, BreakGlassAuditModel.id)
            )
        ).all()
    )
