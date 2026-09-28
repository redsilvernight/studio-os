"""`studio_start_work` (L2/DEC-0159) over MCP: same composite as
`POST /start-work`, same authority — idempotent claim, resume-or-create
session, scoped context; candidates without a task; agent ownership enforced.
Real Postgres through the shared savepoint fixtures."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.start_work import studio_start_work
from studio_mcp.tools.tasks import studio_create_task, studio_get_task

from tests.mcp.conftest import FakeContext


async def test_start_work_claims_resumes_and_replays(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Implement it", auth_ctx)

    first = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"]
    )
    assert first["claimed"] is True
    assert first["resumed"] is False
    assert first["task"]["id"] == task["id"]

    # Same key: the original result, byte for byte.
    replayed = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"], idempotency_key="sw-1"
    )
    again = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"], idempotency_key="sw-1"
    )
    assert again == replayed

    # No key: still no second session, the open one is resumed.
    resumed = await studio_start_work(
        str(project.id), str(agent.id), auth_ctx, task_id=task["id"]
    )
    assert resumed["resumed"] is True
    assert resumed["session"]["id"] == first["session"]["id"]


async def test_start_work_without_task_lists_candidates_and_claims_nothing(
    auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    task = await studio_create_task(str(project.id), "Maybe", auth_ctx)

    result = await studio_start_work(str(project.id), str(agent.id), auth_ctx)
    assert result["task"] is None
    assert result["session"] is None
    assert [c["task_id"] for c in result["candidates"]] == [task["id"]]

    untouched = await studio_get_task(task["id"], auth_ctx)
    assert untouched["claimed_by_machine_id"] is None


async def test_start_work_refuses_a_foreign_agent(
    auth_ctx: FakeContext,
    project: ProjectModel,
    db_session: AsyncSession,
    other_machine: tuple[MachineModel, str],
) -> None:
    other_model, _ = other_machine
    foreign = AgentModel(machine_id=other_model.id, display_name="foreign", agent_kind="")
    db_session.add(foreign)
    await db_session.flush()

    result = await studio_start_work(str(project.id), str(foreign.id), auth_ctx)
    assert result["error_code"] == "actor_not_owned"


async def test_start_work_rejects_a_non_uuid_agent(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_start_work(str(project.id), "not-a-uuid", auth_ctx)
    assert result["error_code"] == "invalid_argument"
