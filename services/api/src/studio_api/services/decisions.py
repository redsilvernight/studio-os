from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy import CursorResult, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.decisions import DecisionCreate, DecisionStatus

from studio_api.db.models.decision import DecisionModel
from studio_api.services.authz import Principal, ensure_can_write, forbidden


async def _next_readable_id(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT nextval('decisions_readable_id_seq')"))
    next_value = result.scalar_one()
    return f"DEC-{next_value:04d}"


async def list_decisions(
    session: AsyncSession, project_id: uuid.UUID | None = None
) -> list[DecisionModel]:
    stmt = select(DecisionModel)
    if project_id is not None:
        stmt = stmt.where(DecisionModel.project_id == project_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_decision(
    session: AsyncSession, principal: Principal, decision_in: DecisionCreate
) -> DecisionModel:
    ensure_can_write(principal, "decision")
    decision = DecisionModel(
        readable_id=await _next_readable_id(session),
        project_id=decision_in.project_id,
        task_id=decision_in.task_id,
        title=decision_in.title,
        body=decision_in.body,
        proposed_by_type=decision_in.proposed_by_type,
        proposed_by_id=decision_in.proposed_by_id,
    )
    session.add(decision)
    await session.commit()
    await session.refresh(decision)
    return decision


_ALLOWED_SOURCES: dict[DecisionStatus, frozenset[str]] = {
    DecisionStatus.ACCEPTED: frozenset({DecisionStatus.PROPOSED.value}),
    DecisionStatus.SUPERSEDED: frozenset(
        {DecisionStatus.PROPOSED.value, DecisionStatus.ACCEPTED.value}
    ),
}


def _invalid_transition(current: str, target: DecisionStatus) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "error_code": "invalid_status_transition",
            "message": f"cannot set status {target.value!r} from {current!r}",
        },
    )


async def _transition_decision(
    session: AsyncSession, principal: Principal, decision_id: uuid.UUID, target: DecisionStatus
) -> DecisionModel:
    """Accepting or superseding a recorded decision is a human governance
    action, distinct from proposing one: only `admin` may perform it (the
    same trust boundary as resolving an AI work review, DEC-0041), and only
    from a legal source state (`proposed` for `accepted`; `proposed` or
    `accepted` for `superseded`) — anything else is `409
    invalid_status_transition`. The set of statuses is unchanged
    (`proposed|accepted|superseded`, DEC-0078).

    The write is a compare-and-set on `(id, status=current)`, so two racing
    admin transitions can never both win: the loser sees `rowcount == 0`,
    re-reads, and gets the same `409 invalid_status_transition` a sequential
    replay would — the documented guarantee holds under concurrency too,
    without introducing a `version` column on this append-only ledger."""
    ensure_can_write(principal, "decision")
    action = "accept" if target is DecisionStatus.ACCEPTED else "supersede"
    if principal.role != Role.ADMIN:
        raise forbidden("decision", action)

    decision = await session.get(DecisionModel, decision_id)
    if decision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decision not found")

    if decision.status not in _ALLOWED_SOURCES[target]:
        raise _invalid_transition(decision.status, target)

    result = await session.execute(
        update(DecisionModel)
        .where(DecisionModel.id == decision_id, DecisionModel.status == decision.status)
        .values(status=target.value)
    )
    if cast(CursorResult[Any], result).rowcount == 0:
        await session.rollback()
        current = await session.get(DecisionModel, decision_id)
        if current is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "decision not found")
        raise _invalid_transition(current.status, target)

    await session.commit()
    await session.refresh(decision)
    return decision


async def accept_decision(
    session: AsyncSession, principal: Principal, decision_id: uuid.UUID
) -> DecisionModel:
    return await _transition_decision(session, principal, decision_id, DecisionStatus.ACCEPTED)


async def supersede_decision(
    session: AsyncSession, principal: Principal, decision_id: uuid.UUID
) -> DecisionModel:
    return await _transition_decision(session, principal, decision_id, DecisionStatus.SUPERSEDED)
