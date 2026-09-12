from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.ai_work import AIWorkLogCreate, AIWorkLogUpdate, AIWorkStatus

from studio_api.db.models.ai_work import AIWorkLogModel


async def list_ai_work(
    session: AsyncSession, project_id: uuid.UUID | None = None, task_id: uuid.UUID | None = None
) -> list[AIWorkLogModel]:
    stmt = select(AIWorkLogModel)
    if project_id is not None:
        stmt = stmt.where(AIWorkLogModel.project_id == project_id)
    if task_id is not None:
        stmt = stmt.where(AIWorkLogModel.task_id == task_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_ai_work(session: AsyncSession, work_in: AIWorkLogCreate) -> AIWorkLogModel:
    work = AIWorkLogModel(
        task_id=work_in.task_id,
        project_id=work_in.project_id,
        agent_id=work_in.agent_id,
        machine_id=work_in.machine_id,
        summary=work_in.summary,
        started_at=datetime.now(UTC),
    )
    session.add(work)
    await session.commit()
    await session.refresh(work)
    return work


async def update_ai_work(
    session: AsyncSession, work: AIWorkLogModel, work_in: AIWorkLogUpdate
) -> AIWorkLogModel:
    if work_in.summary is not None:
        work.summary = work_in.summary
    if work_in.status is not None:
        work.status = work_in.status.value
        if work_in.status in (AIWorkStatus.COMPLETED, AIWorkStatus.FAILED):
            work.ended_at = datetime.now(UTC)
    if work_in.changed_files is not None:
        work.changed_files = work_in.changed_files
    if work_in.tests_run is not None:
        work.tests_run = work_in.tests_run
    await session.commit()
    await session.refresh(work)
    return work
