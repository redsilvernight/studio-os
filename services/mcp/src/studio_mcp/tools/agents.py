from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import Context
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import agents as agents_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import Principal, ensure_can_write
from studio_contracts.agent_identity import AgentIdentityRequest
from studio_contracts.auth import Agent, AgentCreate

from studio_mcp.errors import run_tool


async def studio_resolve_agent_identity(
    harness: str,
    ctx: Context,
    provider: str | None = None,
    effective_model: str | None = None,
    selection_alias: str | None = None,
) -> dict[str, Any]:
    """Resolve the caller user's durable harness/model identity; aliases alone stay unknown."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        ensure_can_write(principal, "agent")
        try:
            request = AgentIdentityRequest(
                harness=harness,
                provider=provider,
                effective_model=effective_model,
                selection_alias=selection_alias,
            )
        except ValidationError:
            return {"error_code": "invalid_argument", "message": "invalid agent identity input"}
        result = await agents_service.resolve_identity(
            session,
            principal,
            request,
        )
        return result.model_dump(mode="json")

    return await run_tool(ctx, _handler)


async def studio_register_agent(
    display_name: str,
    ctx: Context,
    agent_kind: str = "",
    agent_profile: str | None = None,
    harness: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    stable_key: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Register an agent provenance identity for the caller's own machine."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        ensure_can_write(principal, "agent")

        async def _create() -> dict[str, Any]:
            created = await agents_service.create_agent(
                session,
                principal,
                AgentCreate(
                    display_name=display_name,
                    agent_kind=agent_kind,
                    agent_profile=agent_profile,
                    harness=harness,
                    provider=provider,
                    model=model,
                    stable_key=stable_key,
                ),
            )
            return Agent.model_validate(created).model_dump(mode="json", exclude={"owner_user_id"})

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {
                    "display_name": display_name,
                    "agent_kind": agent_kind,
                    "agent_profile": agent_profile,
                    "harness": harness,
                    "provider": provider,
                    "model": model,
                    "stable_key": stable_key,
                },
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_register_agent", request_hash, _create
        )

    return await run_tool(ctx, _handler)
