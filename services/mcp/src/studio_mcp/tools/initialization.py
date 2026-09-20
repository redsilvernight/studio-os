"""Project-initialization MCP tools (Roadmaps P5, DEC-0084/DEC-0086).

Two tools, one intention pair: show what a structured plan would do, then
apply it. The server never invents the plan — the agent supplies it — and the
roadmap inside it is optional. Preview has no side effect; apply is idempotent
(`Idempotency-Key`) and replay-safe (existing project/tasks/roadmap are reused,
never duplicated).

An agent may initialize into an existing project, but creating a project is
provisioning: an agent-only caller fails `forbidden` when the project must be
created (same boundary as the project routes).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import idempotency as idempotency_service
from studio_api.services import initialization as initialization_service
from studio_api.services.authz import Principal, ensure_can_write
from studio_contracts.auth import Role
from studio_contracts.initialization import ProjectInitializationPlan
from studio_contracts.roadmaps import RoadmapOrigin, WriteProvenance

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid

_HASH_ENDPOINT = "MCP studio_apply_project_initialization"


async def studio_preview_project_initialization(
    plan: ProjectInitializationPlan, ctx: Context
) -> dict[str, Any]:
    """Validate a project-initialization plan and show exactly what would be
    created/reused/skipped — read-only, no side effect. A missing roadmap, an
    empty section or a missing optional Library resource are reported, not
    errors."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        target = initialization_service.StudioServicesInitializationTarget(session, principal)
        preview = await initialization_service.preview_initialization(target, plan)
        return preview.model_dump(mode="json")

    return await run_tool(ctx, _handler)


async def studio_apply_project_initialization(
    plan: ProjectInitializationPlan,
    ctx: Context,
    idempotency_key: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Apply a project-initialization plan. All-or-nothing at the decision
    level: any blocking problem refuses before writing anything. Section writes
    then go through their own services (a single transaction awaits the F1
    no-commit variants), so replay — not rollback — is what makes a partial
    failure safe. Replaying the same key returns the original summary; replaying
    without a key still reuses the project, tasks, roadmap and bindings that
    already exist instead of creating a duplicate."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_agent: UUID | None = None
        if agent_id is not None:
            candidate = parse_uuid(agent_id, "agent_id")
            if isinstance(candidate, dict):
                return candidate
            parsed_agent = candidate
        ensure_can_write(principal, "initialization")
        is_agent_write = parsed_agent is not None or principal.role is Role.AGENT
        origin = RoadmapOrigin.AI_PROPOSAL if is_agent_write else RoadmapOrigin.MANUAL
        provenance = WriteProvenance(origin=origin, agent_id=parsed_agent)
        target = initialization_service.StudioServicesInitializationTarget(session, principal)

        async def _apply() -> dict[str, Any]:
            result = await initialization_service.apply_initialization(
                target, plan, principal, provenance
            )
            return result.model_dump(mode="json")

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {"plan": plan.model_dump(mode="json"), "agent_id": agent_id},
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, _HASH_ENDPOINT, request_hash, _apply
        )

    return await run_tool(ctx, _handler)
