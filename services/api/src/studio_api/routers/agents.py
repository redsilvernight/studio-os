from __future__ import annotations

from fastapi import APIRouter, Header, Request, status
from sqlalchemy import select
from studio_contracts.auth import Agent, AgentCreate

from studio_api.db.models.agent import AgentModel
from studio_api.deps import CurrentMachine, CurrentPrincipal, DbSession
from studio_api.openapi_meta import (
    IDEMPOTENCY_KEY_DESCRIPTION,
    RESP_401_UNAUTHORIZED,
    RESP_403_FORBIDDEN,
    RESP_409_IDEMPOTENCY,
)
from studio_api.services import agents as agents_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import ensure_can_write

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get(
    "",
    response_model=list[Agent],
    description="List agent provenance identities. Any authenticated machine may read.",
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_agents(session: DbSession, machine: CurrentMachine) -> list[Agent]:
    result = await session.execute(select(AgentModel))
    return [Agent.model_validate(a) for a in result.scalars().all()]


@router.post(
    "",
    response_model=Agent,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Register an agent identity for the caller's own authenticated "
        "machine. `machine_id` is always derived from the credential — "
        "never send it. `display_name` is required; `agent_kind`, "
        "`agent_profile`, `harness`, `provider` and `model` are optional "
        "free-form metadata (open strings, default null, every value "
        "accepted). Registration confers no permission and is required for "
        "nothing except attributing AI work logs; authentication and "
        "authorization work without it. Accepts `Idempotency-Key` for safe "
        "retries."
    ),
    responses={**RESP_401_UNAUTHORIZED, **RESP_403_FORBIDDEN, **RESP_409_IDEMPOTENCY},
)
async def register_agent(
    agent_in: AgentCreate,
    request: Request,
    session: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", description=IDEMPOTENCY_KEY_DESCRIPTION
    ),
) -> Agent:
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
