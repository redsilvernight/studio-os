from __future__ import annotations

from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.decisions import studio_add_decision, studio_get_decisions

from tests.mcp.conftest import FakeContext


async def test_add_decision_gets_a_readable_id(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_add_decision(
        "Pick a transport", "SSE over WebSocket.", auth_ctx, project_id=str(project.id)
    )
    assert result["readable_id"].startswith("DEC-")
    assert result["status"] == "proposed"


async def test_add_decision_rejects_bad_project_id(auth_ctx: FakeContext) -> None:
    result = await studio_add_decision("Title", "Body", auth_ctx, project_id="not-a-uuid")
    assert result["error_code"] == "invalid_argument"


async def test_get_decisions_lists_added_decision(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_add_decision(
        "Pick a queue", "Postgres advisory lock.", auth_ctx, project_id=str(project.id)
    )
    result = await studio_get_decisions(auth_ctx, project_id=str(project.id))
    assert any(d["id"] == created["id"] for d in result["decisions"])


async def test_add_decision_idempotency_key_replay_allocates_no_second_id(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    """DEC-0027: a replayed studio_add_decision call must not burn a second
    DEC-XXXX readable_id."""
    first = await studio_add_decision(
        "Retried decision",
        "Same body both times.",
        auth_ctx,
        project_id=str(project.id),
        idempotency_key="mcp-decision-key-1",
    )
    second = await studio_add_decision(
        "Retried decision",
        "Same body both times.",
        auth_ctx,
        project_id=str(project.id),
        idempotency_key="mcp-decision-key-1",
    )
    assert second["id"] == first["id"]
    assert second["readable_id"] == first["readable_id"]
