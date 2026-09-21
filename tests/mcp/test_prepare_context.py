from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from mcp import Client
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.library import LibraryResourceModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import claims as claims_service
from studio_api.services import decisions as decisions_service
from studio_api.services import library as library_service
from studio_api.services import project_context as context_service
from studio_api.services import projects as projects_service
from studio_api.services import tasks as tasks_service
from studio_api.services.authz import Principal, load_principal
from studio_contracts.claims import ResourceClaimCreate, ResourceType
from studio_contracts.decisions import DecisionCreate
from studio_contracts.library import LibraryKind, LibraryResourceCreate, LibraryScope
from studio_contracts.tasks import TaskCreate
from studio_mcp.server import mcp
from studio_mcp.tools.ai_library import studio_discover_definitions
from studio_mcp.tools.claims import studio_get_resource_claims
from studio_mcp.tools.context import studio_prepare_context
from studio_mcp.tools.decisions import studio_get_decisions
from studio_mcp.tools.projects import studio_get_project_state, studio_get_projects
from studio_mcp.tools.tasks import studio_get_active_tasks, studio_get_task

from tests.mcp.conftest import FakeContext

Machine = tuple[MachineModel, str]

RULE = LibraryKind.RULE
SKILL = LibraryKind.SKILL


def dump(result: Any) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    assert isinstance(result, dict)
    return result


async def _principal(db_session: AsyncSession, machine: Machine) -> Principal:
    return await load_principal(db_session, machine[0])


async def _project(db_session: AsyncSession, description: str | None = None) -> ProjectModel:
    return await projects_service.create_project(
        db_session, f"ctx-{uuid.uuid4().hex[:8]}", "Context Project", description
    )


async def _task(
    db_session: AsyncSession,
    principal: Principal,
    project: ProjectModel,
    title: str,
    description: str | None = None,
):
    return await tasks_service.create_task(
        db_session,
        principal,
        TaskCreate(project_id=project.id, title=title, description=description),
    )


async def _decision(
    db_session: AsyncSession,
    principal: Principal,
    project: ProjectModel | None,
    title: str,
    body: str = "body",
    task_id: uuid.UUID | None = None,
    status: str | None = None,
):
    decision = await decisions_service.create_decision(
        db_session,
        principal,
        DecisionCreate(
            project_id=project.id if project else None,
            task_id=task_id,
            title=title,
            body=body,
            proposed_by_type="agent",
            proposed_by_id=principal.user.id,
        ),
    )
    if status is not None:
        decision.status = status
        await db_session.commit()
    return decision


async def _library(
    db_session: AsyncSession,
    principal: Principal,
    kind: LibraryKind,
    key: str,
    text: str,
    *,
    scope: LibraryScope = LibraryScope.STUDIO,
    project: ProjectModel | None = None,
    title: str | None = None,
    activate: bool = True,
):
    resource, _ = await library_service.create_resource(
        db_session,
        principal,
        LibraryResourceCreate(
            kind=kind,
            stable_key=key,
            scope=scope,
            project_id=project.id if project else None,
            title=title or f"{key} title",
            content={"content_schema": f"studio.library.{kind.value}/v1", "text": text},
        ),
    )
    await db_session.refresh(resource)
    if activate:
        await library_service.activate_resource_version(
            db_session, principal, resource, 1, resource.version
        )
        await db_session.refresh(resource)
    return resource


async def _claim(
    db_session: AsyncSession,
    principal: Principal,
    project: ProjectModel,
    path: str,
    resource_type: ResourceType = ResourceType.FILE,
    task_id: uuid.UUID | None = None,
):
    return await claims_service.create_claim(
        db_session,
        principal,
        ResourceClaimCreate(
            project_id=project.id,
            task_id=task_id,
            resource_path=path,
            resource_type=resource_type,
            ttl_seconds=3600,
        ),
        principal.machine.id,
        None,
    )


async def _prepare(ctx: FakeContext, project: ProjectModel, objective: str, **kwargs: Any):
    return dump(await studio_prepare_context(str(project.id), objective, ctx, **kwargs))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_selects_relevant_context_and_explains_why(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session, "Studio tooling")
    await _task(db_session, principal, project, "Git Watcher multi repository support")
    await _task(db_session, principal, project, "Dashboard colours")
    await _decision(db_session, principal, project, "Watcher polls each repository", "git watcher")
    await _decision(db_session, principal, project, "Pick a colour palette", "dashboard")
    await _library(db_session, principal, RULE, "watcher-safety", "Never block git operations.")
    await _library(db_session, principal, RULE, "naming", "Use snake_case everywhere.")
    await _library(db_session, principal, SKILL, "git-watcher-debug", "Inspect the watcher loop.")

    result = await _prepare(
        auth_ctx, project, "Modifier le Git Watcher pour supporter plusieurs repository"
    )

    assert result["project"]["id"] == str(project.id)
    assert result["query_terms"] == [
        "modifier",
        "git",
        "watcher",
        "supporter",
        "plusieurs",
        "repository",
    ]
    assert [t["title"] for t in result["related_tasks"]] == ["Git Watcher multi repository support"]
    assert result["related_tasks"][0]["why"]["reason"] == "lexical"
    assert "watcher" in result["related_tasks"][0]["why"]["matched_terms"]
    assert [d["title"] for d in result["decisions"]] == ["Watcher polls each repository"]
    assert [r["stable_key"] for r in result["rules"]] == ["watcher-safety"]
    assert [s["stable_key"] for s in result["skills"]] == ["git-watcher-debug"]
    # What matched nothing is counted, not shipped.
    assert result["additional_available"]["related_tasks"] == 1
    assert result["additional_available"]["decisions"] == 1
    assert result["additional_available"]["rules"] == 1
    assert result["returned"] == {
        "task": 0,
        "related_tasks": 1,
        "decisions": 1,
        "rules": 1,
        "skills": 1,
        "ai_work": 0,
        "claims": 0,
    }


async def test_requested_task_links_decisions_and_claims_structurally(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project, "Refactor storage layer", "Move to S3")
    other = await _task(db_session, principal, project, "Unrelated chore")
    linked = await _decision(
        db_session, principal, project, "Chose multipart", "No lexical overlap", task.id
    )
    await _decision(db_session, principal, project, "Unlinked and unrelated")
    await _claim(db_session, principal, project, "src/storage.py", task_id=task.id)
    await _claim(db_session, principal, project, "src/other.py", task_id=other.id)

    result = await _prepare(auth_ctx, project, "Finish the work", task_id=str(task.id))

    assert result["task"]["id"] == str(task.id)
    assert result["task"]["why"]["reason"] == "requested"
    assert [d["readable_id"] for d in result["decisions"]] == [linked.readable_id]
    assert result["decisions"][0]["why"]["reason"] == "linked_to_task"
    assert [c["resource_path"] for c in result["active_work"]["claims"]] == ["src/storage.py"]
    assert result["active_work"]["claims"][0]["why"]["reason"] == "task_claim"
    assert result["additional_available"]["claims"] == 1


async def test_files_report_conflicting_claims_of_other_machines_only(
    db_session: AsyncSession,
    machine: Machine,
    other_machine: Machine,
    auth_ctx: FakeContext,
) -> None:
    principal = await _principal(db_session, machine)
    other = await _principal(db_session, other_machine)
    project = await _project(db_session)
    await _claim(db_session, other, project, "src/watcher", ResourceType.FOLDER)
    await _claim(db_session, other, project, "docs/readme.md")
    await _claim(db_session, principal, project, "src/watcher/own.py")

    result = await _prepare(
        auth_ctx, project, "Edit the watcher", files=["src/watcher/loop.py", "src/watcher/own.py"]
    )

    claims = result["active_work"]["claims"]
    assert [c["resource_path"] for c in claims] == ["src/watcher"]
    assert claims[0]["why"]["reason"] == "path_conflict"
    assert claims[0]["claimed_by_self"] is False
    assert result["additional_available"]["claims"] == 2  # own claim + unrelated readme


async def test_project_scope_rule_is_included_without_lexical_match(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _library(
        db_session,
        principal,
        RULE,
        "house-style",
        "Tabs only.",
        scope=LibraryScope.PROJECT,
        project=project,
    )
    await _library(db_session, principal, RULE, "studio-generic", "Be kind.")

    result = await _prepare(auth_ctx, project, "Something entirely different")

    assert [r["stable_key"] for r in result["rules"]] == ["house-style"]
    assert result["rules"][0]["why"] == {"reason": "project_scope", "matched_terms": []}
    assert result["rules"][0]["scope"] == "project"
    assert result["additional_available"]["rules"] == 1


async def test_project_definition_shadows_studio_one(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _library(db_session, principal, RULE, "shared-key", "studio wording watcher")
    await _library(
        db_session,
        principal,
        RULE,
        "shared-key",
        "project wording watcher",
        scope=LibraryScope.PROJECT,
        project=project,
    )

    result = await _prepare(auth_ctx, project, "watcher")

    assert [(r["scope"], r["text"]) for r in result["rules"]] == [
        ("project", "project wording watcher")
    ]
    assert result["additional_available"]["rules"] == 0


async def test_superseded_decisions_and_deprecated_or_unactivated_rules_are_left_out(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _decision(db_session, principal, project, "Old watcher design", status="superseded")
    await _library(db_session, principal, RULE, "draft-watcher", "watcher", activate=False)
    deprecated = await _library(db_session, principal, RULE, "old-watcher", "watcher")
    await library_service.deprecate_resource(db_session, principal, deprecated, deprecated.version)

    result = await _prepare(auth_ctx, project, "watcher")

    assert result["decisions"] == []
    assert result["rules"] == []
    assert result["additional_available"] == {
        "related_tasks": 0,
        "decisions": 0,
        "rules": 0,
        "skills": 0,
        "ai_work": 0,
        "claims": 0,
    }


# ---------------------------------------------------------------------------
# Bounds and determinism
# ---------------------------------------------------------------------------


async def test_result_is_bounded_however_much_data_exists(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    for i in range(30):
        await _task(db_session, principal, project, f"watcher task {i:02d}", "watcher " * 400)
        await _decision(db_session, principal, project, f"watcher decision {i:02d}", "x" * 3000)
        await _library(db_session, principal, RULE, f"watcher-rule-{i:02d}", "y" * 5000)
        await _library(db_session, principal, SKILL, f"watcher-skill-{i:02d}", "z" * 5000)

    result = await _prepare(auth_ctx, project, "watcher", limit=3, max_chars=20_000)

    for kind in ("related_tasks", "decisions", "rules", "skills"):
        assert len(result[kind]) == 3
        assert all(item["truncated"] for item in result[kind])  # each text > 1500 chars
    assert result["limits"]["chars_used"] == 12 * context_service.ITEM_TEXT_CAP
    # Nothing silently vanishes: totals stay reconcilable.
    returned, extra = result["returned"], result["additional_available"]
    for kind in ("related_tasks", "decisions", "rules", "skills"):
        assert returned[kind] + extra[kind] == 30

    tight = await _prepare(auth_ctx, project, "watcher", limit=3, max_chars=4000)
    assert tight["limits"]["chars_used"] <= 4000
    text_total = (
        sum(len(t["description"] or "") for t in tight["related_tasks"])
        + sum(len(d["body"]) for d in tight["decisions"])
        + sum(len(r["text"]) for r in tight["rules"] + tight["skills"])
        + len(tight["project"]["description"] or "")
    )
    assert text_total == tight["limits"]["chars_used"]


async def test_budget_exhaustion_drops_items_and_reports_them(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    for i in range(6):
        await _decision(db_session, principal, project, f"watcher decision {i}", "x" * 1500)
    await _library(db_session, principal, RULE, "watcher-rule", "y" * 1500)

    result = await _prepare(auth_ctx, project, "watcher", limit=10, max_chars=1000)

    assert result["limits"]["chars_used"] <= 1000
    assert result["returned"]["decisions"] == 1  # 1000 chars fit one truncated body
    assert result["omitted_for_budget"]["decisions"] == 5
    assert result["omitted_for_budget"]["rules"] == 1
    assert result["additional_available"]["decisions"] == 5
    assert result["decisions"][0]["truncated"] is True


async def test_identical_inputs_give_identical_output(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    for i in range(8):
        await _task(db_session, principal, project, f"watcher task {i}")
        await _decision(db_session, principal, project, f"watcher decision {i}")
        await _library(db_session, principal, RULE, f"watcher-rule-{i}", "watcher")

    first = await _prepare(auth_ctx, project, "watcher", limit=4)
    second = await _prepare(auth_ctx, project, "watcher", limit=4)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


async def test_empty_project_yields_a_valid_compact_answer(
    db_session: AsyncSession, auth_ctx: FakeContext
) -> None:
    project = await _project(db_session)

    result = await _prepare(auth_ctx, project, "Anything at all")

    assert result["task"] is None
    assert result["related_tasks"] == result["decisions"] == result["rules"] == []
    assert result["skills"] == [] and result["active_work"]["claims"] == []
    assert set(result["returned"].values()) == {0}
    assert set(result["additional_available"].values()) == {0}
    assert result["omitted_for_budget"] == {}
    assert len(json.dumps(result)) < 1500


async def test_objective_without_usable_terms_still_returns_structural_context(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project, "Anchor")

    result = await _prepare(auth_ctx, project, "fix it", task_id=str(task.id))

    assert result["query_terms"] == []
    assert result["task"]["title"] == "Anchor"


# ---------------------------------------------------------------------------
# Isolation and permissions
# ---------------------------------------------------------------------------


async def test_other_projects_data_never_appears(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    mine = await _project(db_session)
    foreign = await _project(db_session)
    await _task(db_session, principal, foreign, "Foreign watcher task")
    await _decision(db_session, principal, foreign, "Foreign watcher decision")
    await _decision(db_session, principal, None, "Global watcher decision")
    await _claim(db_session, principal, foreign, "src/watcher/loop.py")
    await _library(
        db_session,
        principal,
        RULE,
        "foreign-watcher",
        "watcher",
        scope=LibraryScope.PROJECT,
        project=foreign,
    )
    await _task(db_session, principal, mine, "Own watcher task")

    result = await _prepare(auth_ctx, mine, "watcher", files=["src/watcher/loop.py"])

    assert [t["title"] for t in result["related_tasks"]] == ["Own watcher task"]
    assert result["decisions"] == []
    assert result["rules"] == []
    assert result["active_work"]["claims"] == []
    assert "Foreign" not in json.dumps(result)


async def test_foreign_or_unknown_task_fails_closed_with_the_same_answer(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    mine = await _project(db_session)
    foreign = await _project(db_session)
    foreign_task = await _task(db_session, principal, foreign, "Secret")

    for task_id in (foreign_task.id, uuid.uuid4()):
        result = dump(await studio_prepare_context(str(mine.id), "watcher", auth_ctx, str(task_id)))
        assert result["error_code"] == "not_found"
        assert "Secret" not in json.dumps(result)


async def test_private_library_definitions_of_other_users_are_invisible(
    db_session: AsyncSession,
    machine: Machine,
    other_machine: Machine,
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _library(
        db_session,
        principal,
        RULE,
        "my-private-watcher",
        "watcher secret",
        scope=LibraryScope.USER,
    )

    mine = await _prepare(auth_ctx, project, "watcher")
    theirs = await _prepare(other_auth_ctx, project, "watcher")

    assert [r["stable_key"] for r in mine["rules"]] == ["my-private-watcher"]
    assert theirs["rules"] == []
    assert theirs["additional_available"]["rules"] == 0
    assert "secret" not in json.dumps(theirs)


async def test_readonly_role_can_read_like_on_every_other_read_tool(
    db_session: AsyncSession, project: ProjectModel, readonly_auth_ctx: FakeContext
) -> None:
    result = await _prepare(readonly_auth_ctx, project, "watcher")
    assert result["project"]["id"] == str(project.id)


async def test_unauthenticated_and_invalid_token_are_rejected(
    db_session: AsyncSession, project: ProjectModel
) -> None:
    anonymous = dump(await studio_prepare_context(str(project.id), "watcher", FakeContext()))
    assert anonymous["error_code"] == "unauthenticated"
    bad = FakeContext(headers={"authorization": "Bearer nope"})
    assert dump(await studio_prepare_context(str(project.id), "x", bad))["error_code"] == (
        "unauthenticated"
    )


async def test_writes_nothing(
    db_session: AsyncSession, machine: Machine, auth_ctx: FakeContext
) -> None:
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    task = await _task(db_session, principal, project, "watcher")
    await _decision(db_session, principal, project, "watcher")
    await _library(db_session, principal, RULE, "watcher-rule", "watcher")

    async def _state() -> tuple[int, int, int, int]:
        counts = []
        for model in (EventModel, DecisionModel, LibraryResourceModel, ResourceClaimModel):
            counts.append(
                (await db_session.execute(select(func.count()).select_from(model))).scalar_one()
            )
        await db_session.refresh(task)
        return task.version, *counts[:1], counts[1] + counts[2], counts[3]

    before = await _state()
    await _prepare(auth_ctx, project, "watcher", task_id=str(task.id), files=["a.py"])
    assert await _state() == before


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"objective": "   "},
        {"objective": "x" * 1001},
        {"objective": "ok", "limit": 0},
        {"objective": "ok", "limit": 21},
        {"objective": "ok", "max_chars": 999},
        {"objective": "ok", "max_chars": 50_001},
        {"objective": "ok", "files": ["a"] * 21},
        {"objective": "ok", "files": [" "]},
        {"objective": "ok", "files": ["p" * 501]},
    ],
)
async def test_out_of_range_arguments_are_rejected(
    project: ProjectModel, auth_ctx: FakeContext, kwargs: dict[str, Any]
) -> None:
    arguments = dict(kwargs)
    objective = arguments.pop("objective")
    result = dump(await studio_prepare_context(str(project.id), objective, auth_ctx, **arguments))
    assert result["error_code"] == "invalid_argument"


async def test_bad_ids_and_unknown_project(project: ProjectModel, auth_ctx: FakeContext) -> None:
    assert dump(await studio_prepare_context("nope", "x", auth_ctx))["error_code"] == (
        "invalid_argument"
    )
    assert (
        dump(await studio_prepare_context(str(project.id), "x", auth_ctx, "nope"))["error_code"]
        == "invalid_argument"
    )
    unknown = dump(await studio_prepare_context(str(uuid.uuid4()), "x", auth_ctx))
    assert unknown["error_code"] == "not_found"


# ---------------------------------------------------------------------------
# Compatibility and discovery
# ---------------------------------------------------------------------------


async def test_tool_is_additive_read_only_and_has_an_output_schema() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    tool = tools["studio_prepare_context"]
    assert tool.annotations is not None and tool.annotations.read_only_hint is True
    assert tool.output_schema is not None
    assert set(tool.input_schema["required"]) == {"project_id", "objective"}
    for legacy in (
        "studio_get_projects",
        "studio_get_project_state",
        "studio_get_task",
        "studio_get_active_tasks",
        "studio_get_decisions",
        "studio_discover_definitions",
        "studio_get_resource_claims",
    ):
        assert legacy in tools


def test_pure_helpers() -> None:
    assert context_service.tokens("Git_Watcher-v2.py") == ["git", "watcher", "v2", "py"]
    assert context_service.query_terms("Fix the Git Watcher for 2 repos, pour les repos") == [
        "git",
        "watcher",
        "repos",
    ]
    assert context_service.score(["git", "loop", "zzz"], "Git watcher", "the loop")[0] == 4
    assert context_service.score(["git"], "Git", "git git")[1] == ["git"]
    assert len(context_service.query_terms(" ".join(f"term{i}x" for i in range(60)))) == 24


def test_budget_semantics() -> None:
    budget = context_service._Budget(1000)
    assert budget.take("a" * 2000) == ("a" * 1000, True)  # cut to the remainder
    assert budget.used == 1000 and budget.remaining == 0
    assert budget.take("") == ("", False)  # empty text is always free
    tiny = context_service._Budget(150)
    assert tiny.take("abc") == ("abc", False)
    assert tiny.take("d" * 500) is None  # remainder below MIN_TEXT_CHARS
    assert tiny.take("") == ("", False)
    mid = context_service._Budget(600)
    assert mid.take("e" * 1000) == ("e" * 600, True)
    assert mid.take("f") is None


# ---------------------------------------------------------------------------
# Measured gain: one call vs the low-level exploration it replaces
# ---------------------------------------------------------------------------


def _size(payload: Any) -> int:
    return len(json.dumps(payload, default=str))


async def test_measured_gain_against_low_level_exploration(
    db_session: AsyncSession,
    machine: Machine,
    other_machine: Machine,
    auth_ctx: FakeContext,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Scenario: an agent starts work on the Git Watcher of a mature project.
    Both paths are actually executed and measured (calls, payload characters,
    items) — no token count is claimed, only what can be counted."""
    principal = await _principal(db_session, machine)
    project = await _project(db_session, "Studio tooling monorepo")
    watcher_task = await _task(
        db_session, principal, project, "Git Watcher multi repository support", "Watch N repos."
    )
    for i in range(40):
        await _task(db_session, principal, project, f"Chore {i}", "Unrelated maintenance. " * 12)
    for i in range(60):
        title = "Watcher polling interval" if i < 3 else f"Decision {i}"
        body = ("Explains the watcher. " if i < 3 else "Explains something else. ") * 30
        await _decision(db_session, principal, project, title, body)
    for i in range(12):
        watcher = i < 2
        await _library(
            db_session,
            principal,
            RULE,
            f"{'watcher-' if watcher else ''}rule-{i}",
            "Guidance text. " * 60,
        )
    for i in range(8):
        await _library(db_session, principal, SKILL, f"skill-{i}", "Skill body. " * 60)
    teammate = await _principal(db_session, other_machine)
    await _claim(db_session, teammate, project, "src/watcher/loop.py")

    # Before: what an agent without the facade does, tool by tool.
    calls: list[tuple[str, Any]] = []
    calls.append(("studio_get_projects", await studio_get_projects(auth_ctx)))
    calls.append(
        ("studio_get_project_state", await studio_get_project_state(str(project.id), auth_ctx))
    )
    calls.append(
        ("studio_get_active_tasks", await studio_get_active_tasks(str(project.id), auth_ctx))
    )
    calls.append(("studio_get_task", await studio_get_task(str(watcher_task.id), auth_ctx)))
    calls.append(("studio_get_decisions", await studio_get_decisions(auth_ctx, str(project.id))))
    calls.append(
        ("studio_get_resource_claims", await studio_get_resource_claims(str(project.id), auth_ctx))
    )
    for kind in ("rule", "skill"):
        listing = dump(await studio_discover_definitions(auth_ctx, kind=kind))
        calls.append((f"studio_discover_definitions({kind}) list", listing))
        for definition in listing["definitions"]:
            if "watcher" in definition["stable_key"] or kind == "skill":
                detail = await studio_discover_definitions(
                    auth_ctx, resource_id=definition["id"], include_versions=True
                )
                calls.append((f"studio_discover_definitions(one {kind})", detail))
    before_calls = len(calls)
    before_chars = sum(_size(dump(result)) for _, result in calls)

    # After: one call.
    prepared = await _prepare(
        auth_ctx,
        project,
        "Modifier le Git Watcher pour supporter plusieurs repositories",
        task_id=str(watcher_task.id),
        files=["src/watcher/loop.py"],
    )
    after_chars = _size(prepared)
    after_items = sum(prepared["returned"].values())

    with capsys.disabled():
        print(
            f"\n[prepare_context gain] before: {before_calls} MCP calls, {before_chars} chars; "
            f"after: 1 call, {after_chars} chars, {after_items} items "
            f"(returned={prepared['returned']}, more={prepared['additional_available']})"
        )
    assert before_calls >= 10
    assert after_chars < before_chars / 2
    assert after_items <= 6 * context_service.DEFAULT_LIMIT + 1
    assert prepared["task"]["id"] == str(watcher_task.id)
    assert {d["title"] for d in prepared["decisions"]} == {"Watcher polling interval"}
    # The teammate's claim on the file about to be edited is surfaced.
    assert [c["why"]["reason"] for c in prepared["active_work"]["claims"]] == ["path_conflict"]


async def test_protocol_round_trip_returns_structured_output(
    db_session: AsyncSession,
    machine: Machine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through the real server (stdio-style token from the environment): the
    response is valid structured content matching the declared output schema."""
    principal = await _principal(db_session, machine)
    project = await _project(db_session)
    await _task(db_session, principal, project, "Watcher work")
    monkeypatch.setenv("STUDIO_MCP_MACHINE_TOKEN", machine[1])

    arguments = {"project_id": str(project.id), "objective": "watcher"}
    async with Client(mcp) as client:
        result = await client.call_tool("studio_prepare_context", arguments)
        assert not result.is_error
        structured = result.structured_content
        # `PreparedContext | McpError` is a union: the SDK wraps it under `result`,
        # exactly like the five AI Library tools.
        assert structured is not None
        prepared = structured["result"]
        assert prepared["project"]["id"] == str(project.id)
        assert [t["title"] for t in prepared["related_tasks"]] == ["Watcher work"]

        monkeypatch.delenv("STUDIO_MCP_MACHINE_TOKEN")
        denied = await client.call_tool("studio_prepare_context", arguments)
        assert denied.structured_content is not None
        assert denied.structured_content["result"]["error_code"] == "unauthenticated"
