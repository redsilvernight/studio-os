from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from studio_contracts.auth import Agent

from studio_api.db.models.agent import AgentModel
from studio_api.deps import CurrentMachine, DbSession

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("", response_model=list[Agent])
async def list_agents(session: DbSession, machine: CurrentMachine) -> list[Agent]:
    result = await session.execute(select(AgentModel))
    return [Agent.model_validate(a) for a in result.scalars().all()]
