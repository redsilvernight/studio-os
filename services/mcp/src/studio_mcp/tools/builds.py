from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.build import BuildModel, ProducerJobModel
from studio_api.services import github as github_service
from studio_api.services import idempotency as idempotency_service
from studio_api.services import producer as producer_service
from studio_api.services.authz import Principal
from studio_contracts.builds import BuildStatus, ProducerJobKind, ProducerJobRequest

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_build(build: BuildModel) -> dict[str, Any]:
    return {
        "id": str(build.id),
        "project_id": str(build.project_id),
        "task_id": str(build.task_id) if build.task_id else None,
        "workflow_run_id": build.workflow_run_id,
        "workflow_name": build.workflow_name,
        "run_number": build.run_number,
        "branch": build.branch,
        "commit_sha": build.commit_sha,
        "pr_number": build.pr_number,
        "status": build.status,
        "conclusion": build.conclusion,
        "html_url": build.html_url,
        "actor_login": build.actor_login,
    }


def _compact_producer_job(job: ProducerJobModel) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "project_id": str(job.project_id),
        "kind": job.kind,
        "status": job.status,
        "task_id": str(job.task_id) if job.task_id else None,
        "result": job.result,
        "error": job.error,
    }


async def studio_get_builds(
    ctx: Context,
    project_id: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List CI builds observed on wired GitHub repositories, newest first —
    read-only. Optional project_id (UUID string), status
    (queued/in_progress/succeeded/failed), limit."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        status_value: str | None = None
        if status is not None:
            try:
                status_value = BuildStatus(status).value
            except ValueError:
                return {
                    "error_code": "invalid_status",
                    "message": f"unknown build status {status!r}",
                }
        kwargs: dict[str, Any] = {"project_id": parsed_project_id}
        if status_value is not None:
            kwargs["status_value"] = status_value
        if limit is not None:
            kwargs["limit"] = limit
        builds = await github_service.list_builds(session, principal, **kwargs)
        return {"builds": [_compact_build(b) for b in builds]}

    return await run_tool(ctx, _handler)


async def studio_request_producer_job(
    project_id: str,
    kind: str,
    ctx: Context,
    task_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Run a bounded, synchronous Studio Producer analysis over one project's
    shared state: kind is priority_analysis, blocker_detection,
    parallelization or decomposition (task_id required for decomposition).
    Requires a writer role. The Producer never mutates tasks or claims — a
    decomposition result is a proposal the caller materializes via
    studio_create_task. Pass a caller-generated idempotency_key when this
    call might be retried — replaying the same key with the same arguments
    returns the original job instead of recomputing."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_project = parse_uuid(project_id, "project_id")
        if isinstance(parsed_project, dict):
            return parsed_project
        parsed_task_id: UUID | None = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task_id = parsed
        try:
            job_kind = ProducerJobKind(kind)
        except ValueError:
            return {"error_code": "invalid_kind", "message": f"unknown producer kind {kind!r}"}
        # Ahead of `run_idempotent_dict`'s replay short-circuit — see
        # `routers/tasks.py::create_task` for why (DEC-0036).
        producer_service.authorize_request(principal, parsed_project)

        async def _create() -> dict[str, Any]:
            job = await producer_service.request_producer_job(
                session,
                principal,
                ProducerJobRequest(
                    project_id=parsed_project, kind=job_kind, task_id=parsed_task_id
                ),
            )
            return _compact_producer_job(job)

        request_hash = idempotency_service.hash_request(
            json.dumps(
                {"project_id": project_id, "kind": kind, "task_id": task_id},
                sort_keys=True,
            ).encode()
        )
        return await idempotency_service.run_idempotent_dict(
            session, idempotency_key, "MCP studio_request_producer_job", request_hash, _create
        )

    return await run_tool(ctx, _handler)
