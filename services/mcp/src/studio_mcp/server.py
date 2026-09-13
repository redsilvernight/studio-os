from __future__ import annotations

import os
from typing import Literal, get_args

from mcp.server.mcpserver import MCPServer

from studio_mcp.tools.ai_work import studio_get_ai_work, studio_log_ai_work
from studio_mcp.tools.claims import (
    studio_claim_resource,
    studio_get_resource_claims,
    studio_release_resource,
)
from studio_mcp.tools.decisions import studio_add_decision, studio_get_decisions
from studio_mcp.tools.events import studio_emit_event, studio_get_recent_changes
from studio_mcp.tools.projects import studio_get_project_state, studio_get_projects
from studio_mcp.tools.sessions import studio_end_session, studio_get_sessions, studio_start_session
from studio_mcp.tools.tasks import (
    studio_claim_task,
    studio_create_task,
    studio_get_active_tasks,
    studio_get_task,
    studio_release_task,
    studio_update_task,
)
from studio_mcp.tools.teammates import studio_get_teammate_activity
from studio_mcp.tools.transfers import (
    studio_create_transfer_metadata,
    studio_get_transfer,
    studio_get_transfers,
    studio_request_transfer_download,
)

_Transport = Literal["stdio", "sse", "streamable-http"]


def create_server() -> MCPServer:
    server = MCPServer(name="studio-os")

    server.add_tool(
        studio_get_projects,
        name="studio_get_projects",
        description=(
            "List active Studio OS projects (id, slug, name) — use to discover "
            "which projects exist before targeting one."
        ),
    )
    server.add_tool(
        studio_get_project_state,
        name="studio_get_project_state",
        description=(
            "Get a project's active tasks and active resource claims by project_id "
            "(UUID string) — the bootstrap read before starting work on a project."
        ),
    )
    server.add_tool(
        studio_get_task,
        name="studio_get_task",
        description="Get one task by task_id (UUID string).",
    )
    server.add_tool(
        studio_get_active_tasks,
        name="studio_get_active_tasks",
        description=(
            "List active (created/in_progress/blocked) tasks for a project_id (UUID string)."
        ),
    )
    server.add_tool(
        studio_create_task,
        name="studio_create_task",
        description=(
            "Create a task on a project (project_id UUID string, title, optional description). "
            "Pass idempotency_key when retrying a call that may have already succeeded — "
            "replaying the same key+arguments returns the original task instead of a duplicate."
        ),
    )
    server.add_tool(
        studio_update_task,
        name="studio_update_task",
        description=(
            "Update a task's title/description/status. expected_version must match "
            "the task's current version (optimistic concurrency) or the call fails "
            "with version_conflict."
        ),
    )
    server.add_tool(
        studio_claim_task,
        name="studio_claim_task",
        description=(
            "Claim a task for the caller's machine (soft lock, sets status to "
            "in_progress). Fails with already_claimed if another machine holds it."
        ),
    )
    server.add_tool(
        studio_release_task,
        name="studio_release_task",
        description="Release a task's claim by task_id (UUID string).",
    )
    server.add_tool(
        studio_get_resource_claims,
        name="studio_get_resource_claims",
        description="List resource claims for a project_id (UUID string), any status.",
    )
    server.add_tool(
        studio_claim_resource,
        name="studio_claim_resource",
        description=(
            "Soft-lock a resource path (file/folder) for the caller's machine. Never "
            "blocks a Git operation or file write — a conflicting active claim is "
            "surfaced via a resource.conflict event, not a rejection. Pass "
            "idempotency_key when retrying a call that may have already succeeded — "
            "replaying the same key+arguments returns the original claim instead of a "
            "duplicate and never re-emits the conflict event."
        ),
    )
    server.add_tool(
        studio_release_resource,
        name="studio_release_resource",
        description="Release a resource claim by claim_id (UUID string).",
    )
    server.add_tool(
        studio_get_decisions,
        name="studio_get_decisions",
        description="List Decisions (DEC-XXXX), optionally filtered by project_id (UUID string).",
    )
    server.add_tool(
        studio_add_decision,
        name="studio_add_decision",
        description=(
            "Record a Decision (DEC-XXXX) with a title and body. The proposer "
            "identity is derived from the caller's authenticated machine. Pass "
            "idempotency_key when retrying a call that may have already succeeded — "
            "replaying the same key+arguments returns the original Decision instead "
            "of allocating a second DEC-XXXX id."
        ),
    )
    server.add_tool(
        studio_get_recent_changes,
        name="studio_get_recent_changes",
        description=(
            "List recent Studio OS events, optionally filtered by project_id, "
            "task_id, and since (ISO-8601 timestamp)."
        ),
    )
    server.add_tool(
        studio_get_sessions,
        name="studio_get_sessions",
        description="List work sessions, optionally filtered by task_id (UUID string).",
    )
    server.add_tool(
        studio_get_teammate_activity,
        name="studio_get_teammate_activity",
        description=(
            "List the machines currently active on a project (via its active tasks "
            "and resource claims), each with a heartbeat-derived online/idle/offline "
            "status."
        ),
    )
    server.add_tool(
        studio_start_session,
        name="studio_start_session",
        description=(
            "Start a work session on a task for the caller's machine. Pass "
            "idempotency_key when retrying a call that may have already succeeded — "
            "replaying the same key+arguments returns the original session instead "
            "of starting a duplicate."
        ),
    )
    server.add_tool(
        studio_end_session,
        name="studio_end_session",
        description="End a work session by session_id (UUID string).",
    )
    server.add_tool(
        studio_log_ai_work,
        name="studio_log_ai_work",
        description=(
            "Log AI work: creates a new AI Work Ledger entry when ai_work_id is "
            "omitted, or updates the existing entry (status/changed_files/tests_run) "
            "when given."
        ),
    )
    server.add_tool(
        studio_get_ai_work,
        name="studio_get_ai_work",
        description=(
            "List AI Work Ledger entries, optionally filtered by project_id/task_id (UUID strings)."
        ),
    )
    server.add_tool(
        studio_emit_event,
        name="studio_emit_event",
        description=(
            "Emit a Studio OS event (task/session/claim/decision/ai_work/... lifecycle) "
            "so other agents and the dashboard see it. event_type must match "
            "TECH/03_EVENT_CONTRACT.md (e.g. 'task.started'). Pass a stable event_id "
            "(UUID string) when this call might be retried — replaying the same "
            "event_id returns the original stored event instead of a duplicate."
        ),
    )
    server.add_tool(
        studio_create_transfer_metadata,
        name="studio_create_transfer_metadata",
        description=(
            "Create a Studio Transfer record and return metadata plus a pre-signed "
            "upload URL — never the file bytes. The client uploads directly to "
            "MinIO/S3 with the returned URL. content_md5 (base64 RFC 1864) is "
            "required for a small file (single-PUT path) or the call fails with "
            "missing_content_md5."
        ),
    )
    server.add_tool(
        studio_get_transfers,
        name="studio_get_transfers",
        description=(
            "List transfers (metadata only), optionally filtered by project_id (UUID string)."
        ),
    )
    server.add_tool(
        studio_get_transfer,
        name="studio_get_transfer",
        description="Get one transfer's metadata by transfer_id (UUID string).",
    )
    server.add_tool(
        studio_request_transfer_download,
        name="studio_request_transfer_download",
        description=(
            "Get a short-lived pre-signed download URL for a transfer_id (UUID "
            "string) — never the file bytes."
        ),
    )
    return server


mcp = create_server()


if __name__ == "__main__":
    # Local/dev default: stdio. Docker/Caddy deployment (mcp.example.com,
    # TECH/01_ARCHITECTURE.md) overrides via STUDIO_MCP_TRANSPORT=streamable-http.
    _raw_transport = os.environ.get("STUDIO_MCP_TRANSPORT", "stdio")
    if _raw_transport not in get_args(_Transport):
        raise ValueError(f"invalid STUDIO_MCP_TRANSPORT: {_raw_transport!r}")

    if _raw_transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # 0.0.0.0: must be reachable from Caddy in another container, not just
        # loopback. Port 8100 kept distinct from the api service's 8000 —
        # matches docker/docker-compose.yml and docker/Caddyfile.
        host = os.environ.get("STUDIO_MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("STUDIO_MCP_PORT", "8100"))
        mcp.run(transport=_raw_transport, host=host, port=port)  # type: ignore[call-overload]
