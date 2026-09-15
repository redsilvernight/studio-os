from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import events as events_service
from studio_api.services.ai_work import _derive_event_id
from studio_contracts.events import EventType
from studio_mcp.tools.ai_work import studio_get_ai_work, studio_log_ai_work

from tests.mcp.conftest import FakeContext


async def test_log_ai_work_creates_started_entry(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    result = await studio_log_ai_work(str(project.id), "Implement étape 5", str(agent.id), auth_ctx)
    assert result["status"] == "started"
    assert result["ended_at"] is None


async def test_log_ai_work_updates_existing_entry_to_completed(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    created = await studio_log_ai_work(
        str(project.id), "Implement étape 5", str(agent.id), auth_ctx
    )
    updated = await studio_log_ai_work(
        str(project.id),
        "Implement étape 5",
        str(agent.id),
        auth_ctx,
        ai_work_id=created["id"],
        status="completed",
        changed_files=["services/mcp/src/studio_mcp/server.py"],
        tests_run=["tests/mcp/test_ai_work.py"],
    )
    assert updated["status"] == "completed"
    assert updated["ended_at"] is not None
    assert updated["changed_files"] == ["services/mcp/src/studio_mcp/server.py"]


async def test_log_ai_work_rejects_unknown_agent(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_log_ai_work(
        str(project.id), "Orphan work", "00000000-0000-0000-0000-000000000000", auth_ctx
    )
    assert result["error_code"] == "invalid_reference"


async def test_log_ai_work_rejects_unknown_existing_id(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    result = await studio_log_ai_work(
        str(project.id),
        "Update on missing entry",
        str(agent.id),
        auth_ctx,
        ai_work_id="00000000-0000-0000-0000-000000000000",
    )
    assert result["error_code"] == "not_found"


async def test_get_ai_work_filters_by_project(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    created = await studio_log_ai_work(str(project.id), "Filtered work", str(agent.id), auth_ctx)
    result = await studio_get_ai_work(auth_ctx, project_id=str(project.id))
    assert any(w["id"] == created["id"] for w in result["ai_work"])


async def test_log_ai_work_emits_same_event_id_shape_as_http_path(
    db_session: AsyncSession, auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    """The MCP tool is a thin layer over the same service function the HTTP
    router calls (`.claude/rules/mcp-tools.md`) — this asserts it, rather than
    assuming it, by checking the emitted event's id matches the deterministic
    derivation `create_ai_work`/`update_ai_work` use on the HTTP path too."""
    created = await studio_log_ai_work(str(project.id), "MCP parity", str(agent.id), auth_ctx)
    events = await events_service.list_events(db_session, project_id=str(project.id))
    started = [e for e in events if e.event_type == EventType.AI_WORK_STARTED.value]
    assert len(started) == 1
    assert started[0].id == _derive_event_id(uuid.UUID(created["id"]), EventType.AI_WORK_STARTED)


async def test_log_ai_work_update_to_completed_emits_completed_event(
    db_session: AsyncSession, auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    created = await studio_log_ai_work(str(project.id), "MCP parity", str(agent.id), auth_ctx)
    await studio_log_ai_work(
        str(project.id),
        "MCP parity",
        str(agent.id),
        auth_ctx,
        ai_work_id=created["id"],
        status="completed",
    )
    events = await events_service.list_events(db_session, project_id=str(project.id))
    completed = [e for e in events if e.event_type == EventType.AI_WORK_COMPLETED.value]
    assert len(completed) == 1


async def test_log_ai_work_review_resolution_is_admin_only_and_actor_type_user(
    auth_ctx: FakeContext,
    admin_ctx: FakeContext,
    db_session: AsyncSession,
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    """Same authorization guarantee as the HTTP path
    (`test_review_resolution_requires_admin_and_review_requested_status`),
    exercised through the MCP tool: the owning agent's own machine cannot
    resolve its own review, and only `admin` can, via the exact same
    `update_ai_work` call the router uses."""
    created = await studio_log_ai_work(str(project.id), "MCP review", str(agent.id), auth_ctx)

    review = await studio_log_ai_work(
        str(project.id),
        "MCP review",
        str(agent.id),
        auth_ctx,
        ai_work_id=created["id"],
        status="review_requested",
    )
    assert review["status"] == "review_requested"

    self_approve = await studio_log_ai_work(
        str(project.id),
        "MCP review",
        str(agent.id),
        auth_ctx,
        ai_work_id=created["id"],
        status="approved",
    )
    assert self_approve["error_code"] == "forbidden"

    approved = await studio_log_ai_work(
        str(project.id),
        "MCP review",
        str(agent.id),
        admin_ctx,
        ai_work_id=created["id"],
        status="approved",
    )
    assert approved["status"] == "approved"

    events = await events_service.list_events(db_session, project_id=str(project.id))
    approved_events = [e for e in events if e.event_type == EventType.AI_WORK_APPROVED.value]
    assert len(approved_events) == 1
    assert approved_events[0].actor_type == "user"
