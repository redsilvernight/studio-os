from __future__ import annotations

from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.ai_work import studio_get_ai_work
from studio_mcp.tools.claims import studio_claim_resource, studio_get_resource_claims
from studio_mcp.tools.handoff import studio_handoff
from studio_mcp.tools.sessions import studio_start_session
from studio_mcp.tools.tasks import studio_claim_task, studio_create_task

from tests.mcp.conftest import FakeContext


async def _open_work(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> tuple[dict, dict]:
    task = await studio_create_task(str(project.id), "Handoff target", auth_ctx)
    await studio_claim_task(task["id"], auth_ctx, agent_id=str(agent.id))
    await studio_claim_resource(
        str(project.id), "src/a.py", "file", 600, auth_ctx, task_id=task["id"]
    )
    session = await studio_start_session(task["id"], auth_ctx, agent_id=str(agent.id))
    return task, session


async def test_handoff_releases_claims_and_links_ai_work_to_session(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task, session = await _open_work(auth_ctx, project, agent)
    before = await studio_get_resource_claims(str(project.id), auth_ctx)
    assert before["claims"]

    result = await studio_handoff(
        str(project.id),
        session["id"],
        task["version"],
        auth_ctx,
        agent_id=str(agent.id),
        summary="Closed in one call",
    )
    assert result["released_claims"]
    assert result["ai_work_id"] is not None

    after = await studio_get_resource_claims(str(project.id), auth_ctx)
    assert [c["status"] for c in after["claims"]] == ["released"] * len(after["claims"])
    assert not [c for c in after["claims"] if c["status"] == "active"]

    listing = await studio_get_ai_work(auth_ctx, task_id=task["id"])
    assert [w["session_id"] for w in listing["ai_work"]] == [session["id"]]


async def test_handoff_idempotency_key_replay_has_no_second_effect(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task, session = await _open_work(auth_ctx, project, agent)
    args = (str(project.id), session["id"], task["version"], auth_ctx)
    kwargs = {"agent_id": str(agent.id), "summary": "Once only", "idempotency_key": "handoff-1"}

    first = await studio_handoff(*args, **kwargs)
    second = await studio_handoff(*args, **kwargs)
    assert second == first

    listing = await studio_get_ai_work(auth_ctx, task_id=task["id"])
    assert len(listing["ai_work"]) == 1
