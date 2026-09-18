from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.decision import DecisionModel
from studio_api.services import decisions as decisions_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import Principal, ensure_can_write
from studio_contracts.decisions import DecisionCreate

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_decision(decision: DecisionModel) -> dict[str, Any]:
    return {
        "id": str(decision.id),
        "readable_id": decision.readable_id,
        "project_id": str(decision.project_id) if decision.project_id else None,
        "task_id": str(decision.task_id) if decision.task_id else None,
        "title": decision.title,
        "body": decision.body,
        "status": decision.status,
        "created_at": decision.created_at.isoformat(),
    }


async def studio_get_decisions(ctx: Context, project_id: str | None = None) -> dict[str, Any]:
    """List decisions, optionally filtered by project_id (UUID string)."""

    async def _handler(session: AsyncSession, _principal: Principal) -> dict[str, Any]:
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        decisions = await decisions_service.list_decisions(session, project_id=parsed_project_id)
        return {"decisions": [_compact_decision(d) for d in decisions]}

    return await run_tool(ctx, _handler)


async def studio_add_decision(
    title: str,
    body: str,
    ctx: Context,
    project_id: str | None = None,
    task_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Record a Decision (DEC-XXXX). `proposed_by` is derived from the caller's
    authenticated machine — the caller cannot claim another actor's identity.
    Pass a caller-generated `idempotency_key` when this call might be
    retried — replaying the same key with the same arguments returns the
    original Decision instead of allocating a second `DEC-XXXX` id; the same
    key with different arguments fails with
    `idempotency_key_payload_mismatch` (DEC-0027)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        parsed_task_id = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task_id = parsed
        # Ahead of `run_idempotent_dict`'s replay short-circuit — see
        # `routers/tasks.py::create_task` for why (DEC-0036).
        ensure_can_write(principal, "decision")

        async def _create() -> dict[str, Any]:
            decision = await decisions_service.create_decision(
                session,
                principal,
                DecisionCreate(
                    project_id=parsed_project_id,
                    task_id=parsed_task_id,
                    title=title,
                    body=body,
                    proposed_by_type="agent",
                    proposed_by_id=principal.user.id,
                ),
            )
            return _compact_decision(decision)

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {"project_id": project_id, "task_id": task_id, "title": title, "body": body},
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_add_decision", request_hash, _create
        )

    return await run_tool(ctx, _handler)


async def studio_accept_decision(ctx: Context, decision_id: str) -> dict[str, Any]:
    """Accept a recorded decision (`proposed` -> `accepted`). Requires an
    `admin` role — a non-admin caller gets `forbidden`. An unknown decision
    id answers `decision not found`; a decision that is not `proposed`
    answers `invalid_status_transition`."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(decision_id, "decision_id")
        if isinstance(parsed, dict):
            return parsed
        decision = await decisions_service.accept_decision(session, principal, parsed)
        return _compact_decision(decision)

    return await run_tool(ctx, _handler)


async def studio_supersede_decision(ctx: Context, decision_id: str) -> dict[str, Any]:
    """Mark a recorded decision as `superseded` (`proposed` or `accepted` ->
    `superseded`). Requires an `admin` role — a non-admin caller gets
    `forbidden`. An unknown decision id answers `decision not found`; an
    already `superseded` decision answers `invalid_status_transition`."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(decision_id, "decision_id")
        if isinstance(parsed, dict):
            return parsed
        decision = await decisions_service.supersede_decision(session, principal, parsed)
        return _compact_decision(decision)

    return await run_tool(ctx, _handler)
