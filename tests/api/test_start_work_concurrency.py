from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.work_session import WorkSessionModel

from tests.api.test_roadmaps_domain import race, real_engine  # noqa: F401


@pytest.mark.parametrize("mode", ["same_agent", "different_agents", "expired"])
async def test_concurrent_starts_preserve_one_holder_and_one_resumed_session(
    race: tuple[AsyncClient, dict[str, str], ProjectModel],  # noqa: F811
    real_engine: AsyncEngine,  # noqa: F811
    mode: str,
) -> None:
    client, headers, project = race
    agents: list[str] = []
    task_id: str | None = None
    try:
        for _ in range(2 if mode == "different_agents" else 1):
            response = await client.post(
                "/api/v1/agents",
                headers=headers,
                json={"display_name": f"race-{uuid4()}", "agent_kind": "codex"},
            )
            assert response.status_code == 201, response.text
            agents.append(response.json()["id"])
        response = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"project_id": str(project.id), "title": "Concurrent start"},
        )
        assert response.status_code == 201, response.text
        task_id = response.json()["id"]
        body = {"project_id": str(project.id), "task_id": task_id, "agent_id": agents[0]}
        old_id: str | None = None
        if mode == "expired":
            first = await client.post("/api/v1/start-work", headers=headers, json=body)
            assert first.status_code == 200, first.text
            old_id = first.json()["session"]["id"]
            async with async_sessionmaker(real_engine)() as setup:
                await setup.execute(
                    update(WorkSessionModel)
                    .where(WorkSessionModel.id == UUID(old_id))
                    .values(last_activity_at=datetime.now(UTC) - timedelta(days=2))
                )
                await setup.commit()
        requests = [dict(body, agent_id=agent_id) for agent_id in agents]
        if mode != "different_agents":
            requests *= 6
        responses = await asyncio.gather(
            *(
                client.post("/api/v1/start-work", headers=headers, json=request)
                for request in requests
            )
        )
        expected = [200, 409] if mode == "different_agents" else [200] * 6
        assert sorted(response.status_code for response in responses) == expected, [
            response.text for response in responses
        ]
        successes = [response.json() for response in responses if response.status_code == 200]
        assert len({item["session"]["id"] for item in successes}) == 1
        if old_id is not None:
            assert successes[0]["session"]["id"] != old_id
        current = (await client.get(f"/api/v1/tasks/{task_id}", headers=headers)).json()
        assert current["claimed_by_agent_id"] == successes[0]["session"]["agent_id"]
        async with async_sessionmaker(real_engine)() as check:
            sessions = (
                (
                    await check.execute(
                        select(WorkSessionModel).where(WorkSessionModel.task_id == UUID(task_id))
                    )
                )
                .scalars()
                .all()
            )
            assert sum(item.ended_at is None for item in sessions) == 1
            assert len(sessions) == (2 if mode == "expired" else 1)
    finally:
        async with async_sessionmaker(real_engine)() as cleanup:
            if task_id is not None:
                await cleanup.execute(
                    delete(WorkSessionModel).where(WorkSessionModel.task_id == UUID(task_id))
                )
                await cleanup.execute(
                    update(TaskModel)
                    .where(TaskModel.id == UUID(task_id))
                    .values(claimed_by_agent_id=None)
                )
            await cleanup.execute(
                delete(AgentModel).where(AgentModel.id.in_([UUID(agent_id) for agent_id in agents]))
            )
            await cleanup.commit()
