from __future__ import annotations

import pytest_asyncio
from mcp.types import Tool

# UC-2B conformance: `tools/list` must let a previously unknown consumer
# (unknown-harness / unknown-provider / unknown-model, no TECH/*, no DEC-*,
# no repo docs) learn each exposed tool's role, inputs, main constraints
# and key errors — without implying HTTP/MCP surface parity (DEC-0046).
# Pure metadata assertions: no database needed.

FORBIDDEN_FRAGMENTS = (
    "TECH/",
    "DEC-",
    "routers/",
    "services/",
    "studio_api",
    "studio_mcp",
    ".py",
    "contract-guardian",
    "studio-tester",
    "studio-architect",
    "sync-debugger",
    "claude",
    "qwen",
    "codex",
    "opencode",
)

READ_ONLY_TOOLS = {
    "studio_get_projects",
    "studio_get_project_state",
    "studio_get_task",
    "studio_get_active_tasks",
    "studio_get_resource_claims",
    "studio_get_decisions",
    "studio_get_recent_changes",
    "studio_get_sessions",
    "studio_get_teammate_activity",
    "studio_get_ai_work",
    "studio_get_transfers",
    "studio_get_transfer",
    "studio_request_transfer_download",
    "studio_get_review_queue",
    "studio_get_timeline",
    "studio_get_builds",
}

WRITE_TOOLS = {
    "studio_create_task",
    "studio_update_task",
    "studio_claim_task",
    "studio_release_task",
    "studio_claim_resource",
    "studio_release_resource",
    "studio_add_decision",
    "studio_start_session",
    "studio_end_session",
    "studio_log_ai_work",
    "studio_emit_event",
    "studio_create_transfer_metadata",
    "studio_request_producer_job",
}


@pytest_asyncio.fixture
async def tools() -> list[Tool]:
    from studio_mcp.server import mcp

    return await mcp.list_tools()


def _by_name(tools: list[Tool]) -> dict[str, Tool]:
    return {tool.name: tool for tool in tools}


def test_all_tools_have_external_descriptions(tools: list[Tool]) -> None:
    assert len(tools) == 29
    for tool in tools:
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) >= 40, f"{tool.name} description is stub-like"


def test_no_internal_references_leak_into_tools_list(tools: list[Tool]) -> None:
    for tool in tools:
        lowered = (tool.description or "").lower()
        for fragment in FORBIDDEN_FRAGMENTS:
            assert fragment.lower() not in lowered, f"{tool.name} leaks {fragment}"


def test_read_tools_marked_read_only_and_writes_are_not(tools: list[Tool]) -> None:
    by_name = _by_name(tools)
    assert set(by_name) == READ_ONLY_TOOLS | WRITE_TOOLS
    for name in READ_ONLY_TOOLS:
        annotations = by_name[name].annotations
        assert annotations is not None and annotations.read_only_hint is True, name
    for name in WRITE_TOOLS:
        annotations = by_name[name].annotations
        assert not (annotations is not None and annotations.read_only_hint), name


def test_writer_role_and_forbidden_visible_where_they_gate(tools: list[Tool]) -> None:
    by_name = _by_name(tools)
    for name in ("studio_create_task", "studio_claim_task", "studio_emit_event"):
        assert "writer" in (by_name[name].description or "")
    assert "forbidden" in (by_name["studio_release_task"].description or "")
    assert "forbidden" in (by_name["studio_get_transfer"].description or "")


def test_idempotency_and_event_id_discoverable(tools: list[Tool]) -> None:
    by_name = _by_name(tools)
    for name in (
        "studio_create_task",
        "studio_claim_resource",
        "studio_add_decision",
        "studio_start_session",
    ):
        schema = by_name[name].input_schema
        assert "idempotency_key" in schema["properties"], name
        assert "idempotency_key" not in schema.get("required", []), name
        assert "duplicate" in (by_name[name].description or ""), name
    emit_schema = by_name["studio_emit_event"].input_schema
    assert "event_id" in emit_schema["properties"]
    assert "event_id" not in emit_schema.get("required", [])


def test_version_conflict_and_ownership_discoverable(tools: list[Tool]) -> None:
    by_name = _by_name(tools)
    assert "version_conflict" in (by_name["studio_update_task"].description or "")
    assert "expected_version" in by_name["studio_update_task"].input_schema["properties"]
    assert "actor_not_owned" in (by_name["studio_log_ai_work"].description or "")
    assert "already_claimed" in (by_name["studio_claim_task"].description or "")


def test_event_identity_rules_without_internal_docs(tools: list[Tool]) -> None:
    description = _by_name(tools)["studio_emit_event"].description or ""
    for fragment in (
        "machine_id_mismatch",
        "actor_id_mismatch",
        "actor_not_owned",
        "invalid_event_type",
    ):
        assert fragment in description


def test_http_fallback_pointers_where_transport_is_partial(tools: list[Tool]) -> None:
    by_name = _by_name(tools)
    assert "POST /api/v1/agents" in (by_name["studio_log_ai_work"].description or "")
    assert "/api/v1/transfers" in (by_name["studio_create_transfer_metadata"].description or "")
    assert "/api/v1/events/stream" in (by_name["studio_get_recent_changes"].description or "")
