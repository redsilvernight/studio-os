from __future__ import annotations

from fastapi import APIRouter, Header, Request, status
from sqlalchemy import select
from studio_contracts.auth import Agent, AgentCreate

from studio_api.db.models.agent import AgentModel
from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.services import agents as agents_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("", response_model=list[Agent])
async def list_agents(session: DbSession, machine: CurrentMachine) -> list[Agent]:
    result = await session.execute(select(AgentModel))
    return [Agent.model_validate(a) for a in result.scalars().all()]


@router.post("", response_model=Agent, status_code=status.HTTP_201_CREATED)
async def register_agent(
    agent_in: AgentCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Agent:
    """Public operational-provenance registration (CC-1): any writer may
    materialize an `Agent` identity attached to its own authenticated
    machine. Runs `ensure_can_write` unconditionally, ahead of
    `run_idempotent`'s replay short-circuit — see
    `routers/tasks.py::create_task` for why (DEC-0036)."""
    ensure_can_write(principal, "agent")

    async def _create() -> Agent:
        return Agent.model_validate(await agents_service.create_agent(session, principal, agent_in))

    return await idempotency_service.run_idempotent(
        session,
        request,
        idempotency_key,
        "POST /agents",
        Agent,
        _create,
        status.HTTP_201_CREATED,
    )
