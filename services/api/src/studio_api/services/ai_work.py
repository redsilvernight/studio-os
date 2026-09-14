from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.ai_work import AIWorkLogCreate, AIWorkLogUpdate, AIWorkStatus
from studio_contracts.auth import Role

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.services.authz import Principal, ensure_can_write, forbidden


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


async def create_ai_work(
    session: AsyncSession, principal: Principal, work_in: AIWorkLogCreate
) -> AIWorkLogModel:
    ensure_can_write(principal, "ai_work")
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


async def _ensure_ai_work_owned(
    session: AsyncSession, principal: Principal, work: AIWorkLogModel
) -> None:
    """Ownership for a PATCH: `AIWorkLogModel.machine_id` is nullable (an
    entry logged by a coordinator not tied to a specific machine), so the
    non-null `agent_id` (per the audit's "agent_id sur AIWorkLog") is the
    fallback — the same actor-ownership shape `events.resolve_event_identity`
    already uses for `actor_type=agent`."""
    ensure_can_write(principal, "ai_work")
    if principal.role == Role.ADMIN:
        return
    if work.machine_id is not None:
        if work.machine_id != principal.machine.id:
            raise forbidden("ai_work", "update")
        return
    agent = await session.get(AgentModel, work.agent_id)
    if agent is None or agent.machine_id != principal.machine.id:
        raise forbidden("ai_work", "update")


async def update_ai_work(
    session: AsyncSession, principal: Principal, work: AIWorkLogModel, work_in: AIWorkLogUpdate
) -> AIWorkLogModel:
    await _ensure_ai_work_owned(session, principal, work)
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
