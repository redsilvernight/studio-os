from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import AgentCreate

from studio_api.db.models.agent import AgentModel
from studio_api.services.authz import Principal, ensure_can_write


async def create_agent(
    session: AsyncSession, principal: Principal, agent_in: AgentCreate
) -> AgentModel:
    """Registers an operational provenance identity for the authenticated
    machine (CC-1). `machine_id` is derived from `principal`, never from
    client input — the same shape as `events.resolve_event_identity`
    (DEC-0035). Grants no permission: authorization stays `auth_role` +
    ownership (`authz.py`)."""
    ensure_can_write(principal, "agent")
    agent = AgentModel(
        machine_id=principal.machine.id,
        display_name=agent_in.display_name,
        agent_kind=agent_in.agent_kind,
        agent_profile=agent_in.agent_profile,
        harness=agent_in.harness,
        provider=agent_in.provider,
        model=agent_in.model,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent
