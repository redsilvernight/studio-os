"""Create a dedicated P1.6 project and harness fixtures in the local test DB."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.user import UserModel
from studio_api.services import projects
from studio_contracts import API_CONTRACT_VERSION

ROOT = Path(__file__).resolve().parents[4]
TRACE = Path(__file__).resolve().parent / "traces"
P15_FIXTURE = ROOT / "docs/audits/studios-agent-workflow/validation-p1-e2e/traces/fixture.json"


async def main() -> None:
    assert API_CONTRACT_VERSION == 5
    source = json.loads(P15_FIXTURE.read_text(encoding="utf-8"))
    engine = create_async_engine(os.environ["STUDIO_DATABASE_URL"])
    ids: dict[str, object] = {"api_contract_version": 5, "agents": {}, "tasks": {}}
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        from_agent = await session.get(AgentModel, source["agents"]["direct"])
        assert from_agent and from_agent.owner_user_id and from_agent.machine_id
        owner = await session.get(UserModel, from_agent.owner_user_id)
        assert owner
        project = await projects.create_project(
            session,
            "p16-e2e",
            "P16 E2E ONLY",
            "Local API5 fixture; no production data",
            creator=owner,
        )
        ids.update(project_id=str(project.id), machine_id=str(from_agent.machine_id))
        for harness in ("claude", "codex", "opencode", "direct"):
            agent = AgentModel(
                machine_id=from_agent.machine_id,
                owner_user_id=from_agent.owner_user_id,
                display_name=f"p16-{harness}",
                agent_kind="assistant",
                harness=harness,
                stable_key=f"p16-{harness}",
            )
            session.add(agent)
            await session.flush()
            ids["agents"][harness] = str(agent.id)
            ids["tasks"][harness] = {}
            scenarios = ("tracked", "readonly", "provided", "signal", "failed", "handoff")
            if harness == "opencode":
                scenarios += ("readonly_01", "readonly_02", "readonly_03")
            if harness == "direct":
                scenarios += ("signal_source",)
            for scenario in scenarios:
                task = TaskModel(
                    project_id=project.id,
                    title=f"P16 {harness} {scenario}",
                    description="Isolated P1.6 local API5 fixture; no production data",
                )
                session.add(task)
                await session.flush()
                ids["tasks"][harness][scenario] = str(task.id)
        await session.commit()
    await engine.dispose()
    TRACE.mkdir(exist_ok=True)
    (TRACE / "fixture.json").write_text(
        json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Created P16 E2E fixture in the local API5 database.")


if __name__ == "__main__":
    asyncio.run(main())
