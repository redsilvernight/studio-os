from __future__ import annotations

import os
from typing import Literal, get_args

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from studio_mcp.tools.ai_library import (
    studio_configure_runtime,
    studio_discover_definitions,
    studio_publish_definition,
    studio_register_runtime,
    studio_resolve_agent,
)
from studio_mcp.tools.ai_work import studio_get_ai_work, studio_log_ai_work
from studio_mcp.tools.builds import studio_get_builds, studio_request_producer_job
from studio_mcp.tools.claims import (
    studio_claim_resource,
    studio_get_resource_claims,
    studio_release_resource,
)
from studio_mcp.tools.context import studio_prepare_context
from studio_mcp.tools.decisions import (
    studio_accept_decision,
    studio_add_decision,
    studio_get_decisions,
    studio_supersede_decision,
)
from studio_mcp.tools.events import studio_emit_event, studio_get_recent_changes
from studio_mcp.tools.initialization import (
    studio_apply_project_initialization,
    studio_preview_project_initialization,
)
from studio_mcp.tools.projects import studio_get_project_state, studio_get_projects
from studio_mcp.tools.review_queue import studio_get_review_queue
from studio_mcp.tools.roadmaps import (
    studio_apply_roadmap_hydration,
    studio_get_roadmap,
    studio_preview_roadmap_hydration,
    studio_propose_roadmap,
    studio_update_roadmap_step,
)
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
from studio_mcp.tools.timeline import studio_get_timeline
from studio_mcp.tools.transfers import (
    studio_create_transfer_metadata,
    studio_get_transfer,
    studio_get_transfers,
    studio_request_transfer_download,
)

_Transport = Literal["stdio", "sse", "streamable-http"]

_READ_ONLY = ToolAnnotations(read_only_hint=True)
_IDEMPOTENT_WRITE = ToolAnnotations(idempotent_hint=True)


def create_server() -> MCPServer:
    server = MCPServer(name="studio-os")

    server.add_tool(
        studio_get_projects,
        name="studio_get_projects",
        description=(
            "List active projects (id, slug, name) — read-only. Use to discover "
            "which projects exist before targeting one. Any authenticated caller may read."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_get_project_state,
        name="studio_get_project_state",
        description=(
            "Get a project's active tasks and active resource claims by project_id "
            "(UUID string) — read-only. The bootstrap read before starting work on a project."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_prepare_context,
        name="studio_prepare_context",
        description=(
            "Recommended first call to prime an agent on a project: returns, in ONE bounded "
            "read-only response, the project, the requested task (optional task_id), related "
            "active tasks, decisions, rules, skills and the active claims that matter for the "
            "stated objective. Required: project_id (UUID string) and objective (free text, "
            "1..1000 characters). Optional: task_id (UUID string, must belong to the project, "
            "otherwise not_found), files (up to 20 paths; claims held by other machines that "
            "overlap them are reported), limit (items per kind, 1..20, default 5) and max_chars "
            "(budget for free text, 1000..50000, default 12000). Selection is deterministic and "
            "explained: every item carries why (a structural link, or exact word overlap with "
            "the objective listed in matched_terms) — no semantic search is involved. The "
            "response states what was returned and what else exists but was left out "
            "(additional_available, omitted_for_budget); use the dedicated read tools for those. "
            "Long texts are cut and flagged truncated. Same visibility as the individual read "
            "tools: another user's private library definitions are never included."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_get_task,
        name="studio_get_task",
        description=(
            "Get one task by task_id (UUID string) — read-only. Unknown ids fail with not_found."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_get_active_tasks,
        name="studio_get_active_tasks",
        description=(
            "List active (created/in_progress/blocked) tasks for a project_id (UUID string) — "
            "read-only."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_create_task,
        name="studio_create_task",
        description=(
            "Create a task on a project (project_id UUID string, title, optional description). "
            "Requires a writer role (read-only callers fail with forbidden). "
            "Pass idempotency_key when retrying a call that may have already succeeded — "
            "replaying the same key+arguments returns the original task instead of a duplicate; "
            "the same key with different arguments fails with idempotency_key_payload_mismatch."
        ),
    )
    server.add_tool(
        studio_update_task,
        name="studio_update_task",
        description=(
            "Update a task's title/description/status. Requires a writer role. "
            "expected_version must match the task's current version (read it first): "
            "a stale version fails with version_conflict carrying the live server version — "
            "re-read, merge, retry. Updates never overwrite silently."
        ),
    )
    server.add_tool(
        studio_claim_task,
        name="studio_claim_task",
        description=(
            "Claim a task for the caller's machine (soft lock, sets status to "
            "in_progress). Requires a writer role. Fails with already_claimed if another "
            "machine holds it."
        ),
    )
    server.add_tool(
        studio_release_task,
        name="studio_release_task",
        description=(
            "Release a task's claim by task_id (UUID string). Only the holding machine (or a "
            "privileged role) may release; anyone else fails with forbidden. Safe to repeat — "
            "never creates anything."
        ),
        annotations=_IDEMPOTENT_WRITE,
    )
    server.add_tool(
        studio_get_resource_claims,
        name="studio_get_resource_claims",
        description=(
            "List resource claims for a project_id (UUID string), any status — read-only."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_claim_resource,
        name="studio_claim_resource",
        description=(
            "Soft-lock a resource path (file/folder) for the caller's machine. Requires a writer "
            "role. Claims warn, they never block: a conflicting active claim is surfaced via a "
            "resource.conflict event, not a rejection, and no Git operation or file write is ever "
            "refused. "
            "Pass idempotency_key when retrying a call that may have already succeeded — "
            "replaying the same key+arguments returns the original claim instead of a "
            "duplicate and never re-emits the conflict event."
        ),
    )
    server.add_tool(
        studio_release_resource,
        name="studio_release_resource",
        description=(
            "Release a resource claim by claim_id (UUID string). Only the holding machine (or a "
            "privileged role) may release; anyone else fails with forbidden. Safe to repeat — "
            "never creates anything."
        ),
        annotations=_IDEMPOTENT_WRITE,
    )
    server.add_tool(
        studio_get_decisions,
        name="studio_get_decisions",
        description=(
            "List recorded decisions (stable human-readable ids), optionally filtered by "
            "project_id (UUID string) — read-only."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_add_decision,
        name="studio_add_decision",
        description=(
            "Record a decision with a title and body. Requires a writer role; the proposer "
            "identity is derived from the caller's authenticated machine. Pass "
            "idempotency_key when retrying a call that may have already succeeded — "
            "replaying the same key+arguments returns the original decision instead of a "
            "duplicate (no second id is allocated)."
        ),
    )
    server.add_tool(
        studio_accept_decision,
        name="studio_accept_decision",
        description=(
            "Accept a proposed Decision (proposed -> accepted). Admin role only. Not a "
            "creation: no idempotency_key — retrying an already-accepted decision fails "
            "with invalid_decision_transition."
        ),
    )
    server.add_tool(
        studio_supersede_decision,
        name="studio_supersede_decision",
        description=(
            "Supersede a Decision (proposed or accepted -> superseded, terminal). Admin "
            "role only. Not a creation: no idempotency_key."
        ),
    )
    server.add_tool(
        studio_get_recent_changes,
        name="studio_get_recent_changes",
        description=(
            "List recent events, optionally filtered by project_id, task_id, and since (ISO-8601 "
            "timestamp) — read-only. This is the polling channel; for live push use the HTTP event "
            "stream (GET /api/v1/events/stream)."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_get_sessions,
        name="studio_get_sessions",
        description="List work sessions, optionally filtered by task_id (UUID string) — read-only.",
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_get_teammate_activity,
        name="studio_get_teammate_activity",
        description=(
            "List the machines currently active on a project (via its active tasks "
            "and resource claims), each with a heartbeat-derived online/idle/offline "
            "status — read-only."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_start_session,
        name="studio_start_session",
        description=(
            "Start a work session on a task for the caller's machine. Requires a writer role. Pass "
            "idempotency_key when retrying a call that may have already succeeded — "
            "replaying the same key+arguments returns the original session instead "
            "of starting a duplicate."
        ),
    )
    server.add_tool(
        studio_end_session,
        name="studio_end_session",
        description=(
            "End a work session by session_id (UUID string). Only the machine that started it "
            "(or a privileged role) may end it; anyone else fails with forbidden. Safe to repeat."
        ),
        annotations=_IDEMPOTENT_WRITE,
    )
    server.add_tool(
        studio_log_ai_work,
        name="studio_log_ai_work",
        description=(
            "Log AI work: creates a new work ledger entry when ai_work_id is "
            "omitted, or updates the existing entry (status/changed_files/tests_run) "
            "when given. Requires a writer role. New entries must reference an agent attached to "
            "the caller's own machine — register one first over HTTP (POST /api/v1/agents), "
            "since agent registration is HTTP-only; a foreign or unknown agent fails with "
            "actor_not_owned. Updating is limited to the owning machine's entries, and resolving "
            "a review (approved / changes requested) additionally requires a privileged role."
        ),
    )
    server.add_tool(
        studio_get_ai_work,
        name="studio_get_ai_work",
        description=(
            "List AI work ledger entries, optionally filtered by project_id/task_id (UUID "
            "strings) — read-only."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_get_builds,
        name="studio_get_builds",
        description=(
            "List CI builds observed on wired GitHub repositories, newest first — "
            "read-only. Optional project_id (UUID string), status "
            "(queued/in_progress/succeeded/failed), limit."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_request_producer_job,
        name="studio_request_producer_job",
        description=(
            "Run a bounded, synchronous Studio Producer analysis over one project's "
            "shared state: kind is priority_analysis, blocker_detection, "
            "parallelization or decomposition (task_id UUID string required for "
            "decomposition). Requires a writer role. The Producer never mutates tasks "
            "or claims — a decomposition result is a proposal the caller materializes "
            "via studio_create_task. Pass idempotency_key when retrying a call that "
            "may have already succeeded — replaying the same key+arguments returns "
            "the original job instead of recomputing."
        ),
    )
    server.add_tool(
        studio_get_review_queue,
        name="studio_get_review_queue",
        description=(
            "Aggregated view of everything waiting on a human decision: AI work in "
            "review_requested (resolve via studio_log_ai_work), decisions still proposed "
            "(informational — no transition tool exists for decisions), and recent "
            "resource.conflict events within conflict_window_hours (default 24, best-effort "
            "and time-windowed — no persisted conflict state exists). Also serves as the "
            "notifications surface — there is no separate notifications tool. "
            "Read-only."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_get_roadmap,
        name="studio_get_roadmap",
        description=(
            "Read a project's roadmap synthesis and current position: roadmap "
            "summaries (id, title, status, progress, current step) and, for the active "
            "roadmap, the current step plus the next available steps — read-only. Required "
            "project_id (UUID string); optional status filter, limit (1..100, default 20) and "
            "max_chars budget for free text. A project with no roadmap returns an empty list "
            "and a null active position: that is a normal state, never an error. Any "
            "authenticated caller may read."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_propose_roadmap,
        name="studio_propose_roadmap",
        description=(
            "Propose a structured roadmap plan for a project (project_id UUID string and a "
            "document in the neutral plan format: title, optional objective/context, phases of "
            "steps with optional dependencies and planned tasks). Requires a writer role. "
            "submit=true (default) freezes it as proposed for human validation; submit=false "
            "keeps it a draft. This never creates Tasks and never activates the roadmap — "
            "approval and activation stay human. Pass idempotency_key when retrying a call "
            "that may have already succeeded: replaying the same key and arguments returns the "
            "original roadmap instead of a duplicate."
        ),
    )
    server.add_tool(
        studio_preview_roadmap_hydration,
        name="studio_preview_roadmap_hydration",
        description=(
            "Preview the Tasks a roadmap hydration would create, reuse or skip for a "
            "roadmap_id (UUID string) — read-only, writes nothing. Optional step_keys restricts "
            "the preview to specific step keys; limit bounds the returned items. Works on any "
            "non-archived roadmap; a non-active roadmap answers applicable=false with a reason."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_apply_roadmap_hydration,
        name="studio_apply_roadmap_hydration",
        description=(
            "Apply roadmap hydration for a roadmap_id (UUID string): create the missing Tasks, "
            "reuse the already linked ones and skip done/skipped steps. Requires a writer role "
            "and an active roadmap. expected_version must match the version read at preview; a "
            "stale version fails with version_conflict. Pass idempotency_key when retrying a "
            "call that may have already succeeded: replaying the same key returns the original "
            "result, and replaying with another key still reuses existing links, so no Task is "
            "ever duplicated. An existing Task is never modified or deleted."
        ),
    )
    server.add_tool(
        studio_update_roadmap_step,
        name="studio_update_roadmap_step",
        description=(
            "Push bounded step progress on a roadmap (roadmap_id and step_key). Requires a "
            "writer role. Optional state_override (done or skipped), clear_state_override, "
            "state_override_reason, notes and criteria_checked (indices into the step's "
            "acceptance criteria). Progress-type updates are applied directly, even when the "
            "caller is an agent, because they never change the plan's structure or content."
        ),
    )
    server.add_tool(
        studio_preview_project_initialization,
        name="studio_preview_project_initialization",
        description=(
            "Validate a project-initialization plan and show exactly what would be created, "
            "reused or skipped — read-only, no side effect. The plan describes the project "
            "(slug, name), an optional roadmap, a task plan, Library resources to pin and "
            "generic runtime bindings. A missing roadmap, an empty section and a missing "
            "optional Library resource are all valid: they are reported, never treated as "
            "errors."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_apply_project_initialization,
        name="studio_apply_project_initialization",
        description=(
            "Apply a project-initialization plan. Requires a writer role; creating a new "
            "project additionally requires admin or developer (an agent-only caller fails with "
            "forbidden unless the project already exists). Any blocking problem refuses before "
            "writing anything. Replaying is safe: the same idempotency_key returns the original "
            "summary, and a replay without a key still reuses the existing project, tasks, "
            "roadmap and bindings instead of creating a duplicate."
        ),
    )
    server.add_tool(
        studio_get_timeline,
        name="studio_get_timeline",
        description=(
            "Day-grouped project activity (project_id UUID string, newest day first), "
            "unfiltered — full history, not an actionable signal (use "
            "studio_get_review_queue for what needs action). Optional since (ISO-8601 "
            "timestamp) and limit. Read-only."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_emit_event,
        name="studio_emit_event",
        description=(
            "Publish a project event (task/session/claim/decision/ai_work lifecycle) "
            "so other consumers see it. Requires a writer role. event_type uses dotted names "
            "such as task.created, task.started, task.updated or session.ended; unknown types "
            "fail with invalid_event_type. Identity is validated against the caller's "
            "authenticated machine: omit machine_id (derived automatically), use actor_type user "
            "with the machine "
            "owner's user id, agent with an agent attached to the caller's own machine, or system "
            "with the machine's own id — anything else fails with machine_id_mismatch, "
            "actor_id_mismatch or actor_not_owned. No agent identity is needed: user and system "
            "actors are fully supported. Pass a stable event_id (UUID string) when this call might "
            "be retried — replaying the same event_id returns the original stored event instead "
            "of a duplicate."
        ),
    )
    server.add_tool(
        studio_create_transfer_metadata,
        name="studio_create_transfer_metadata",
        description=(
            "Create a transfer record and return metadata plus a pre-signed "
            "upload URL — never the file bytes. Requires a writer role. The client uploads "
            "directly to object storage with the returned URL. content_md5 (base64) is "
            "required for a small file (single-upload path) or the call fails with "
            "missing_content_md5. Oversize files fail with transfer_too_large and exhausted quotas "
            "with quota_exceeded. The full cycle (multipart upload, resume, completion, deletion) "
            "lives on the HTTP API (/api/v1/transfers); this tool only starts it."
        ),
    )
    server.add_tool(
        studio_get_transfers,
        name="studio_get_transfers",
        description=(
            "List transfers visible to the caller (metadata only), optionally filtered by "
            "project_id (UUID string) — read-only. Inaccessible transfers are silently omitted."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_get_transfer,
        name="studio_get_transfer",
        description=(
            "Get one transfer's metadata by transfer_id (UUID string) — read-only. Only the "
            "sender, the recipient, broadcast recipients, or a privileged role may read it; "
            "anyone else fails with forbidden."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_request_transfer_download,
        name="studio_request_transfer_download",
        description=(
            "Get a short-lived pre-signed download URL for a transfer_id (UUID "
            "string) — never the file bytes. Same visibility rule as reading the transfer; "
            "outsiders fail with forbidden. Download with HTTP Range to resume a partial fetch."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_resolve_agent,
        name="studio_resolve_agent",
        description=(
            "Resolve one agent definition (stable_key string, optional project_id UUID string) "
            "into its full structured result: effective definition version, rules, skills, "
            "model profile, capability requirements, winning runtime, compatibility verdict "
            "and provenance — read-only. Same result as POST /api/v1/resolutions. Optional "
            "ephemeral session_overrides (validated like stored choices, winning per stored "
            "precedence, never persisted). A selected-but-incompatible runtime fails with "
            "runtime_incompatible — no fallback to another runtime. Unknown or invisible "
            "definitions fail with definition_not_found."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_discover_definitions,
        name="studio_discover_definitions",
        description=(
            "Discover and read AI library definitions (rules, skills, agent definitions, "
            "model profiles, workflows) without knowing UUIDs — read-only. Filter the list "
            "by kind/scope/project_id, or fetch one definition by resource_id (UUID string) "
            "or by kind plus stable_key, with optional include_versions. Another user's "
            "private definitions are silently omitted and fail with definition_not_found, "
            "never forbidden."
        ),
        annotations=_READ_ONLY,
    )
    server.add_tool(
        studio_publish_definition,
        name="studio_publish_definition",
        description=(
            "Publish a library change over the definition lifecycle. Requires a writer role "
            "(read-only callers fail with forbidden). Actions: create a new definition "
            "(kind/stable_key/scope/title, optional project/content/links), draft a new "
            "version, move the active pointer (activate with version plus "
            "expected_resource_version — a stale version fails with version_conflict), or "
            "deprecate. Creation and activation stay two distinct steps. Pass "
            "idempotency_key when retrying a call that may have already succeeded — "
            "replaying the same key and arguments returns the original result instead of a "
            "duplicate; the same key with different arguments fails with "
            "idempotency_key_payload_mismatch."
        ),
    )
    server.add_tool(
        studio_configure_runtime,
        name="studio_configure_runtime",
        description=(
            "Set or clear the runtime choice for one logical (kind, stable_key) definition "
            "key. Requires a writer role (read-only callers fail with forbidden). Levels "
            "user, project_override, project_default and studio_default persist; session "
            "is ephemeral and rejected here — pass it to studio_resolve_agent instead. "
            "Set stores an open runtime target (concrete machine, harness/provider/model "
            "refs, capabilities) and accepts idempotency_key for safe retries (replaying "
            "the same key and arguments returns the original binding instead of a "
            "duplicate; key reuse with different arguments fails with "
            "idempotency_key_payload_mismatch). Clear removes the stored choice and fails "
            "with not_found when nothing is stored."
        ),
    )
    server.add_tool(
        studio_register_runtime,
        name="studio_register_runtime",
        description=(
            "Register or maintain a runtime description for the caller's own execution "
            "target. Requires a writer role. Any provider or harness is an ordinary "
            "runtime described with open harness/provider/model refs plus declared "
            "capabilities — no special cases. Actions: register a new runtime, update its "
            "descriptors under expected_version (a stale version fails with "
            "version_conflict), or revoke it (logical, repeatable, keeps history readable). "
            "Register and update accept idempotency_key for safe retries (replaying the "
            "same key and arguments returns the original runtime instead of a duplicate)."
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
