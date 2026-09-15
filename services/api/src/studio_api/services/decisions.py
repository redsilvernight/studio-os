from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.decisions import DecisionCreate

from studio_api.db.models.decision import DecisionModel
from studio_api.services.authz import Principal, ensure_can_write


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
