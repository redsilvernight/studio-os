"""Run three independent OpenCode readonly audits against the local P1.6 fixture."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import asyncpg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from studio_api.db.models.task import TaskModel

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
TRACE = HERE / "traces"
P15 = ROOT / "docs/audits/studios-agent-workflow/validation-p1-e2e"
RUNTIME = ROOT / ".worktrees/p15-runtime-20261104"


def configure_old_runner() -> Any:
    sys.path.insert(0, str(P15))
    validate = importlib.import_module("validate")
    models = importlib.import_module("models_p16")
    validate.TRACE = TRACE
    validate.RUNTIME = RUNTIME
    models.TRACE = TRACE
    models.RUNTIME = RUNTIME

    def environment() -> dict[str, str]:
        password = (ROOT / ".worktrees/p0-runtime-20261104/pw.txt").read_text().strip()
        env = os.environ.copy()
        env.update(
            STUDIO_ENVIRONMENT="test",
            STUDIO_DATABASE_URL=(
                f"postgresql+asyncpg://p15_runner:{password}@127.0.0.1:55441/studio_p16_test"
            ),
            STUDIO_TEST_DATABASE_URL=(
                f"postgresql+asyncpg://p15_runner:{password}@127.0.0.1:55441/studio_p16_test"
            ),
            STUDIO_S3_ENDPOINT_URL="http://127.0.0.1:55449",
            STUDIO_REALTIME_LISTENER_ENABLED="false",
            STUDIO_MCP_TOOL_PROFILE="session",
        )
        env.pop("STUDIO_MCP_MACHINE_TOKEN", None)
        return env

    models.environment = environment
    return models


async def snapshot(task_id: str) -> dict[str, Any]:
    url = os.environ["STUDIO_TEST_DATABASE_URL"].replace("postgresql+asyncpg:", "postgresql:")
    conn = await asyncpg.connect(url)
    try:
        task = await conn.fetchrow(
            "SELECT id, status, version, claimed_by_machine_id, claimed_by_agent_id "
            "FROM tasks WHERE id=$1",
            task_id,
        )
        assert task
        result: dict[str, Any] = {
            "task": dict(task),
            "database": await conn.fetchval("SELECT current_database()"),
        }
        for table in ("work_sessions", "resource_claims", "events", "ai_work_logs"):
            result[table] = await conn.fetchval(
                f"SELECT count(*) FROM {table} WHERE task_id=$1", task_id
            )
        return result
    finally:
        await conn.close()


async def add_fresh_readonly_tasks(fixture: dict[str, Any]) -> None:
    engine = create_async_engine(os.environ["STUDIO_DATABASE_URL"])
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        for index in range(4, 7):
            key = f"readonly_0{index}"
            if key not in fixture["tasks"]["opencode"]:
                task = TaskModel(
                    project_id=uuid.UUID(fixture["project_id"]),
                    title=f"P16 OpenCode readonly {index:02d}",
                    description="Isolated P1.6 local API5 fixture; no production data",
                )
                session.add(task)
                await session.flush()
                fixture["tasks"]["opencode"][key] = str(task.id)
        await session.commit()
    await engine.dispose()


async def main() -> None:
    TRACE.mkdir(exist_ok=True)
    fixture_path = TRACE / "fixture.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    models = configure_old_runner()
    await add_fresh_readonly_tasks(fixture)
    for index in range(1, 4):
        task_id = fixture["tasks"]["opencode"][f"readonly_0{index + 3}"]
        fixture["tasks"]["opencode"]["readonly"] = task_id
        fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
        before = await snapshot(task_id)
        (TRACE / f"opencode-readonly-r2-{index}-before.json").write_text(
            json.dumps(before, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        run_id = f"p16-e04-r2-{index}"
        models.run("opencode", "readonly", run_id)
        after = await snapshot(task_id)
        (TRACE / f"opencode-readonly-r2-{index}-after.json").write_text(
            json.dumps(after, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"OpenCode readonly run {index}: task state before/after captured.")


if __name__ == "__main__":
    asyncio.run(main())
