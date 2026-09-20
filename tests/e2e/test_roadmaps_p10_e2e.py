"""Roadmaps P10 - final end-to-end release gate (real Postgres, real HTTP app,
real MCP tools, one isolated transaction).

Main scenario, in the order a team actually works:

    Project -> Initialization (preview, apply, replay) -> Roadmap -> Tasks ->
    Context -> AI proposal -> Human review -> updated Context -> export

plus the variants (request changes / reject / stale base / permissions), the
"no Roadmap" invariant, the provenance that must survive an approval, the
role-based (not identity-based) review boundary and the HTTP/MCP surface split.
Nothing here is mocked: the assertions are on what the platform really stores.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.event import EventModel
from studio_api.db.models.roadmap import RoadmapModel, RoadmapRevisionModel
from studio_api.db.models.task import TaskModel
from studio_contracts.initialization import ProjectInitializationPlan
from studio_contracts.roadmaps import (
    Provenance,
    Roadmap,
    RoadmapContext,
    RoadmapDocument,
    RoadmapRevision,
)
from studio_mcp.tools.context import studio_prepare_context
from studio_mcp.tools.initialization import (
    studio_apply_project_initialization,
    studio_preview_project_initialization,
)
from studio_mcp.tools.roadmaps import (
    studio_apply_roadmap_hydration,
    studio_get_roadmap,
    studio_propose_roadmap,
    studio_update_roadmap_step,
)

from tests.e2e.conftest import Actor, attach_agent
from tests.mcp.test_prepare_context import dump

Json = dict[str, Any]

PLAN_DOCUMENT: Json = {
    "format": "studio.roadmap/v1",
    "title": "Ship the game",
    "objective": "A playable build",
    "phases": [
        {
            "key": "P1",
            "title": "Foundations",
            "steps": [
                {
                    "key": "S1",
                    "title": "Set up the repo",
                    "acceptance_criteria": ["repo builds", "CI is green"],
                },
                {
                    "key": "S2",
                    "title": "Implement the core loop",
                    "depends_on": ["S1"],
                    "tasks": [{"hydration_key": "core-loop", "title": "Core loop"}],
                },
            ],
        },
        {"key": "P2", "title": "Polish", "steps": [{"key": "S3", "title": "Balance"}]},
    ],
}


def _plan(slug: str, *, mode: str = "draft", with_roadmap: bool = True) -> Json:
    plan: Json = {
        "format": "studio.initialization/v1",
        "mode": mode,
        "project": {"slug": slug, "name": "P10 Game", "description": "Final gate"},
        "tasks": [
            {"key": "setup", "title": "Set up the repo", "roadmap_step_key": "S1"},
            {"key": "chores", "title": "Standalone chores"},
        ],
    }
    if with_roadmap:
        plan["roadmap"] = copy.deepcopy(PLAN_DOCUMENT)
    else:
        plan["tasks"] = [{"key": "chores", "title": "Standalone chores"}]
    return plan


def _revised(**step_titles: str) -> Json:
    """The active plan with some step titles changed (an AI-proposed revision)."""
    document = copy.deepcopy(PLAN_DOCUMENT)
    for phase in document["phases"]:
        for step in phase["steps"]:
            if step["key"] in step_titles:
                step["title"] = step_titles[step["key"]]
    return document


def _step(roadmap: Json, key: str) -> Json:
    for phase in roadmap["phases"]:
        for step in phase["steps"]:
            if step["key"] == key:
                return step  # type: ignore[no-any-return]
    raise AssertionError(f"no step {key}")


def _detail(response: Any) -> Json:
    return response.json()["detail"]  # type: ignore[no-any-return]


async def _post(client: AsyncClient, actor: Actor, url: str, body: Json, **extra: str) -> Any:
    return await client.post(url, headers={**actor.headers, **extra}, json=body)


async def _apply_init(
    client: AsyncClient, actor: Actor, plan: Json, key: str | None = None
) -> Json:
    headers = {"Idempotency-Key": key} if key else {}
    response = await _post(
        client, actor, "/api/v1/projects/initialization/apply", {"plan": plan}, **headers
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def _get_roadmap(client: AsyncClient, actor: Actor, roadmap_id: str) -> Json:
    response = await client.get(f"/api/v1/roadmaps/{roadmap_id}", headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def _transition(client: AsyncClient, actor: Actor, roadmap: Json, name: str) -> Json:
    response = await _post(
        client,
        actor,
        f"/api/v1/roadmaps/{roadmap['id']}/transitions",
        {"transition": name, "expected_version": roadmap["version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def _context(actor: Actor, project_id: str, objective: str = "work on the plan") -> Json:
    return dump(await studio_prepare_context(project_id, objective, actor.ctx))


async def _bootstrap_active(
    client: AsyncClient, developer: Actor, slug: str | None = None
) -> tuple[str, Json]:
    """Initialization -> active roadmap. Returns (project_id, active roadmap)."""
    result = await _apply_init(client, developer, _plan(slug or f"p10-{uuid.uuid4().hex[:8]}"))
    active = await _transition(
        client, developer, await _get_roadmap(client, developer, result["roadmap_id"]), "activate"
    )
    return result["project_id"], active


async def _propose_over_mcp(
    agent: Actor,
    project_id: str,
    active: Json,
    document: Json,
    *,
    agent_id: uuid.UUID | None = None,
    summary: str = "Rename steps",
    idempotency_key: str | None = None,
) -> Json:
    return dump(
        await studio_propose_roadmap(
            project_id,
            RoadmapDocument.model_validate(document),
            agent.ctx,
            roadmap_id=active["id"],
            base_revision_no=active["approved_revision_no"],
            summary=summary,
            agent_id=str(agent_id) if agent_id else None,
            idempotency_key=idempotency_key,
        )
    )


async def _review(
    client: AsyncClient,
    actor: Actor,
    roadmap: Json,
    revision_no: int,
    decision: str,
    comment: str | None = None,
) -> Any:
    return await _post(
        client,
        actor,
        f"/api/v1/roadmaps/{roadmap['id']}/proposals/{revision_no}/review",
        {"decision": decision, "expected_version": roadmap["version"], "comment": comment},
    )


# ---------------------------------------------------------------------------------
# The main scenario
# ---------------------------------------------------------------------------------
async def test_main_scenario_project_to_export(
    client: AsyncClient,
    db_session: AsyncSession,
    developer: Actor,
    agent: Actor,
    admin: Actor,
) -> None:
    slug = f"p10-{uuid.uuid4().hex[:8]}"

    # -- B. initialization: preview writes nothing, apply is idempotent ------------
    plan = _plan(slug)
    preview = await _post(client, developer, "/api/v1/projects/initialization/preview", plan)
    assert preview.status_code == 200, preview.text
    assert preview.json()["applicable"] is True and preview.json()["problems"] == []
    assert {(a["section"], a["action"]) for a in preview.json()["actions"]} >= {
        ("project", "create"),
        ("roadmap", "create"),
        ("tasks", "create"),
    }
    listed = await client.get("/api/v1/projects", headers=developer.headers)
    assert all(p["slug"] != slug for p in listed.json())  # preview created nothing
    assert (await db_session.execute(select(func.count()).select_from(TaskModel))).scalar_one() == 0

    key = str(uuid.uuid4())
    applied = await _apply_init(client, developer, plan, key)
    assert applied["applied"] is True and applied["roadmap_status"] == "draft"
    assert applied["summary"]["created"] >= 4  # project, roadmap, 2 tasks
    assert applied["provenance"]["origin"] == "manual"
    project_id, roadmap_id = applied["project_id"], applied["roadmap_id"]

    replay_same_key = await _apply_init(client, developer, plan, key)
    assert replay_same_key == applied
    replay_new_key = await _apply_init(client, developer, plan, str(uuid.uuid4()))
    assert replay_new_key["summary"]["created"] == 0  # everything reused, nothing duplicated
    assert replay_new_key["roadmap_id"] == roadmap_id and replay_new_key["project_id"] == project_id
    tasks = (await db_session.execute(select(TaskModel))).scalars().all()
    assert sorted(t.title for t in tasks) == ["Set up the repo", "Standalone chores"]
    roadmap_rows = (await db_session.execute(select(RoadmapModel))).scalars().all()
    assert len(roadmap_rows) == 1

    # -- C. the roadmap: structure, dependencies, criteria, task links, progress ---
    draft = await _get_roadmap(client, developer, roadmap_id)
    assert draft["status"] == "draft"
    assert [p["key"] for p in draft["phases"]] == ["P1", "P2"]
    assert [s["key"] for s in draft["phases"][0]["steps"]] == ["S1", "S2"]
    assert _step(draft, "S2")["depends_on"] == ["S1"]
    assert _step(draft, "S1")["acceptance_criteria"] == ["repo builds", "CI is green"]
    setup_task = next(t for t in tasks if t.title == "Set up the repo")
    assert [link["task_id"] for link in _step(draft, "S1")["linked_tasks"]] == [str(setup_task.id)]
    active = await _transition(client, developer, draft, "activate")
    assert active["status"] == "active"
    assert active["progress"] == {"done": 0, "total": 3, "skipped": 0, "ratio": 0.0}
    assert active["current_step_key"] == "S1"
    assert Roadmap.model_validate(active).approved_revision_no == active["approved_revision_no"]

    # hydration: preview is read-only, apply is idempotent by key and by hydration key
    hyd_preview = await _post(
        client, developer, f"/api/v1/roadmaps/{roadmap_id}/hydration/preview", {}
    )
    assert hyd_preview.json()["counts"] == {"create": 1, "reuse": 0, "skip": 0}
    hydrated = dump(
        await studio_apply_roadmap_hydration(
            roadmap_id, active["version"], developer.ctx, idempotency_key=str(uuid.uuid4())
        )
    )
    assert hydrated["counts"] == {"create": 1, "reuse": 0, "skip": 0}
    again = dump(
        await studio_apply_roadmap_hydration(
            roadmap_id, active["version"], developer.ctx, idempotency_key=str(uuid.uuid4())
        )
    )
    assert again["counts"] == {"create": 0, "reuse": 1, "skip": 0}
    total_tasks = (
        await db_session.execute(select(func.count()).select_from(TaskModel))
    ).scalar_one()
    assert total_tasks == 3  # setup + chores + the hydrated core loop, never twice

    # -- D. context: a bounded slice, never the whole roadmap ----------------------
    before = await _context(agent, project_id)
    section = before["roadmap"]
    assert section["roadmap_id"] == roadmap_id and section["status"] == "active"
    # the P6 section adds only selection metadata to the frozen `RoadmapContext` slice
    extras = {"why", "status", "truncated", "objective", "task_step"}
    assert set(section) - extras <= set(RoadmapContext.model_fields)
    assert section["current_phase_key"] == "P1"
    assert section["current_step"]["key"] == "S1"
    assert section["current_step"]["linked_task_ids"] == [str(setup_task.id)]
    assert section["current_step"]["acceptance_criteria"] == ["repo builds", "CI is green"]
    assert section["blocking"] == []  # S1 is workable now: it is the current step, not a blocker
    assert "phases" not in section  # the full plan is never dumped into the context
    assert len(json.dumps(section)) < 3000

    # -- E. agent proposal: pending, nothing active moves --------------------------
    worker = await attach_agent(db_session, agent)
    proposed = await _propose_over_mcp(
        agent,
        project_id,
        active,
        _revised(S1="Set up the repo and CI"),
        agent_id=worker.id,
        summary="Clarify S1",
    )
    assert "error_code" not in proposed, proposed
    revisions = await client.get(
        f"/api/v1/roadmaps/{roadmap_id}/revisions",
        headers=developer.headers,
        params={"kind": "proposal", "status": "pending"},
    )
    (pending,) = revisions.json()
    assert pending["status"] == "pending" and pending["summary"] == "Clarify S1"
    assert pending["base_revision_no"] == active["approved_revision_no"]
    assert pending["provenance"]["origin"] == "ai_proposal"
    assert pending["provenance"]["actor_type"] == "agent"
    assert pending["provenance"]["agent_id"] == str(worker.id)
    assert pending["provenance"]["machine_id"] == str(agent.machine.id)

    unchanged = await _get_roadmap(client, developer, roadmap_id)
    assert (unchanged["version"], unchanged["revision_no"]) == (
        active["version"],
        active["revision_no"],
    )
    assert _step(unchanged, "S1")["title"] == "Set up the repo"
    assert await _context(agent, project_id) == before  # P6 never sees a pending proposal

    queue = await client.get(
        "/api/v1/review-queue", headers=developer.headers, params={"project_id": project_id}
    )
    queued = [i for i in queue.json()["items"] if i["kind"] == "roadmap_proposal"]
    assert [(i["scope"], i["revision_no"]) for i in queued] == [
        ("revision", pending["revision_no"])
    ]
    mcp_view = dump(await studio_get_roadmap(project_id, agent.ctx))
    assert [p["revision_no"] for p in mcp_view["pending_proposals"]] == [pending["revision_no"]]

    # -- F. human review: read the diff, approve -----------------------------------
    diff = await client.get(
        f"/api/v1/roadmaps/{roadmap_id}/proposals/{pending['revision_no']}/diff",
        headers=developer.headers,
    )
    assert [(e["scope"], e["key"], e["change"]) for e in diff.json()["entries"]] == [
        ("step", "S1", "changed")
    ]
    full = RoadmapRevision.model_validate(
        (
            await client.get(
                f"/api/v1/roadmaps/{roadmap_id}/revisions/{pending['revision_no']}",
                headers=developer.headers,
            )
        ).json()
    )
    assert full.content is not None and full.status is not None

    approved_response = await _review(
        client, developer, unchanged, pending["revision_no"], "approve", "Looks right"
    )
    assert approved_response.status_code == 200, approved_response.text
    approved = approved_response.json()
    assert approved["approved_revision_no"] == pending["revision_no"]
    assert approved["version"] == active["version"] + 1
    assert _step(approved, "S1")["title"] == "Set up the repo and CI"
    assert [link["task_id"] for link in _step(approved, "S1")["linked_tasks"]] == [
        str(setup_task.id)
    ]  # the plan changed, the Task links did not

    events = (await db_session.execute(select(EventModel).order_by(EventModel.seq))).scalars().all()
    approval = [e for e in events if e.event_type == "roadmap.approved"][-1]
    assert approval.payload["scope"] == "revision"
    assert approval.payload["revision_no"] == pending["revision_no"]
    assert approval.payload["comment"] == "Looks right"

    after = await _context(agent, project_id)
    assert after != before
    assert after["roadmap"]["current_step"]["title"] == "Set up the repo and CI"  # next call

    # -- I. export: the approved plan, neutral and versioned -----------------------
    exported = await client.get(f"/api/v1/roadmaps/{roadmap_id}/export", headers=admin.headers)
    assert exported.status_code == 200
    document = RoadmapDocument.model_validate(exported.json())
    assert document.format == "studio.roadmap/v1"
    assert [s.title for p in document.phases for s in p.steps] == [
        "Set up the repo and CI",
        "Implement the core loop",
        "Balance",
    ]
    assert not {"id", "status", "provenance", "linked_tasks"} & set(exported.json())
    server_pdf = await client.get(
        f"/api/v1/roadmaps/{roadmap_id}/export", headers=admin.headers, params={"format": "pdf"}
    )
    assert server_pdf.status_code == 501  # reserved contract: PDF is the client print path
    assert _detail(server_pdf)["error_code"] == "not_implemented"


# ---------------------------------------------------------------------------------
# G. review variants
# ---------------------------------------------------------------------------------
async def test_request_changes_and_reject_need_a_comment_and_leave_the_plan_alone(
    client: AsyncClient, db_session: AsyncSession, developer: Actor, agent: Actor
) -> None:
    project_id, active = await _bootstrap_active(client, developer)
    for decision, resulting in (("request_changes", "changes_requested"), ("reject", "rejected")):
        proposal = await _propose_over_mcp(
            agent, project_id, active, _revised(S3=f"Balance {decision}")
        )
        revision_no = proposal["revision_no"]

        blank = await _review(client, developer, active, revision_no, decision)
        assert blank.status_code == 422, blank.text  # a comment is mandatory
        whitespace = await _review(client, developer, active, revision_no, decision, "   ")
        assert whitespace.status_code == 422

        reviewed = await _review(client, developer, active, revision_no, decision, "Not yet")
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["version"] == active["version"]  # plan untouched
        assert _step(reviewed.json(), "S3")["title"] == "Balance"

        stored = (
            await client.get(
                f"/api/v1/roadmaps/{active['id']}/revisions/{revision_no}",
                headers=developer.headers,
            )
        ).json()
        assert stored["status"] == resulting
        assert stored["review_comment"] == "Not yet"
        assert stored["reviewed_by_user_id"] == str(developer.user_id)
        assert stored["reviewed_at"] is not None

        again = await _review(client, developer, active, revision_no, "approve")
        assert again.status_code == 409  # a decided proposal is not re-reviewable
        assert _detail(again)["error_code"] == "invalid_state"

    # neither decision ever became active content
    assert "Balance request_changes" not in json.dumps(await _context(developer, project_id))


async def test_a_stale_base_is_refused_and_the_agent_can_re_propose(
    client: AsyncClient, developer: Actor, agent: Actor
) -> None:
    project_id, active = await _bootstrap_active(client, developer)
    first = await _propose_over_mcp(agent, project_id, active, _revised(S1="One"))
    # a second proposal on the same base supersedes the first one
    second = await _propose_over_mcp(agent, project_id, active, _revised(S1="Two"))
    assert first["revision_no"] != second["revision_no"]
    superseded = await client.get(
        f"/api/v1/roadmaps/{active['id']}/revisions/{first['revision_no']}",
        headers=developer.headers,
    )
    assert superseded.json()["status"] == "superseded"
    assert (
        await _review(client, developer, active, first["revision_no"], "approve")
    ).status_code == 409

    approved = await _review(client, developer, active, second["revision_no"], "approve")
    assert approved.status_code == 200, approved.text

    # a proposal written against the old base can no longer be applied
    stale = await _propose_over_mcp(agent, project_id, active, _revised(S1="Three"))
    assert stale["base_revision_no"] == active["approved_revision_no"]
    current = await _get_roadmap(client, developer, active["id"])
    refused = await _review(client, developer, current, stale["revision_no"], "approve")
    assert refused.status_code == 409
    assert _detail(refused)["error_code"] == "base_revision_stale"
    assert _detail(refused)["server_revision_no"] == current["approved_revision_no"]
    assert _step(await _get_roadmap(client, developer, active["id"]), "S1")["title"] == "Two"

    # the agent re-reads the approved base and re-proposes: this one applies
    fresh = await _propose_over_mcp(agent, project_id, current, _revised(S1="Three"))
    latest = await _get_roadmap(client, developer, active["id"])
    assert (
        await _review(client, developer, latest, fresh["revision_no"], "approve")
    ).status_code == 200

    # a stale roadmap `expected_version` is refused as well, never applied blindly
    late = await _propose_over_mcp(
        agent, project_id, await _get_roadmap(client, developer, active["id"]), _revised(S1="Four")
    )
    outdated = await _review(client, developer, latest, late["revision_no"], "approve")
    assert outdated.status_code == 409
    assert _detail(outdated)["error_code"] == "version_conflict"


async def test_review_and_lifecycle_permissions(
    client: AsyncClient,
    db_session: AsyncSession,
    developer: Actor,
    admin: Actor,
    agent: Actor,
    readonly: Actor,
) -> None:
    project_id, active = await _bootstrap_active(client, developer)
    proposal = await _propose_over_mcp(agent, project_id, active, _revised(S3="Balanced"))
    number = proposal["revision_no"]

    for outsider in (agent, readonly):
        denied = await _review(client, outsider, active, number, "approve")
        assert denied.status_code == 403, (outsider.role, denied.text)
        denied_reject = await _review(client, outsider, active, number, "reject", "no")
        assert denied_reject.status_code == 403
    for outsider in (agent, readonly):
        blocked = await _post(
            client,
            outsider,
            f"/api/v1/roadmaps/{active['id']}/transitions",
            {"transition": "archive", "expected_version": active["version"]},
        )
        assert blocked.status_code == 403, (outsider.role, blocked.text)

    readonly_proposal = await _post(
        client,
        readonly,
        f"/api/v1/roadmaps/{active['id']}/proposals",
        {
            "base_revision_no": active["approved_revision_no"],
            "document": _revised(S3="X"),
        },
    )
    assert readonly_proposal.status_code == 403
    # every read stays open to an authenticated machine, whatever its role
    assert (
        await client.get(
            f"/api/v1/roadmaps/{active['id']}/proposals/{number}/diff", headers=readonly.headers
        )
    ).status_code == 200

    # the proposal is still pending and unapplied; an admin may review it
    assert _step(await _get_roadmap(client, developer, active["id"]), "S3")["title"] == "Balance"
    assert (await _review(client, admin, active, number, "approve")).status_code == 200


# ---------------------------------------------------------------------------------
# Provenance and the role-based review boundary
# ---------------------------------------------------------------------------------
async def test_provenance_survives_the_human_approval(
    client: AsyncClient, db_session: AsyncSession, developer: Actor, agent: Actor
) -> None:
    project_id, active = await _bootstrap_active(client, developer)
    worker = await attach_agent(db_session, agent)
    changed = _revised(S3="Balanced")
    changed["phases"][1]["steps"].append({"key": "S4", "title": "Ship", "depends_on": ["S3"]})
    proposal = await _propose_over_mcp(
        agent, project_id, active, changed, agent_id=worker.id, summary="Rename S3, add S4"
    )
    revision_no = proposal["revision_no"]
    base = active["approved_revision_no"]

    approved = await _review(client, developer, active, revision_no, "approve", "ok")
    assert approved.status_code == 200, approved.text

    revision = RoadmapRevision.model_validate(
        (
            await client.get(
                f"/api/v1/roadmaps/{active['id']}/revisions/{revision_no}",
                headers=developer.headers,
            )
        ).json()
    )
    # who proposed it, and from where -- untouched by the approval
    proposed_by: Provenance = revision.provenance
    assert proposed_by.origin.value == "ai_proposal"
    assert proposed_by.actor_type == "agent"
    assert proposed_by.actor_id == worker.id and proposed_by.agent_id == worker.id
    assert proposed_by.machine_id == agent.machine.id
    # what was decided, by whom, with which comment, against which base
    assert revision.status is not None and revision.status.value == "approved"
    assert revision.reviewed_by_user_id == developer.user_id
    assert revision.reviewed_at is not None and revision.review_comment == "ok"
    assert revision.base_revision_no == base
    assert revision.summary == "Rename S3, add S4"
    # the resulting revision is the proposal itself, now the approved one
    resulting = await _get_roadmap(client, developer, active["id"])
    assert resulting["approved_revision_no"] == resulting["revision_no"] == revision_no
    # a step the AI *created* keeps the AI origin after the human approval; a step it merely
    # edited keeps its creator, the edit itself being attributed by the revision above
    created_step = _step(resulting, "S4")["provenance"]
    assert created_step["origin"] == "ai_proposal"
    assert created_step["actor_type"] == "agent" and created_step["agent_id"] == str(worker.id)
    assert _step(resulting, "S3")["title"] == "Balanced"
    assert _step(resulting, "S3")["provenance"]["origin"] == "manual"
    # ...and the audit trail names the human reviewer as the actor of the approval
    events = (await db_session.execute(select(EventModel).order_by(EventModel.seq))).scalars().all()
    approval = [e for e in events if e.event_type == "roadmap.approved"][-1]
    assert approval.machine_id == developer.machine.id
    assert approval.actor_id == developer.user_id
    proposal_event = [e for e in events if e.event_type == "roadmap.proposed"][-1]
    assert proposal_event.machine_id == agent.machine.id
    # history keeps both: the baseline revision and the approved proposal
    kinds = (
        await db_session.execute(
            select(RoadmapRevisionModel.revision_no, RoadmapRevisionModel.status).where(
                RoadmapRevisionModel.roadmap_id == uuid.UUID(active["id"])
            )
        )
    ).all()
    assert (revision_no, "approved") in {(n, s) for n, s in kinds}


async def test_review_boundary_is_the_role_not_the_identity_of_the_proposer(
    client: AsyncClient, db_session: AsyncSession, developer: Actor, agent: Actor
) -> None:
    """DEC-0085/0089: the boundary is the authenticated *role* (`admin`/`developer`
    review, `agent`/`readonly` never do). `origin`/`agent_id` are self-declared
    provenance -- a workflow guard, "not a security boundary". So a developer
    token that proposes through a declared agent identity is still a developer
    token and may review its own proposal; what the platform guarantees is that
    the proposal stays attributable to the agent and the review to the reviewer.
    A stricter proposer/reviewer separation would be a new contract (post-P10)."""
    project_id, active = await _bootstrap_active(client, developer)
    own_agent = await attach_agent(db_session, developer, "developer-side-agent")
    proposal = await _propose_over_mcp(
        developer, project_id, active, _revised(S3="Self"), agent_id=own_agent.id
    )
    assert proposal["revision_no"]

    # the agent *role* cannot review its own -- or anybody's -- proposal
    theirs = await _propose_over_mcp(agent, project_id, active, _revised(S3="Theirs"))
    assert (
        await _review(client, agent, active, theirs["revision_no"], "approve")
    ).status_code == 403

    # a developer-role token holding the proposer's agent identity can (role-based)
    self_review = await _review(client, developer, active, theirs["revision_no"], "reject", "no")
    assert self_review.status_code == 200
    mine = await _propose_over_mcp(
        developer, project_id, active, _revised(S3="Self"), agent_id=own_agent.id
    )
    approved = await _review(client, developer, active, mine["revision_no"], "approve")
    assert approved.status_code == 200
    stored = (
        await client.get(
            f"/api/v1/roadmaps/{active['id']}/revisions/{mine['revision_no']}",
            headers=developer.headers,
        )
    ).json()
    assert stored["provenance"]["origin"] == "ai_proposal"  # attribution is not erased
    assert stored["provenance"]["agent_id"] == str(own_agent.id)
    assert stored["reviewed_by_user_id"] == str(developer.user_id)


# ---------------------------------------------------------------------------------
# "No Roadmap" is a normal state, and a Roadmap never becomes mandatory
# ---------------------------------------------------------------------------------
async def test_a_project_without_roadmap_keeps_working_everywhere(
    client: AsyncClient, developer: Actor, agent: Actor
) -> None:
    created = await _post(
        client,
        developer,
        "/api/v1/projects",
        {"slug": f"plain-{uuid.uuid4().hex[:8]}", "name": "No roadmap here"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    assert (
        await client.get(f"/api/v1/projects/{project_id}/roadmaps", headers=developer.headers)
    ).json() == []
    task = await _post(
        client, developer, "/api/v1/tasks", {"project_id": project_id, "title": "Standalone"}
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    claimed = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=developer.headers)
    assert claimed.status_code == 200 and claimed.json()["status"] == "in_progress"
    done = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers={**developer.headers, "If-Match-Version": str(claimed.json()["version"])},
        json={"status": "completed"},
    )
    assert done.status_code == 200 and done.json()["status"] == "completed"
    open_task = await _post(
        client, developer, "/api/v1/tasks", {"project_id": project_id, "title": "Standalone next"}
    )
    assert open_task.status_code == 201

    # MCP: reading a roadmap that does not exist is a normal answer, not an error
    view = dump(await studio_get_roadmap(project_id, agent.ctx))
    assert view["roadmaps"] == [] and view["active"] is None and view["pending_proposals"] == []
    assert "error_code" not in view
    # context: no roadmap key of any kind, and the standalone Task is still surfaced
    payload = await _context(agent, project_id, "finish the standalone work")
    assert not any(key.startswith("roadmap") for key in payload)
    assert "unavailable" not in payload
    assert [t["title"] for t in payload["related_tasks"]] == ["Standalone next"]

    # initialization without a roadmap section reports `skip`, it never invents one
    plan = _plan(f"plain-init-{uuid.uuid4().hex[:8]}", with_roadmap=False)
    result = await _apply_init(client, developer, plan)
    assert result["roadmap_id"] is None
    assert ("roadmap", "skip") in {(a["section"], a["action"]) for a in result["actions"]}
    empty = await _context(developer, result["project_id"], "chores")
    assert not any(key.startswith("roadmap") for key in empty)


async def test_a_roadmap_never_blocks_standalone_tasks_or_other_projects(
    client: AsyncClient, developer: Actor, agent: Actor
) -> None:
    project_id, active = await _bootstrap_active(client, developer)
    other = await _post(
        client,
        developer,
        "/api/v1/projects",
        {"slug": f"other-{uuid.uuid4().hex[:8]}", "name": "O"},
    )
    other_id = other.json()["id"]
    loose = await _post(
        client, developer, "/api/v1/tasks", {"project_id": project_id, "title": "Unlinked"}
    )
    assert loose.status_code == 201  # not tied to any step
    assert _step(await _get_roadmap(client, developer, active["id"]), "S3")["linked_tasks"] == []
    other_payload = await _context(agent, other_id)
    assert not any(key.startswith("roadmap") for key in other_payload)  # no cross-project leak
    assert active["title"] not in json.dumps(other_payload)

    # archived or draft-only projects never present a "current roadmap" either
    archived = await _transition(client, developer, active, "archive")
    assert archived["status"] == "archived"
    payload = await _context(agent, project_id)
    assert "roadmap" not in payload


# ---------------------------------------------------------------------------------
# Idempotency and concurrency across surfaces
# ---------------------------------------------------------------------------------
async def test_proposal_idempotency_key_replays_across_surfaces(
    client: AsyncClient, db_session: AsyncSession, developer: Actor, agent: Actor
) -> None:
    project_id, active = await _bootstrap_active(client, developer)
    key = str(uuid.uuid4())
    document = _revised(S3="Once")
    first = await _propose_over_mcp(agent, project_id, active, document, idempotency_key=key)
    replay = await _propose_over_mcp(agent, project_id, active, document, idempotency_key=key)
    assert replay == first  # same key + same body = the original answer

    body = {
        "base_revision_no": active["approved_revision_no"],
        "document": document,
        "summary": "over http",
    }
    http_key = {"Idempotency-Key": str(uuid.uuid4())}
    one = await _post(client, agent, f"/api/v1/roadmaps/{active['id']}/proposals", body, **http_key)
    two = await _post(client, agent, f"/api/v1/roadmaps/{active['id']}/proposals", body, **http_key)
    assert one.status_code == two.status_code == 201
    assert one.json() == two.json()
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(RoadmapRevisionModel)
            .where(
                RoadmapRevisionModel.roadmap_id == uuid.UUID(active["id"]),
                RoadmapRevisionModel.kind == "proposal",
            )
        )
    ).scalar_one()
    assert count == 2  # one per distinct key, never one per call

    # another body under a used key is a conflict, not a silent second write
    clash = await _post(
        client,
        agent,
        f"/api/v1/roadmaps/{active['id']}/proposals",
        {**body, "summary": "different body"},
        **http_key,
    )
    assert clash.status_code == 409


async def test_stale_versions_are_refused_and_never_applied_blindly(
    client: AsyncClient, developer: Actor
) -> None:
    project_id, active = await _bootstrap_active(client, developer)
    bump = await client.patch(
        f"/api/v1/roadmaps/{active['id']}",
        headers={**developer.headers, "If-Match-Version": str(active["version"])},
        json={"context": "moved on"},
    )
    assert bump.status_code == 200
    stale_hydration = dump(
        await studio_apply_roadmap_hydration(active["id"], active["version"], developer.ctx)
    )
    assert stale_hydration["error_code"] == "version_conflict"
    assert (await _get_roadmap(client, developer, active["id"]))["version"] == bump.json()[
        "version"
    ]
    stale_step = dump(
        await studio_update_roadmap_step(
            active["id"], "S1", 999, developer.ctx, notes="never written"
        )
    )
    assert stale_step["error_code"] == "version_conflict"
    assert _step(await _get_roadmap(client, developer, active["id"]), "S1")["notes"] is None


# ---------------------------------------------------------------------------------
# Initialization by an agent: propose the plan, a human validates it
# ---------------------------------------------------------------------------------
async def test_agent_initialization_is_a_proposal_a_human_validates(
    client: AsyncClient, developer: Actor, agent: Actor
) -> None:
    slug = f"agent-init-{uuid.uuid4().hex[:8]}"
    created = await _post(client, developer, "/api/v1/projects", {"slug": slug, "name": "Agent"})
    assert created.status_code == 201

    plan = _plan(slug, mode="proposed")
    preview = dump(
        await studio_preview_project_initialization(
            ProjectInitializationPlan.model_validate(plan), agent.ctx
        )
    )
    assert preview["applicable"] is True and preview["roadmap_status"] == "proposed"

    result = dump(
        await studio_apply_project_initialization(
            ProjectInitializationPlan.model_validate(plan), agent.ctx, str(uuid.uuid4())
        )
    )
    assert "error_code" not in result, result
    assert result["applied"] is True and result["roadmap_status"] == "proposed"
    assert result["provenance"]["origin"] == "ai_proposal"
    roadmap = await _get_roadmap(client, developer, result["roadmap_id"])
    assert roadmap["status"] == "proposed"
    assert roadmap["provenance"]["origin"] == "ai_proposal"
    # regression: a proposed roadmap refuses new Task links, so the plan's step-linked Task
    # is linked *before* the roadmap is submitted, and a replay must not fail on its links
    assert len(_step(roadmap, "S1")["linked_tasks"]) == 1
    replay = dump(
        await studio_apply_project_initialization(
            ProjectInitializationPlan.model_validate(plan), agent.ctx
        )
    )
    assert "error_code" not in replay, replay
    assert replay["summary"]["created"] == 0 and replay["roadmap_id"] == result["roadmap_id"]
    assert (await _get_roadmap(client, developer, roadmap["id"]))["version"] == roadmap["version"]

    # the agent role cannot validate its own plan; a human activates it
    denied = await _post(
        client,
        agent,
        f"/api/v1/roadmaps/{roadmap['id']}/transitions",
        {"transition": "approve", "expected_version": roadmap["version"]},
    )
    assert denied.status_code == 403
    approved = await _transition(client, developer, roadmap, "approve")
    assert approved["status"] == "active"
    context = await _context(agent, result["project_id"])
    assert context["roadmap"]["roadmap_id"] == roadmap["id"]
