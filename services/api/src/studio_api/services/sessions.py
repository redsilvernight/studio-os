from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.sessions import WorkSessionCreate

from studio_api.db.models.work_session import WorkSessionModel


async def list_sessions(
    session: AsyncSession, task_id: uuid.UUID | None = None
) -> list[WorkSessionModel]:
    stmt = select(WorkSessionModel)
    if task_id is not None:
        stmt = stmt.where(WorkSessionModel.task_id == task_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def start_session(session: AsyncSession, session_in: WorkSessionCreate) -> WorkSessionModel:
    work_session = WorkSessionModel(
        task_id=session_in.task_id,
        machine_id=session_in.machine_id,
        agent_id=session_in.agent_id,
        started_at=datetime.now(UTC),
    )
    session.add(work_session)
    await session.commit()
    await session.refresh(work_session)
    return work_session


async def end_session(session: AsyncSession, session_id: uuid.UUID) -> WorkSessionModel:
    work_session = await session.get(WorkSessionModel, session_id)
    if work_session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    work_session.ended_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(work_session)
    return work_session
