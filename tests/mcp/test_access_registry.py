"""Fail-closed MCP tool registry and generated outsider matrix (DEC-0103 §12).

Mirror of `tests/api/test_access_registry.py` for the MCP surface: every
registered tool is classified in `MCP_ACCESS`, every `project` tool has an
outsider probe, and an active User without membership (member of another
project) gets `forbidden` on `project` — or a filtered listing — through each
of them, `studio_prepare_context`, `studio_discover_definitions` and
`studio_resolve_agent` included (refused before any read).
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import pytest
import studio_mcp.server as tools
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.build import BuildModel
from studio_api.db.models.machine import MachineModel
from studio_api.services import projects as projects_service
from studio_api.services.authz import load_principal
from studio_contracts.initialization import ProjectInitializationPlan
from studio_contracts.roadmaps import RoadmapDocument
from studio_mcp.access_registry import MCP_ACCESS
from studio_mcp.server import create_server
from studio_mcp.tools.ai_library import studio_configure_runtime, studio_publish_definition
from studio_mcp.tools.ai_work import studio_log_ai_work
from studio_mcp.tools.builds import studio_request_producer_job
from studio_mcp.tools.claims import studio_claim_resource
from studio_mcp.tools.decisions import studio_add_decision
from studio_mcp.tools.roadmaps import studio_propose_roadmap
from studio_mcp.tools.sessions import studio_start_session
from studio_mcp.tools.tasks import studio_create_task
from studio_mcp.tools.transfers import studio_create_transfer_metadata

from tests.e2e.test_roadmaps_p10_e2e import _plan
from tests.mcp.conftest import FakeContext

pytestmark = pytest.mark.isolation


async def test_every_tool_is_classified_and_no_entry_is_stale() -> None:
    registered = {tool.name for tool in await create_server().list_tools()}
    assert not registered - MCP_ACCESS.keys(), "unclassified tools (add them to MCP_ACCESS)"
    assert not MCP_ACCESS.keys() - registered, "stale MCP_ACCESS entries"


@dataclass(frozen=True)
class Probe:
    """Keyword arguments of one outsider call; string leaves are formatted
    with the world. Expectations as in the HTTP matrix."""

    kwargs: dict[str, Any]
    expect: Literal["forbidden", "filtered", "role", "slug"] = "forbidden"


_MD5 = base64.b64encode(hashlib.md5(b"x").digest()).decode()
_UNKNOWN = "00000000-0000-4000-8000-000000000000"
_RULE = {"content_schema": "studio.library.rule/v1", "text": "Outsider rule."}
_DOC = {
    "title": "Outsider",
    "phases": [{"key": "P1", "title": "P", "steps": [{"key": "S1", "title": "S"}]}],
}

PROBES: dict[str, tuple[Probe, ...]] = {
    "studio_get_projects": (Probe({}, "filtered"),),
    "studio_get_project_state": (Probe({"project_id": "{pid}"}),),
    "studio_prepare_context": (Probe({"project_id": "{pid}", "objective": "anything"}),),
    "studio_get_task": (Probe({"task_id": "{task}"}),),
    "studio_get_active_tasks": (Probe({"project_id": "{pid}"}),),
    "studio_create_task": (Probe({"project_id": "{pid}", "title": "x"}),),
    "studio_update_task": (Probe({"task_id": "{task}", "expected_version": 1, "title": "x"}),),
    "studio_claim_task": (Probe({"task_id": "{task}"}),),
    "studio_release_task": (Probe({"task_id": "{task}"}),),
    "studio_get_resource_claims": (Probe({"project_id": "{pid}"}),),
    "studio_claim_resource": (
        Probe(
            {
                "project_id": "{pid}",
                "resource_path": "x.py",
                "resource_type": "file",
                "ttl_seconds": 60,
            }
        ),
    ),
    "studio_release_resource": (Probe({"claim_id": "{claim}"}),),
    "studio_get_decisions": (Probe({"project_id": "{pid}"}), Probe({}, "filtered")),
    "studio_add_decision": (Probe({"title": "x", "body": "x", "project_id": "{pid}"}),),
    "studio_accept_decision": (
        Probe({"decision_id": "{decision}"}, "role"),
        Probe({"decision_id": _UNKNOWN}, "role"),
    ),
    "studio_supersede_decision": (
        Probe({"decision_id": "{decision}"}, "role"),
        Probe({"decision_id": _UNKNOWN}, "role"),
    ),
    "studio_get_recent_changes": (
        Probe({"project_id": "{pid}"}),
        Probe({"task_id": "{task}"}),
        Probe({"task_id": _UNKNOWN}, "filtered"),
        Probe({}, "filtered"),
    ),
    "studio_get_sessions": (Probe({"task_id": "{task}"}),),
    "studio_get_teammate_activity": (Probe({"project_id": "{pid}"}),),
    "studio_start_session": (Probe({"task_id": "{task}"}),),
    "studio_end_session": (Probe({"session_id": "{session}"}),),
    "studio_log_ai_work": (
        Probe({"project_id": "{pid}", "summary": "x", "agent_id": "{outsider_agent}"}),
        Probe(
            {
                "project_id": "{pid}",
                "summary": "x",
                "agent_id": "{outsider_agent}",
                "ai_work_id": "{work}",
            }
        ),
    ),
    "studio_get_ai_work": (
        Probe({"project_id": "{pid}"}),
        Probe({"task_id": "{task}"}),
        Probe({"task_id": _UNKNOWN}, "filtered"),
        Probe({}, "filtered"),
    ),
    "studio_get_builds": (Probe({"project_id": "{pid}"}), Probe({}, "filtered")),
    "studio_request_producer_job": (Probe({"project_id": "{pid}", "kind": "priority_analysis"}),),
    "studio_get_review_queue": (Probe({"project_id": "{pid}"}), Probe({}, "filtered")),
    "studio_get_roadmap": (Probe({"project_id": "{pid}"}),),
    "studio_propose_roadmap": (
        Probe({"project_id": "{pid}", "document": "$doc"}),
        Probe(
            {
                "project_id": "{pid}",
                "document": "$doc",
                "roadmap_id": "{roadmap}",
                "base_revision_no": 1,
            }
        ),
    ),
    "studio_preview_roadmap_hydration": (Probe({"roadmap_id": "{roadmap}"}),),
    "studio_apply_roadmap_hydration": (Probe({"roadmap_id": "{roadmap}", "expected_version": 1}),),
    "studio_update_roadmap_step": (
        Probe({"roadmap_id": "{roadmap}", "step_key": "S1", "expected_version": 1, "notes": "x"}),
    ),
    "studio_transition_roadmap": (
        Probe({"roadmap_id": "{roadmap}", "transition": "archive", "expected_version": 1}),
    ),
    "studio_preview_project_initialization": (Probe({"plan": "$plan"}, "slug"),),
    "studio_apply_project_initialization": (Probe({"plan": "$plan"}, "slug"),),
    "studio_get_timeline": (Probe({"project_id": "{pid}"}),),
    "studio_emit_event": (
        Probe(
            {
                "project_id": "{pid}",
                "event_type": "task.updated",
                "actor_type": "user",
                "actor_id": "{outsider_user}",
                "payload": {},
            }
        ),
    ),
    "studio_create_transfer_metadata": (
        Probe(
            {
                "filename": "x.bin",
                "content_type": "application/octet-stream",
                "size_bytes": 1,
                "category": "asset",
                "project_id": "{pid}",
                "content_md5": _MD5,
            }
        ),
    ),
    "studio_get_transfers": (Probe({"project_id": "{pid}"}), Probe({}, "filtered")),
    "studio_get_transfer": (Probe({"transfer_id": "{transfer}"}),),
    "studio_request_transfer_download": (Probe({"transfer_id": "{transfer}"}),),
    "studio_resolve_agent": (Probe({"stable_key": "world-agent", "project_id": "{pid}"}),),
    "studio_discover_definitions": (
        Probe({"project_id": "{pid}"}),
        Probe({"resource_id": "{lib}"}),
        Probe({}, "filtered"),
    ),
    "studio_publish_definition": (
        Probe(
            {
                "action": "create",
                "kind": "rule",
                "stable_key": "outsider-rule",
                "scope": "project",
                "project_id": "{pid}",
                "title": "x",
                "content": _RULE,
            }
        ),
        Probe({"action": "create_version", "resource_id": "{lib}", "title": "x", "content": _RULE}),
        Probe(
            {
                "action": "activate",
                "resource_id": "{lib}",
                "version": 1,
                "expected_resource_version": 1,
            }
        ),
    ),
    "studio_configure_runtime": (
        Probe(
            {
                "action": "set",
                "level": "project_default",
                "project_id": "{pid}",
                "target_kind": "agent_definition",
                "target_stable_key": "outsider-agent",
                "target": {"harness_ref": "x"},
            }
        ),
        Probe(
            {
                "action": "clear",
                "level": "project_default",
                "project_id": "{pid}",
                "target_kind": "agent_definition",
                "target_stable_key": "world-agent",
            }
        ),
    ),
}


def test_probes_cover_exactly_the_project_tools() -> None:
    project_tools = {name for name, access in MCP_ACCESS.items() if access == "project"}
    assert not project_tools - PROBES.keys(), "project tools without an outsider probe"
    assert not PROBES.keys() - project_tools, "probes for non-project tools"


def _dump(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    assert isinstance(result, dict)
    return result


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    assert "error_code" not in result, result
    return result


async def _build_world(
    db_session: AsyncSession,
    member: FakeContext,
    member_machine: MachineModel,
    member_agent: AgentModel,
    outsider_machine: MachineModel,
) -> dict[str, str]:
    principal = await load_principal(db_session, member_machine)
    slug = f"world-{uuid.uuid4().hex[:8]}"
    project = await projects_service.create_project(
        db_session, slug, "World", None, creator=principal.user
    )
    outsider = await load_principal(db_session, outsider_machine)
    await projects_service.create_project(  # member elsewhere, never of `project`
        db_session, f"else-{slug}", "Elsewhere", None, creator=outsider.user
    )
    outsider_agent = AgentModel(
        machine_id=outsider_machine.id, display_name="outsider", agent_kind="claude_code"
    )
    db_session.add(outsider_agent)
    build = BuildModel(
        project_id=project.id,
        workflow_run_id=1,
        workflow_name="ci",
        run_number=1,
        branch="main",
        commit_sha="0" * 40,
        html_url="https://example.test/run/1",
        actor_login="ci",
    )
    db_session.add(build)
    await db_session.flush()

    pid = str(project.id)
    task = _ok(await studio_create_task(pid, "t", member))["id"]
    session = _ok(await studio_start_session(task, member))["id"]
    claim = _ok(await studio_claim_resource(pid, "a.py", "file", 600, member))["id"]
    decision = _ok(await studio_add_decision("d", "d", member, project_id=pid))["id"]
    lib = _dump(
        await studio_publish_definition(
            "create",
            member,
            kind="rule",
            stable_key="world-rule",
            scope="project",
            project_id=pid,
            title="r",
            content=_RULE,
        )
    )
    _dump(
        await studio_configure_runtime(
            "set",
            member,
            level="project_default",
            project_id=pid,
            target_kind="agent_definition",
            target_stable_key="world-agent",
            target={"harness_ref": "h"},
        )
    )
    work = _ok(await studio_log_ai_work(pid, "w", str(member_agent.id), member))["id"]
    job = _ok(await studio_request_producer_job(pid, "priority_analysis", member))["id"]
    transfer = _ok(
        await studio_create_transfer_metadata(
            "a.bin",
            "application/octet-stream",
            1,
            "asset",
            member,
            project_id=pid,
            content_md5=_MD5,
        )
    )["id"]
    roadmap = _ok(
        await studio_propose_roadmap(
            pid, RoadmapDocument.model_validate(_DOC), member, submit=False
        )
    )["id"]
    return {
        "pid": pid,
        "slug": slug,
        "task": task,
        "session": session,
        "claim": claim,
        "decision": decision,
        "lib": _ok(lib).get("id") or lib["resource"]["id"],
        "work": work,
        "build": str(build.id),
        "job": job,
        "transfer": transfer,
        "roadmap": roadmap,
        "outsider_user": str(outsider_machine.owner_user_id),
        "outsider_agent": str(outsider_agent.id),
    }


_LEAK_KEYS: tuple[str, ...] = (
    "pid",
    "task",
    "session",
    "claim",
    "decision",
    "lib",
    "work",
    "build",
    "job",
)
_LEAK_KEYS += ("transfer", "roadmap")


def _render(value: Any, world: dict[str, str]) -> Any:
    if value == "$plan":
        return ProjectInitializationPlan.model_validate(_plan(world["slug"]))
    if value == "$doc":
        return RoadmapDocument.model_validate(_DOC)
    if isinstance(value, dict):
        return {k: _render(v, world) for k, v in value.items()}
    if isinstance(value, str):
        return value.format(**world)
    return value


def _verdict(name: str, expect: str, result: dict[str, Any], world: dict[str, str]) -> bool:
    text = json.dumps(result, default=str)
    leaks = any(world[key] in text for key in _LEAK_KEYS)
    if expect == "forbidden":
        return result.get("error_code") == "forbidden" and result.get("resource") == "project"
    if expect == "filtered":
        return "error_code" not in result and not leaks
    if expect == "role":
        return result.get("error_code") == "forbidden"
    # slug: the preview plans a `create`; apply only fails on slug uniqueness
    # with the structured `conflict` code (slugs are non-secret, accepted
    # oracle) — never a write, never the generic `error` fallback.
    if name.startswith("studio_apply"):
        return result.get("error_code") == "conflict" and not leaks
    actions = [a for a in result.get("actions", []) if a["section"] == "project"]
    return "error_code" not in result and all(a["action"] == "create" for a in actions)


async def test_outsider_matrix(
    db_session: AsyncSession,
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    agent: AgentModel,
) -> None:
    world = await _build_world(db_session, auth_ctx, machine[0], agent, other_machine[0])
    failures: list[str] = []
    for name, probes in PROBES.items():
        for probe in probes:
            result = _dump(
                await getattr(tools, name)(**_render(probe.kwargs, world), ctx=other_auth_ctx)
            )
            if not _verdict(name, probe.expect, result, world):
                failures.append(
                    f"{name}({probe.kwargs}) -> {json.dumps(result, default=str)[:200]}"
                )
    assert not failures, "outsider matrix:\n" + "\n".join(failures)
