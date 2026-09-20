"""Roadmap MCP tools (Roadmaps P4, DEC-0084/DEC-0086).

Five intention-sized tools — not one per HTTP route (DEC-0046): read the plan
and the current position, propose a structured plan, preview then apply Task
hydration, and push bounded step progress. No tool activates, approves, rejects
or archives a roadmap: those are human (provision) transitions, and an agent
cannot reach them from this surface.

Every tool is a thin layer over the same P3 service functions the HTTP routes
use. The concrete interface expected from `studio_api.services.roadmaps` is
documented in DEC-0086; it is imported lazily so this surface builds and is
tested against the frozen P1 contracts before P3 lands.

Absence of a Roadmap is a normal project state: `studio_get_roadmap` answers
with an empty list and a null active position, never an error.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.services import idempotency as idempotency_service
from studio_api.services.authz import Principal, ensure_can_write
from studio_api.services.roadmap_port import RoadmapServicePort
from studio_contracts.roadmaps import (
    HydrationApplyRequest,
    HydrationItem,
    HydrationRequest,
    HydrationResult,
    Roadmap,
    RoadmapDocument,
    RoadmapErrorCode,
    RoadmapImport,
    RoadmapOrigin,
    RoadmapStatus,
    RoadmapSummary,
    RoadmapValidationReason,
    Step,
    StepProgressUpdate,
    StepState,
    StepStateOverride,
    WriteProvenance,
    roadmap_document_errors,
)

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DEFAULT_MAX_CHARS = 4000
MIN_MAX_CHARS = 500
MAX_MAX_CHARS = 20000
MAX_UPCOMING_STEPS = 5


def _roadmaps() -> RoadmapServicePort:
    """The P3 Roadmap service, imported lazily (see module docstring). The
    import is coerced to the typed port so this call site is checked against
    the frozen interface (DEC-0086)."""
    from importlib import import_module

    return cast(RoadmapServicePort, import_module("studio_api.services.roadmaps"))


def _bounded(value: str | None, max_chars: int) -> tuple[str | None, bool]:
    if value is None or len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def _error(code: RoadmapErrorCode, message: str, **extra: object) -> dict[str, Any]:
    return {"error_code": code.value, "message": message, **extra}


def _compact_summary(summary: RoadmapSummary, max_chars: int) -> dict[str, Any]:
    title, truncated = _bounded(summary.title, max_chars)
    return {
        "id": str(summary.id),
        "title": title,
        "status": summary.status.value,
        "revision_no": summary.revision_no,
        "approved_revision_no": summary.approved_revision_no,
        "current_step_key": summary.current_step_key,
        "progress": summary.progress.model_dump(mode="json"),
        "truncated": truncated,
    }


def _current_position(roadmap: Roadmap, max_chars: int) -> dict[str, Any]:
    steps = [step for phase in roadmap.phases for step in phase.steps]
    current_key = roadmap.current_step_key
    current = next((step for step in steps if step.key == current_key), None)
    current_phase = next(
        (
            phase.key
            for phase in roadmap.phases
            if current is not None and any(step.key == current.key for step in phase.steps)
        ),
        None,
    )
    upcoming = [step for step in steps if step.available and step.key != current_key]
    return {
        "roadmap_id": str(roadmap.id),
        "title": roadmap.title,
        "status": roadmap.status.value,
        "progress": roadmap.progress.model_dump(mode="json"),
        "current_phase_key": current_phase,
        "current_step_key": current_key,
        "current_step": _compact_step(current, max_chars) if current is not None else None,
        "upcoming_steps": [
            _compact_step(step, max_chars) for step in upcoming[:MAX_UPCOMING_STEPS]
        ],
        "blocking": sorted(
            {
                dependency
                for step in steps
                for dependency in step.waiting_on
                if step.state not in (StepState.DONE, StepState.SKIPPED)
            }
        ),
    }


def _compact_step(step: Step, max_chars: int) -> dict[str, Any]:
    title, truncated = _bounded(step.title, max_chars)
    objective, objective_truncated = _bounded(step.objective, max_chars)
    return {
        "key": step.key,
        "title": title,
        "state": step.state.value,
        "available": step.available,
        "waiting_on": step.waiting_on,
        "acceptance_criteria": [
            criteria[0]
            for criteria in (_bounded(item, max_chars) for item in step.acceptance_criteria)
            if criteria[0] is not None
        ],
        "objective": objective,
        "linked_task_ids": [str(task.task_id) for task in step.linked_tasks],
        "truncated": truncated or objective_truncated,
    }


def _compact_hydration(result: HydrationResult, limit: int) -> dict[str, Any]:
    body = result.model_dump(mode="json")
    items = list(result.items)
    body["items"] = [_compact_hydration_item(item) for item in items[:limit]]
    body["omitted_for_budget"] = max(0, len(items) - limit)
    return body


def _compact_hydration_item(item: HydrationItem) -> dict[str, Any]:
    return {
        "step_key": item.step_key,
        "hydration_key": item.hydration_key,
        "action": item.action.value,
        "title": item.title,
        "task_id": str(item.task_id) if item.task_id is not None else None,
        "reason": item.reason.value if item.reason is not None else None,
    }


async def studio_get_roadmap(
    project_id: str,
    ctx: Context,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Read a project's roadmap summary and the current phase/step position.
    Absence of a roadmap is a normal state, not an error."""

    async def _handler(session: AsyncSession, _principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(project_id, "project_id")
        if isinstance(parsed, dict):
            return parsed
        parsed_status: RoadmapStatus | None = None
        if status is not None:
            try:
                parsed_status = RoadmapStatus(status)
            except ValueError:
                return {"error_code": "invalid_argument", "message": f"unknown status: {status!r}"}
        bounded_limit = max(1, min(limit, MAX_LIMIT))
        bounded_chars = max(MIN_MAX_CHARS, min(max_chars, MAX_MAX_CHARS))
        summaries = await _roadmaps().list_roadmaps(session, parsed, parsed_status)
        roadmaps = [
            _compact_summary(summary, bounded_chars) for summary in summaries[:bounded_limit]
        ]
        active_summary = next(
            (summary for summary in summaries if summary.status is RoadmapStatus.ACTIVE), None
        )
        active = None
        if active_summary is not None:
            detail = await _roadmaps().get_roadmap(session, active_summary.id)
            if detail is not None:
                active = _current_position(detail, bounded_chars)
        drafts = sum(
            1 for s in summaries if s.status in (RoadmapStatus.DRAFT, RoadmapStatus.PROPOSED)
        )
        return {
            "project_id": project_id,
            "roadmaps": roadmaps,
            "active": active,
            "draft_pending": drafts,
            "omitted_for_budget": max(0, len(summaries) - bounded_limit),
        }

    return await run_tool(ctx, _handler)


async def studio_propose_roadmap(
    project_id: str,
    document: RoadmapDocument,
    ctx: Context,
    submit: bool = True,
    idempotency_key: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Propose a structured roadmap plan (draft, or `proposed` for human
    validation when `submit` is true). Never creates Tasks and never activates
    the roadmap."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(project_id, "project_id")
        if isinstance(parsed, dict):
            return parsed
        errors = roadmap_document_errors(document)
        if errors:
            return {
                "error_code": RoadmapErrorCode.INVALID_ROADMAP.value,
                "reason": errors[0].get("reason", RoadmapValidationReason.LIMIT_EXCEEDED.value),
                "field": errors[0].get("field"),
            }
        parsed_agent: UUID | None = None
        if agent_id is not None:
            candidate = parse_uuid(agent_id, "agent_id")
            if isinstance(candidate, dict):
                return candidate
            parsed_agent = candidate
        ensure_can_write(principal, "roadmap")
        provenance = WriteProvenance(origin=RoadmapOrigin.AI_PROPOSAL, agent_id=parsed_agent)
        request = RoadmapImport(
            project_id=parsed, document=document, submit=submit, provenance=provenance
        )

        async def _create() -> dict[str, Any]:
            roadmap = await _roadmaps().import_roadmap(session, principal, request)
            return _compact_summary(roadmap, DEFAULT_MAX_CHARS)

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {
                    "project_id": project_id,
                    "submit": submit,
                    "agent_id": agent_id,
                    "document": document.model_dump(mode="json"),
                },
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_propose_roadmap", request_hash, _create
        )

    return await run_tool(ctx, _handler)


async def studio_preview_roadmap_hydration(
    roadmap_id: str, ctx: Context, step_keys: list[str] | None = None, limit: int = 50
) -> dict[str, Any]:
    """Preview the Tasks a roadmap would create/reuse/skip — read-only, writes
    nothing, works on any non-archived status."""

    async def _handler(session: AsyncSession, _principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(roadmap_id, "roadmap_id")
        if isinstance(parsed, dict):
            return parsed
        request = HydrationRequest(step_keys=step_keys)
        result = await _roadmaps().preview_hydration(session, parsed, request)
        return _compact_hydration(result, max(1, min(limit, MAX_LIMIT)))

    return await run_tool(ctx, _handler)


async def studio_apply_roadmap_hydration(
    roadmap_id: str,
    expected_version: int,
    ctx: Context,
    step_keys: list[str] | None = None,
    idempotency_key: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Apply roadmap hydration: create the missing Tasks, reuse the linked
    ones, skip done/skipped steps. Requires an active roadmap and the version
    read at preview; replaying with another key still reuses by hydration key,
    so it never duplicates."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(roadmap_id, "roadmap_id")
        if isinstance(parsed, dict):
            return parsed
        ensure_can_write(principal, "roadmap")
        request = HydrationApplyRequest(step_keys=step_keys, expected_version=expected_version)

        async def _apply() -> dict[str, Any]:
            result = await _roadmaps().apply_hydration(session, principal, parsed, request)
            return _compact_hydration(result, max(1, min(limit, MAX_LIMIT)))

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {
                    "roadmap_id": roadmap_id,
                    "step_keys": step_keys,
                    "expected_version": expected_version,
                },
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_apply_roadmap_hydration", request_hash, _apply
        )

    return await run_tool(ctx, _handler)


async def studio_update_roadmap_step(
    roadmap_id: str,
    step_key: str,
    ctx: Context,
    state_override: str | None = None,
    clear_state_override: bool = False,
    state_override_reason: str | None = None,
    notes: str | None = None,
    criteria_checked: list[int] | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Push bounded step progress (manual override, notes, checked criteria)
    on a roadmap. Progress-type writes are applied directly, even for an agent:
    they never change the plan's structure."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(roadmap_id, "roadmap_id")
        if isinstance(parsed, dict):
            return parsed
        override: StepStateOverride | None = None
        if state_override is not None:
            try:
                override = StepStateOverride(state_override)
            except ValueError:
                return {
                    "error_code": "invalid_argument",
                    "message": f"unknown state_override: {state_override!r}",
                }
        parsed_agent: UUID | None = None
        if agent_id is not None:
            candidate = parse_uuid(agent_id, "agent_id")
            if isinstance(candidate, dict):
                return candidate
            parsed_agent = candidate
        ensure_can_write(principal, "roadmap")
        progress = StepProgressUpdate(
            state_override=override,
            clear_state_override=clear_state_override,
            state_override_reason=state_override_reason,
            notes=notes,
            criteria_checked=criteria_checked,
            provenance=WriteProvenance(agent_id=parsed_agent),
        )
        step = await _roadmaps().update_step_progress(
            session, principal, parsed, step_key, progress
        )
        return _compact_step(step, DEFAULT_MAX_CHARS)

    return await run_tool(ctx, _handler)
