from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_, select
from studio_contracts.agent_identity import (
    AgentIdentityLinkRequest,
    AgentIdentityRequest,
    AgentIdentityResult,
)
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

_LEGACY_EXCLUDED = {"__all__": {"owner_user_id", "superseded_by_agent_id"}}


@router.get(
    "",
    response_model=list[Agent],
    response_model_exclude=_LEGACY_EXCLUDED,
    description=(
        "List agent provenance identities owned by the caller's user, or legacy rows whose "
        "machine belongs to the "
        "caller's User, every agent for `admin` (contract version 2)."
    ),
    responses={**RESP_401_UNAUTHORIZED},
)
async def list_agents(
    session: DbSession,
    principal: CurrentPrincipal,
    include_identity_owner: bool = False,
    include_identity_link: bool = False,
) -> list[Agent] | JSONResponse:
    stmt = select(AgentModel)
    if principal.role != Role.ADMIN:
        stmt = stmt.outerjoin(MachineModel, AgentModel.machine_id == MachineModel.id).where(
            or_(
                AgentModel.owner_user_id == principal.user.id,
                and_(
                    AgentModel.owner_user_id.is_(None),
                    MachineModel.owner_user_id == principal.user.id,
                ),
            )
        )
    result = await session.execute(stmt)
    agents = [Agent.model_validate(a) for a in result.scalars().all()]
    if include_identity_owner or include_identity_link:
        payload = []
        for agent in agents:
            row = agent.model_dump(mode="json")
            if not include_identity_owner:
                row.pop("owner_user_id", None)
            if not include_identity_link:
                row.pop("superseded_by_agent_id", None)
            payload.append(row)
        return JSONResponse(payload)
    return agents


@router.post(
    "/resolve-identity",
    response_model=AgentIdentityResult,
    description="Resolve the authenticated user's durable logical harness/provider/observed-model "
    "identity across authorized machines. An alias alone returns unknown without creation.",
    responses={
        201: {"model": AgentIdentityResult, "description": "Identity created"},
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
    },
)
async def resolve_identity(
    payload: AgentIdentityRequest,
    response: Response,
    session: DbSession,
    principal: CurrentPrincipal,
) -> AgentIdentityResult:
    result = await agents_service.resolve_identity(session, principal, payload)
    if result.created:
        response.status_code = status.HTTP_201_CREATED
    return result


@router.post(
    "",
    response_model=Agent,
    response_model_exclude={"owner_user_id", "superseded_by_agent_id"},
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
    response_model_exclude={
        "agent": {"owner_user_id", "superseded_by_agent_id"},
    },
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


@router.post(
    "/{agent_id}/supersede",
    response_model=Agent,
    status_code=status.HTTP_200_OK,
    description=(
        "Explicitly reconcile a former identity with its canonical one "
        "the former row keeps its machine, metadata, stable key "
        "and history, and only gains a `superseded_by_agent_id` pointer — "
        "nothing is merged, renamed or deleted, so clearing the pointer "
        "restores the previous state. `admin` reconciles any user's rows; "
        "otherwise the caller must own both the former row's machine and the "
        "canonical identity. Repeating the same link is refused with `409 "
        "already_superseded` (never a silent second link), and a canonical "
        "row must itself be user-scoped and unlinked."
    ),
    responses={
        200: {"model": Agent, "description": "Former identity linked"},
        **RESP_401_UNAUTHORIZED,
        **RESP_403_FORBIDDEN,
        404: {"description": "`not_found`: one of the two agents does not exist"},
        409: {
            "description": "`invalid_identity_link` (self, or canonical not user-scoped/"
            "already linked) or `already_superseded`"
        },
    },
)
async def supersede_identity(
    agent_id: uuid.UUID,
    payload: AgentIdentityLinkRequest,
    session: DbSession,
    principal: CurrentPrincipal,
) -> Agent:
    linked = await agents_service.supersede_identity(
        session, principal, agent_id, payload.canonical_agent_id
    )
    return Agent.model_validate(linked)
