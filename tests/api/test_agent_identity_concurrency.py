from __future__ import annotations

import asyncio
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.project import ProjectModel

from tests.api.test_roadmaps_domain import race, real_engine  # noqa: F401


async def test_concurrent_identity_resolution_creates_one_durable_agent(
    race: tuple[AsyncClient, dict[str, str], ProjectModel],  # noqa: F811
    real_engine: AsyncEngine,  # noqa: F811
) -> None:
    client, headers, _ = race
    model = f"identity-test-{uuid4()}"
    try:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/api/v1/agents/resolve-identity",
                    headers=headers,
                    json={"harness": "codex-cli", "provider": "openai", "effective_model": model},
                )
                for _ in range(6)
            )
        )
        assert sorted(r.status_code for r in responses) == [200, 200, 200, 200, 200, 201]
        assert len({r.json()["agent"]["id"] for r in responses}) == 1
    finally:
        async with async_sessionmaker(real_engine)() as cleanup:
            await cleanup.execute(delete(AgentModel).where(AgentModel.model == model))
            await cleanup.commit()
