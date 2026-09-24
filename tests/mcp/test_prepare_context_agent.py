"""P3.3 agent-bound library selection + P3.9 cross-harness resume (needs DB)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.services import ai_work as ai_work_service
from studio_api.services import library as library_service
from studio_api.services import projects as projects_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal, load_principal
from studio_client.adapters import get_adapter
from studio_client.canonical import build_offline_resolved
from studio_contracts.ai_work import AIWorkLogCreate, AIWorkLogUpdate
from studio_contracts.library import (
    DependencyPin,
    LibraryKind,
    LibraryResourceCreate,
    LibraryScope,
)
from studio_contracts.tasks import TaskCreate
from studio_mcp.tools.context import studio_prepare_context

from tests.mcp.conftest import FakeContext

Machine = tuple[MachineModel, str]
REPO = Path(__file__).resolve().parents[2]

RULE = LibraryKind.RULE
SKILL = LibraryKind.SKILL
AGENT = LibraryKind.AGENT_DEFINITION


def dump(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    assert isinstance(result, dict)
    return result


async def _principal(db_session: AsyncSession, machine: Machine) -> Principal:
    return await load_principal(db_session, machine[0])


async def _project(db_session: AsyncSession):
    return await projects_service.create_project(
        db_session, f"ctx-{uuid.uuid4().hex[:8]}", "Context Project", None, creator=None
    )


async def _resource(db_session, principal, kind, key, content, dependencies=None):
    resource, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=kind,
            stable_key=key,
            scope=LibraryScope.STUDIO,
            title=f"{key} title",
            content=content,
            dependencies=dependencies or [],
        ),
    )
    await db_session.refresh(resource)
    await library_service.activate_resource_version(
        db_session, principal, resource, 1, resource.version
    )
    await db_session.refresh(resource)
    return resource


def _rule(text: str) -> dict[str, object]:
    return {"content_schema": "studio.library.rule/v1", "text": text}


def _skill(text: str) -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": text}


def _agent(summary: str) -> dict[str, object]:
    return {"content_schema": "studio.library.agent_definition/v1", "summary": summary}


async def _prepare(auth_ctx, project, objective, **kwargs):
    return dump(await studio_prepare_context(str(project.id), objective, auth_ctx, **kwargs))


async def test_agent_bindings_win_over_lexical_only(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _resource(db_session, principal, RULE, "p3-bound-rule", _rule("Bound rule text."))
    await _resource(db_session, principal, SKILL, "p3-bound-skill", _skill("Bound skill text."))
    await _resource(
        db_session,
        principal,
        AGENT,
        "p3-worker",
        _agent("Worker."),
        dependencies=[
            DependencyPin(kind=RULE, stable_key="p3-bound-rule", version=1),
            DependencyPin(kind=SKILL, stable_key="p3-bound-skill", version=1),
        ],
    )

    # Objective shares no token with the bound texts: lexical alone finds nothing.
    result = await _prepare(
        auth_ctx, project, "quokka zephyr completely unrelated", agent_stable_key="p3-worker"
    )

    by_key = {r["stable_key"]: r for r in result["rules"]}
    assert by_key["p3-bound-rule"]["agent_applies"] is True
    skills = {s["stable_key"]: s for s in result["skills"]}
    assert skills["p3-bound-skill"]["agent_applies"] is True
    assert result["returned"]["rules"] >= 1 and result["returned"]["skills"] >= 1


async def test_unknown_agent_fails_closed(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    project = await _project(db_session)
    result = await _prepare(auth_ctx, project, "anything", agent_stable_key="no-such-agent")
    assert result["error_code"] == "definition_not_found"


async def test_no_agent_key_behaves_as_before(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _resource(db_session, principal, RULE, "p3-plain-rule", _rule("quokka husbandry"))
    plain = await _prepare(auth_ctx, project, "quokka husbandry")
    assert plain["rules"][0]["agent_applies"] is False


async def test_cross_harness_resume(
    db_session: AsyncSession,
    machine: Machine,
    agent: AgentModel,
    auth_ctx: FakeContext,
) -> None:
    """P3.9: Agent A configured from the Claude projection, Agent B from the
    OpenCode projection of the SAME canonical source. B has zero A history
    and still resumes via one prepare_context."""
    claude_cfg = get_adapter("claude-code").translate(build_offline_resolved(REPO, "studio-tester"))
    opencode_cfg = get_adapter("opencode").translate(build_offline_resolved(REPO, "studio-tester"))
    # Same canon, two envelopes: identical instructions and rule sets.
    assert "You are the QA specialist" in claude_cfg.artifacts[0].content
    assert "You are the QA specialist" in opencode_cfg.artifacts[0].content
    assert "python-conventions" in claude_cfg.artifacts[0].content
    assert "python-conventions" in opencode_cfg.artifacts[0].content
    assert claude_cfg.artifacts[0].path.startswith(".claude/agents/")
    assert opencode_cfg.artifacts[0].path.startswith(".opencode/agents/")

    # --- Agent A works (task + handoff), context destroyed afterwards. ---
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await tasks_service.create_task(
        db_session, principal, TaskCreate(project_id=project.id, title="Fix claim TTL")
    )
    work = await ai_work_service.create_ai_work(
        db_session,
        principal,
        AIWorkLogCreate(
            project_id=project.id,
            agent_id=agent.id,
            task_id=task.id,
            summary="DONE index. NEXT rename the TTL label.",
        ),
    )
    await ai_work_service.update_ai_work(
        db_session, principal, work, AIWorkLogUpdate(status="completed")
    )

    # --- Agent B: other harness projection, no history, one call. ---
    result = await _prepare(auth_ctx, project, "fix claim TTL", task_id=str(task.id))
    assert result["task"]["id"] == str(task.id)
    assert any("NEXT rename the TTL label" in e["summary"] for e in result["ai_work"])
