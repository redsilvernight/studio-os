from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.machine import MachineModel
from studio_api.services import claims as claims_service
from studio_api.services import events as events_service
from studio_api.services import idempotency as idempotency_service
from studio_contracts.claims import ResourceClaimCreate, ResourceType
from studio_contracts.events import EventCreate, EventType

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_claim(claim: ResourceClaimModel) -> dict[str, Any]:
    return {
        "id": str(claim.id),
        "project_id": str(claim.project_id),
        "task_id": str(claim.task_id) if claim.task_id else None,
        "resource_path": claim.resource_path,
        "resource_type": claim.resource_type,
        "status": claim.status,
        "claimed_by_machine_id": str(claim.claimed_by_machine_id),
        "expires_at": claim.expires_at.isoformat(),
    }


async def studio_get_resource_claims(project_id: str, ctx: Context) -> dict[str, Any]:
    """List resource claims for a project (UUID string), any status."""

    async def _handler(session: AsyncSession, _machine: MachineModel) -> dict[str, Any]:
        parsed = parse_uuid(project_id, "project_id")
        if isinstance(parsed, dict):
            return parsed
        claims = await claims_service.list_claims(session, project_id=parsed)
        return {"claims": [_compact_claim(c) for c in claims]}

    return await run_tool(ctx, _handler)


async def studio_claim_resource(
    project_id: str,
    resource_path: str,
    resource_type: str,
    ttl_seconds: int,
    ctx: Context,
    task_id: str | None = None,
    agent_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Soft lock a resource path for the caller's machine (never blocks a Git
    operation or a file write — it warns via a `resource.conflict` event when
    another active claim overlaps it). Pass a caller-generated
    `idempotency_key` when this call might be retried — replaying the same
    key with the same arguments returns the original claim instead of
    creating a second one (and never re-emits the conflict event); the same
    key with different arguments fails with
    `idempotency_key_payload_mismatch` (DEC-0027)."""

    async def _handler(session: AsyncSession, machine: MachineModel) -> dict[str, Any]:
        parsed_project = parse_uuid(project_id, "project_id")
        if isinstance(parsed_project, dict):
            return parsed_project
        try:
            parsed_type = ResourceType(resource_type)
        except ValueError:
            return {
                "error_code": "invalid_argument",
                "message": f"unknown resource_type: {resource_type!r}",
            }
        parsed_task_id: UUID | None = None
        if task_id is not None:
            parsed_task = parse_uuid(task_id, "task_id")
            if isinstance(parsed_task, dict):
                return parsed_task
            parsed_task_id = parsed_task
        parsed_agent_id: UUID | None = None
        if agent_id is not None:
            parsed_agent = parse_uuid(agent_id, "agent_id")
            if isinstance(parsed_agent, dict):
                return parsed_agent
            parsed_agent_id = parsed_agent

        async def _create() -> dict[str, Any]:
            claim = await claims_service.create_claim(
                session,
                ResourceClaimCreate(
                    project_id=parsed_project,
                    task_id=parsed_task_id,
                    resource_path=resource_path,
                    resource_type=parsed_type,
                    ttl_seconds=ttl_seconds,
                ),
                machine.id,
                parsed_agent_id,
            )
            if await claims_service.has_conflict(session, claim):
                await events_service.create_event(
                    session,
                    EventCreate(
                        event_id=uuid4(),
                        event_type=EventType.RESOURCE_CONFLICT,
                        project_id=claim.project_id,
                        task_id=claim.task_id,
                        machine_id=machine.id,
                        actor_type="system",
                        actor_id=machine.id,
                        client_timestamp=datetime.now(UTC),
                        payload={"claim_id": str(claim.id), "resource_path": claim.resource_path},
                    ),
                )
            return _compact_claim(claim)

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {
                    "project_id": project_id,
                    "resource_path": resource_path,
                    "resource_type": resource_type,
                    "ttl_seconds": ttl_seconds,
                    "task_id": task_id,
                    "agent_id": agent_id,
                },
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_claim_resource", request_hash, _create
        )

    return await run_tool(ctx, _handler)


async def studio_release_resource(claim_id: str, ctx: Context) -> dict[str, Any]:
    """Release a resource claim by id (UUID string)."""

    async def _handler(session: AsyncSession, _machine: MachineModel) -> dict[str, Any]:
        parsed = parse_uuid(claim_id, "claim_id")
        if isinstance(parsed, dict):
            return parsed
        claim = await claims_service.get_claim(session, parsed)
        claim = await claims_service.release_claim(session, claim)
        return _compact_claim(claim)

    return await run_tool(ctx, _handler)
