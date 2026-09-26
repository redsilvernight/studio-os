"""Fail-closed access registry of every MCP tool (DEC-0103 §12).

Same classes as `studio_api.access_registry.AccessClass`. Every tool
registered by `create_server()` must appear here;
`tests/mcp/test_access_registry.py` fails on a missing or stale entry and
generates the outsider matrix from the `project` entries. Documentation and
test input only — authorization stays in the shared services (DEC-0046 §4).
"""

from __future__ import annotations

from collections.abc import Mapping

from studio_api.access_registry import AccessClass

_P: AccessClass = "project"

MCP_ACCESS: Mapping[str, AccessClass] = {
    # Own: user-private runtime registry and the caller's own machine agents.
    "studio_register_runtime": "own",
    "studio_register_agent": "own",
    # Project: every other tool reads or writes project data (lists filtered).
    "studio_get_projects": _P,
    "studio_get_project_state": _P,
    "studio_prepare_context": _P,
    "studio_get_task": _P,
    "studio_get_active_tasks": _P,
    "studio_create_task": _P,
    "studio_update_task": _P,
    "studio_claim_task": _P,
    "studio_release_task": _P,
    "studio_get_resource_claims": _P,
    "studio_claim_resource": _P,
    "studio_release_resource": _P,
    "studio_get_decisions": _P,
    "studio_add_decision": _P,
    "studio_accept_decision": _P,
    "studio_supersede_decision": _P,
    "studio_get_recent_changes": _P,
    "studio_get_sessions": _P,
    "studio_get_teammate_activity": _P,
    "studio_start_session": _P,
    "studio_end_session": _P,
    "studio_log_ai_work": _P,
    "studio_get_ai_work": _P,
    "studio_get_builds": _P,
    "studio_request_producer_job": _P,
    "studio_get_review_queue": _P,
    "studio_get_roadmap": _P,
    "studio_propose_roadmap": _P,
    "studio_preview_roadmap_hydration": _P,
    "studio_apply_roadmap_hydration": _P,
    "studio_update_roadmap_step": _P,
    "studio_transition_roadmap": _P,
    "studio_preview_project_initialization": _P,
    "studio_apply_project_initialization": _P,
    "studio_get_timeline": _P,
    "studio_emit_event": _P,
    "studio_create_transfer_metadata": _P,
    "studio_get_transfers": _P,
    "studio_get_transfer": _P,
    "studio_request_transfer_download": _P,
    "studio_resolve_agent": _P,
    "studio_discover_definitions": _P,
    "studio_publish_definition": _P,
    "studio_configure_runtime": _P,
}
