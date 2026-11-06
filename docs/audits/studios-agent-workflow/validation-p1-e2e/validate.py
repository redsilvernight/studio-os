"""Bounded P1.5 validation against a dedicated local PostgreSQL cluster."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
TRACE = OUT / "traces"
RUNTIME = ROOT / ".worktrees/p15-runtime-20261104"
PYTHON = ROOT / ".venv/Scripts/python.exe"


def environment() -> dict[str, str]:
    env = os.environ.copy()
    password = (ROOT / ".worktrees/p0-runtime-20261104/pw.txt").read_text().strip()
    env.update(
        STUDIO_ENVIRONMENT="test",
        STUDIO_DATABASE_URL=f"postgresql+asyncpg://p15_runner:{password}@127.0.0.1:55441/studio_p15_test",
        STUDIO_TEST_DATABASE_URL=f"postgresql+asyncpg://p15_runner:{password}@127.0.0.1:55441/studio_p15_test",
        STUDIO_S3_ENDPOINT_URL="http://127.0.0.1:55449",
        STUDIO_REALTIME_LISTENER_ENABLED="false",
        STUDIO_MCP_TOOL_PROFILE="session",
    )
    env.pop("STUDIO_MCP_MACHINE_TOKEN", None)
    return env


def save(name: str, value: Any) -> None:
    (TRACE / name).write_text(
        redact(json.dumps(value, indent=2, ensure_ascii=False, default=str)), encoding="utf-8"
    )


def redact(text: str) -> str:
    for path in (ROOT / ".worktrees/p0-runtime-20261104/pw.txt", RUNTIME / "machine-token.txt"):
        if path.exists():
            secret = path.read_text().strip()
            if secret:
                text = text.replace(secret, "[REDACTED]")
    return text


async def signals() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = environment()
    env["STUDIO_MCP_MACHINE_TOKEN"] = (RUNTIME / "machine-token.txt").read_text()
    ids = json.loads((TRACE / "fixture.json").read_text())
    log = []
    async with stdio_client(
        StdioServerParameters(
            command=str(PYTHON), args=["-m", "studio_mcp.server"], env=env, cwd=str(RUNTIME)
        )
    ) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()

            async def call(name: str, **arguments: Any) -> dict[str, Any]:
                response = await client.call_tool(name, arguments)
                value = response.structured_content or json.loads(response.content[0].text)
                value = value.get("result", value)
                log.append({"tool": name, "arguments": arguments, "response": value})
                save("signals-seed.json", log)
                assert "error_code" not in value, value
                return value

            source = await call(
                "studio_start_work",
                project_id=ids["project_id"],
                agent_id=ids["agents"]["direct"],
                task_id=ids["tasks"]["direct"]["signal"],
                idempotency_key="p15-sender",
            )
            for harness in ("claude", "codex", "opencode"):
                await call(
                    "studio_coordinate",
                    from_session_id=source["session"]["id"],
                    intent="heads_up",
                    task_id=ids["tasks"][harness]["tracked"],
                    text=(
                        f"Validation requirement {harness}: retain marker "
                        f"P15-SIGNAL-{harness.upper()} in the durable audit handoff summary "
                        "before acknowledging this message."
                    ),
                    event_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"p15-signal-{harness}")),
                )
    print("Three controlled signals emitted over real MCP")


async def bootstrap() -> None:
    import asyncpg
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from studio_api.db.models.agent import AgentModel
    from studio_api.db.models.task import TaskModel
    from studio_api.services import projects, provisioning
    from studio_contracts import API_CONTRACT_VERSION

    assert API_CONTRACT_VERSION == 5
    url = os.environ["STUDIO_DATABASE_URL"].replace("postgresql+asyncpg:", "postgresql:")
    conn = await asyncpg.connect(url.rsplit("/", 1)[0] + "/postgres")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname='studio_p15_test'")
        if not exists:
            await conn.execute("CREATE DATABASE studio_p15_test")
    finally:
        await conn.close()
    result = await asyncio.to_thread(
        subprocess.run,
        [str(PYTHON), "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "services/api",
        capture_output=True,
        text=True,
    )
    (TRACE / "migrations.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, "Migration failed; see migrations.log"
    engine = create_async_engine(os.environ["STUDIO_DATABASE_URL"])
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        user = await provisioning.create_user(
            session, "P15 isolated runner", "p15@example.test", "admin"
        )
        machine, token = await provisioning.create_machine(session, user.id, "p15-isolated")
        project = await projects.create_project(
            session, "p15-e2e", "P15 E2E ONLY", None, creator=user
        )
        ids: dict[str, Any] = {
            "project_id": str(project.id),
            "machine_id": str(machine.id),
            "api_contract_version": API_CONTRACT_VERSION,
            "tasks": {},
            "agents": {},
        }
        for harness in ("claude", "codex", "opencode", "direct"):
            agent = AgentModel(
                machine_id=machine.id,
                owner_user_id=user.id,
                display_name=f"p15-{harness}",
                agent_kind="assistant",
                harness=harness,
                stable_key=f"p15-{harness}",
            )
            session.add(agent)
            await session.flush()
            ids["agents"][harness] = str(agent.id)
            ids["tasks"][harness] = {}
            for scenario in ("tracked", "readonly", "provided", "signal", "failed", "conflict"):
                task = TaskModel(
                    project_id=project.id,
                    title=f"P15 {harness} {scenario}",
                    description="Isolated validation fixture; no production data",
                )
                session.add(task)
                await session.flush()
                ids["tasks"][harness][scenario] = str(task.id)
        await session.commit()
    await engine.dispose()
    RUNTIME.mkdir(exist_ok=True)
    (RUNTIME / "machine-token.txt").write_text(token)
    save("fixture.json", ids)
    print("API5 fixture created; dedicated database 127.0.0.1:55441/studio_p15_test")


async def snapshot(label: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(
        os.environ["STUDIO_DATABASE_URL"].replace("postgresql+asyncpg:", "postgresql:")
    )
    try:
        state = {}
        for table in ("tasks", "work_sessions", "resource_claims", "events", "ai_work_logs"):
            exists = await conn.fetchval("SELECT to_regclass($1)", table)
            if exists:
                state[table] = json.loads(
                    await conn.fetchval(
                        f"SELECT coalesce(json_agg(t),'[]')::text FROM (SELECT * FROM {table}) t"
                    )
                )
        state["database"] = await conn.fetchval("SELECT current_database()")
        save(f"state-{label}.json", state)
    finally:
        await conn.close()


async def direct() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = environment()
    env["STUDIO_MCP_MACHINE_TOKEN"] = (RUNTIME / "machine-token.txt").read_text()
    fixture = json.loads((TRACE / "fixture.json").read_text())
    log: list[Any] = []
    async with stdio_client(
        StdioServerParameters(
            command=str(PYTHON), args=["-m", "studio_mcp.server"], env=env, cwd=str(RUNTIME)
        )
    ) as (read, write):
        async with ClientSession(read, write) as client:
            initialized = await client.initialize()
            tools = await client.list_tools()
            save(
                "mcp-contract.json",
                {
                    "initialize": initialized.model_dump(mode="json"),
                    "tools": tools.model_dump(mode="json"),
                },
            )

            async def call(name: str, **arguments: Any) -> dict[str, Any]:
                started = time.monotonic()
                response = await client.call_tool(name, arguments)
                value = response.structured_content
                if value is None:
                    value = json.loads(response.content[0].text)
                if set(value) == {"result"}:
                    value = value["result"]
                log.append(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "response": value,
                        "seconds": time.monotonic() - started,
                    }
                )
                save("direct.json", log)
                return value

            project = fixture["project_id"]
            agent = fixture["agents"]["direct"]
            task = fixture["tasks"]["direct"]["tracked"]
            ctx = await call(
                "studio_prepare_context",
                project_id=project,
                task_id=task,
                objective="Isolated audit",
                max_chars=4000,
            )
            assert ctx["task"]["id"] == task
            args = dict(
                project_id=project,
                agent_id=agent,
                task_id=task,
                idempotency_key="p15-direct-start",
                max_chars=6000,
            )
            start = await call("studio_start_work", **args)
            assert "error_code" not in start, start
            replay = await call("studio_start_work", **args)
            assert start == replay
            session = start["session"]["id"]
            conflict = await call(
                "studio_update_task", task_id=task, expected_version=0, title="Must not write"
            )
            assert conflict.get("error_code") == "version_conflict", conflict
            block = await call("studio_sync", session_id=session)
            assert "error_code" not in block
            close_args = dict(
                project_id=project,
                session_id=session,
                agent_id=agent,
                summary="P15 directed transport diagnostic; replay verified",
                changed_files=[],
                tests_run=["real MCP stdio replay and version conflict"],
                idempotency_key="p15-direct-close",
            )
            closed = await call("studio_handoff", **close_args)
            assert "error_code" not in closed, closed
            assert closed == await call("studio_handoff", **close_args)
            print(
                f"Real MCP directed calls: {len(log)}; tools: {len(tools.tools)}; assertions passed"
            )


def preservation() -> None:
    baseline = json.loads((TRACE / "baseline.json").read_text())
    changed = [
        p
        for p, digest in baseline["files"].items()
        if not (ROOT / p).is_file() or hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != digest
    ]
    checks = {
        k: subprocess.check_output(["git", *args], cwd=ROOT).decode() == baseline[k]
        for k, args in {
            "head": ["rev-parse", "HEAD"],
            "index": ["diff", "--cached", "--raw"],
            "worktrees": ["worktree", "list", "--porcelain"],
        }.items()
    }
    save(
        "preservation.json", {"files_checked": len(baseline["files"]), "changed": changed, **checks}
    )
    assert not changed and all(checks.values())
    print("Preserved", len(baseline["files"]), "preexisting files, HEAD, index and worktrees")


def regression() -> None:
    runs = [
        (
            "preflight",
            ["pwsh", "-NoProfile", "-File", "scripts/test-env.ps1", "-TimeoutSeconds", "3"],
        ),
        (
            "p0-regression",
            [
                str(PYTHON),
                "-m",
                "pytest",
                "tests/api/test_p0_task_concurrency.py",
                "tests/mcp/test_p0_cursor_concurrency.py",
                "tests/mcp/test_p0_delivery.py",
                "tests/mcp/test_p0_delivery_races.py",
                "tests/mcp/test_sync.py",
                "tests/mcp/test_handoff.py",
                "tests/mcp/test_response_budget.py",
                "tests/contracts/test_version_compatibility.py",
                "--require-infra",
                "-q",
            ],
        ),
    ]
    results = []
    for name, command in runs:
        started = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        (TRACE / f"{name}.log").write_text(redact(result.stdout + result.stderr), encoding="utf-8")
        results.append(
            {
                "name": name,
                "command": command,
                "exit_code": result.returncode,
                "seconds": time.monotonic() - started,
            }
        )
        save("regression.json", results)
        print(name, result.returncode, (result.stdout + result.stderr)[-500:])


if __name__ == "__main__":
    os.environ.update(environment())
    if sys.argv[1] == "preservation":
        preservation()
    elif sys.argv[1] == "regression":
        regression()
    elif sys.argv[1] == "snapshot":
        asyncio.run(snapshot(sys.argv[2]))
    else:
        asyncio.run({"bootstrap": bootstrap, "direct": direct, "signals": signals}[sys.argv[1]]())
