from __future__ import annotations

from fastapi import APIRouter, Header, Request, Response, status
from sqlalchemy import select
from studio_contracts.auth import Agent, AgentCreate, AgentEnsureResult, Role

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.deps import CurrentPrincipal, DbSession
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
    description=(
        "List agent provenance identities: those whose machine belongs to the "
        "caller's User, every agent for `admin` (contract version 2)."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_agents(session: DbSession, principal: CurrentPrincipal) -> list[Agent]:
    stmt = select(AgentModel)
    if principal.role != Role.ADMIN:
        stmt = stmt.join(MachineModel, AgentModel.machine_id == MachineModel.id).where(
            MachineModel.owner_user_id == principal.user.id
        )
    result = await session.execute(stmt)
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


@router.post(
    "/ensure",
    response_model=AgentEnsureResult,
    description=(
        "Server-side `agents ensure` (AIB-I, additive): find this machine's "
        "agent for `AgentCreate.stable_key` or register it, so a retried "
        "session-start hook never registers a duplicate — even after the "
        "idempotency table forgot the original call. `machine_id` is always "
        "derived from the credential, never sent. Same machine + same key + "
        "same metadata returns the existing agent (`created=false`, `200`); "
        "same key + different metadata is `409 "
        "idempotency_key_payload_mismatch`, never a silent second agent. "
        "Without a `stable_key` this is a plain registration "
        "(`created=true`, `201`). The `stable_key` itself is the replay key "
        "(same pattern as `event_id` for `POST /events` and the natural key "
        "of `PUT /projects/{id}/members/{user_id}`), so no `Idempotency-Key` "
        "is needed here. Authorization: `ensure_can_write` — `readonly` -> "
        "`403 forbidden`. Confers no permission."
    ),
    responses={
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        409: {
            "description": "`idempotency_key_payload_mismatch`: same stable key, different body."
        },
    },
)
async def ensure_agent(
    agent_in: AgentCreate,
    response: Response,
    session: DbSession,
    principal: CurrentPrincipal,
) -> AgentEnsureResult:
    ensure_can_write(principal, "agent")
    agent, created = await agents_service.ensure_agent(session, principal, agent_in)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return AgentEnsureResult(agent=Agent.model_validate(agent), created=created)
