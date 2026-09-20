"""HTTP acceptance of Roadmap proposals and human review (Roadmaps P8,
DEC-0084 §6/DEC-0085). Real Postgres through the shared savepoint fixtures:
the agent proposes on an active roadmap, a human reviews (approve / request
changes / reject), the active content only moves on approval, and a stale base
is refused instead of applied blindly.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.roadmap import RoadmapRevisionModel
from studio_contracts.roadmaps import (
    RoadmapDiff,
    RoadmapRevision,
    RoadmapRevisionSummary,
)

Headers = dict[str, str]

DOCUMENT: dict[str, Any] = {
    "format": "studio.roadmap/v1",
    "title": "Plan",
    "objective": "Ship it",
    "phases": [
        {
            "key": "P1",
            "title": "Phase one",
            "steps": [
                {
                    "key": "S1",
                    "title": "Step one",
                    "acceptance_criteria": ["a", "b"],
                },
                {"key": "S2", "title": "Step two", "depends_on": ["S1"]},
            ],
        },
        {"key": "P2", "title": "Phase two", "steps": [{"key": "S3", "title": "Step three"}]},
    ],
}


def document(**overrides: Any) -> dict[str, Any]:
    return {**copy.deepcopy(DOCUMENT), **overrides}


def step_of(roadmap: dict[str, Any], key: str) -> dict[str, Any]:
    for phase in roadmap["phases"]:
        for step in phase["steps"]:
            if step["key"] == key:
                return step  # type: ignore[no-any-return]
    raise AssertionError(f"no step {key}")


def error(response: Any) -> dict[str, Any]:
    return response.json()["detail"]  # type: ignore[no-any-return]


async def active_roadmap(
    client: AsyncClient, headers: Headers, project: ProjectModel
) -> dict[str, Any]:
    created = await client.post(
        "/api/v1/roadmaps/import",
        headers=headers,
        json={"project_id": str(project.id), "document": document()},
    )
    assert created.status_code == 201, created.text
    activated = await client.post(
        f"/api/v1/roadmaps/{created.json()['id']}/transitions",
        headers=headers,
        json={"transition": "activate", "expected_version": created.json()["version"]},
    )
    assert activated.status_code == 200, activated.text
    return activated.json()  # type: ignore[no-any-return]


async def propose(
    client: AsyncClient,
    headers: Headers,
    roadmap: dict[str, Any],
    doc: dict[str, Any],
    *,
    base: int | None = None,
    summary: str | None = "Proposed change",
    expected_status: int = 201,
) -> Any:
    response = await client.post(
        f"/api/v1/roadmaps/{roadmap['id']}/proposals",
        headers=headers,
        json={
            "base_revision_no": roadmap["approved_revision_no"] if base is None else base,
            "document": doc,
            "summary": summary,
        },
    )
    assert response.status_code == expected_status, response.text
    return response


async def review(
    client: AsyncClient,
    headers: Headers,
    roadmap: dict[str, Any],
    revision_no: int,
    decision: str,
    *,
    comment: str | None = None,
    expected_version: int | None = None,
) -> Any:
    return await client.post(
        f"/api/v1/roadmaps/{roadmap['id']}/proposals/{revision_no}/review",
        headers=headers,
        json={
            "decision": decision,
            "expected_version": roadmap["version"]
            if expected_version is None
            else expected_version,
            "comment": comment,
        },
    )


async def make_task(client: AsyncClient, headers: Headers, project: ProjectModel) -> str:
    response = await client.post(
        "/api/v1/tasks", headers=headers, json={"project_id": str(project.id), "title": "T"}
    )
    assert response.status_code == 201
    return response.json()["id"]  # type: ignore[no-any-return]


# --- proposal creation ---
async def test_agent_proposes_on_active_without_touching_the_roadmap(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    changed = document()
    changed["phases"][0]["steps"][1]["title"] = "Step two v2"

    created = await propose(client, agent_auth_headers, active, changed)
    revision = created.json()
    RoadmapRevision.model_validate(revision)
    assert revision["kind"] == "proposal"
    assert revision["status"] == "pending"
    assert revision["base_revision_no"] == active["approved_revision_no"]
    assert revision["provenance"]["origin"] == "ai_proposal"
    assert revision["provenance"]["agent_id"] is None  # a declared agent_id, not the role

    unchanged = await client.get(f"/api/v1/roadmaps/{active['id']}", headers=auth_headers)
    assert unchanged.json()["revision_no"] == active["revision_no"]
    assert step_of(unchanged.json(), "S2")["title"] == "Step two"

    events = (await db_session.execute(select(EventModel).order_by(EventModel.seq))).scalars().all()
    proposed = [event for event in events if event.event_type == "roadmap.proposed"]
    assert proposed[-1].payload["scope"] == "revision"
    assert proposed[-1].payload["revision_no"] == revision["revision_no"]


async def test_proposal_requires_an_active_roadmap(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    created = await client.post(
        "/api/v1/roadmaps/import",
        headers=auth_headers,
        json={"project_id": str(project.id), "document": document()},
    )
    draft = created.json()
    response = await propose(client, auth_headers, draft, document(), base=0, expected_status=409)
    assert error(response)["error_code"] == "invalid_state"


async def test_new_proposal_supersedes_the_pending_one(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    first = (await propose(client, agent_auth_headers, active, document())).json()
    second_doc = document()
    second_doc["title"] = "Plan v2"
    second = (
        await propose(client, agent_auth_headers, active, second_doc, summary="Second")
    ).json()
    assert second["revision_no"] > first["revision_no"]
    rows = (
        (
            await db_session.execute(
                select(RoadmapRevisionModel).where(
                    RoadmapRevisionModel.roadmap_id == uuid.UUID(active["id"])
                )
            )
        )
        .scalars()
        .all()
    )
    statuses = {row.revision_no: row.status for row in rows if row.kind == "proposal"}
    assert statuses[first["revision_no"]] == "superseded"
    assert statuses[second["revision_no"]] == "pending"


async def test_proposal_creation_is_idempotent(
    client: AsyncClient, auth_headers: Headers, agent_auth_headers: Headers, project: ProjectModel
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    changed = document()
    changed["title"] = "Idempotent"
    headers = {**agent_auth_headers, "Idempotency-Key": "p8-proposal-1"}
    payload = {
        "base_revision_no": active["approved_revision_no"],
        "document": changed,
        "summary": "x",
    }
    first = await client.post(
        f"/api/v1/roadmaps/{active['id']}/proposals", headers=headers, json=payload
    )
    second = await client.post(
        f"/api/v1/roadmaps/{active['id']}/proposals", headers=headers, json=payload
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


# --- revision reads and diff ---
async def test_list_get_revisions_and_diff(
    client: AsyncClient, auth_headers: Headers, agent_auth_headers: Headers, project: ProjectModel
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    changed = document()
    changed["phases"][0]["steps"][0]["title"] = "Step one v2"
    changed["phases"][0]["steps"][1]["depends_on"] = []
    changed["phases"][1]["steps"][0]["depends_on"] = ["S1"]
    changed["phases"][1]["steps"].append({"key": "S4", "title": "Step four"})
    revision = (await propose(client, agent_auth_headers, active, changed)).json()

    listing = await client.get(f"/api/v1/roadmaps/{active['id']}/revisions", headers=auth_headers)
    assert listing.status_code == 200
    summaries = listing.json()
    for summary in summaries:
        RoadmapRevisionSummary.model_validate(summary)
    assert summaries[0]["revision_no"] == revision["revision_no"]
    assert "content" not in summaries[0]

    only_proposals = await client.get(
        f"/api/v1/roadmaps/{active['id']}/revisions",
        headers=auth_headers,
        params={"kind": "proposal", "status": "pending"},
    )
    assert [item["revision_no"] for item in only_proposals.json()] == [revision["revision_no"]]

    single = await client.get(
        f"/api/v1/roadmaps/{active['id']}/revisions/{revision['revision_no']}",
        headers=auth_headers,
    )
    assert single.status_code == 200
    assert RoadmapRevision.model_validate(single.json()).content is not None

    diff = await client.get(
        f"/api/v1/roadmaps/{active['id']}/proposals/{revision['revision_no']}/diff",
        headers=auth_headers,
    )
    assert diff.status_code == 200
    RoadmapDiff.model_validate(diff.json())
    entries = {
        (entry["scope"], entry["key"], entry["change"]): entry for entry in diff.json()["entries"]
    }
    assert ("step", "S1", "changed") in entries
    assert ("step", "S4", "added") in entries
    assert ("dependency", "S3", "added") in entries
    assert ("dependency", "S2", "removed") in entries
    assert entries[("step", "S1", "changed")]["fields"] == ["title"]

    missing = await client.get(
        f"/api/v1/roadmaps/{active['id']}/proposals/999/diff", headers=auth_headers
    )
    assert missing.status_code == 404
    assert error(missing)["error_code"] == "reference_not_found"


# --- approval applies atomically, preserving links ---
async def test_approve_applies_by_key_and_preserves_links_and_dependencies(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    task_id = await make_task(client, auth_headers, project)
    s1 = step_of(active, "S1")
    linked = await client.post(
        f"/api/v1/roadmaps/{active['id']}/steps/S1/links",
        headers=auth_headers,
        json={"task_id": task_id},
    )
    assert linked.status_code == 201, linked.text

    changed = document()
    changed["phases"][0]["steps"][1]["title"] = "Step two reviewed"
    changed["phases"][0]["steps"][0]["acceptance_criteria"] = ["a", "b", "c"]
    revision = (await propose(client, agent_auth_headers, active, changed)).json()

    approved = await review(client, auth_headers, linked.json(), revision["revision_no"], "approve")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["revision_no"] == revision["revision_no"]
    assert body["approved_revision_no"] == revision["revision_no"]
    assert step_of(body, "S2")["title"] == "Step two reviewed"
    s1_after = step_of(body, "S1")
    assert [link["task_id"] for link in s1_after["linked_tasks"]] == [task_id]
    assert s1_after["acceptance_criteria"] == ["a", "b", "c"]
    assert s1_after["id"] == s1["id"]  # same step row, matched by key

    stored = await client.get(
        f"/api/v1/roadmaps/{active['id']}/revisions/{revision['revision_no']}",
        headers=auth_headers,
    )
    assert stored.json()["status"] == "approved"
    assert stored.json()["reviewed_by_user_id"] is not None
    assert stored.json()["reviewed_at"] is not None


async def test_approve_a_proposal_that_removes_a_linked_step_is_refused(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    task_id = await make_task(client, auth_headers, project)
    linked = await client.post(
        f"/api/v1/roadmaps/{active['id']}/steps/S1/links",
        headers=auth_headers,
        json={"task_id": task_id},
    )
    assert linked.status_code == 201, linked.text

    without_s1 = document()
    without_s1["phases"][0]["steps"] = [without_s1["phases"][0]["steps"][1]]
    without_s1["phases"][0]["steps"][0]["depends_on"] = []
    revision = (await propose(client, agent_auth_headers, active, without_s1)).json()

    response = await review(client, auth_headers, linked.json(), revision["revision_no"], "approve")
    assert response.status_code == 409
    assert error(response)["error_code"] == "step_has_links"

    still_there = await client.get(f"/api/v1/roadmaps/{active['id']}", headers=auth_headers)
    assert step_of(still_there.json(), "S1")["title"] == "Step one"


# --- review decisions and permissions ---
async def test_request_changes_requires_a_comment_and_leaves_the_roadmap(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    changed = document()
    changed["title"] = "Renamed"
    revision = (await propose(client, agent_auth_headers, active, changed)).json()

    no_comment = await review(
        client, auth_headers, active, revision["revision_no"], "request_changes"
    )
    assert no_comment.status_code == 422

    decided = await review(
        client,
        auth_headers,
        active,
        revision["revision_no"],
        "request_changes",
        comment="Please split S1",
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["revision_no"] == active["revision_no"]
    stored = await client.get(
        f"/api/v1/roadmaps/{active['id']}/revisions/{revision['revision_no']}",
        headers=auth_headers,
    )
    assert stored.json()["status"] == "changes_requested"
    assert stored.json()["review_comment"] == "Please split S1"


async def test_reject_requires_a_comment(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    changed = document()
    changed["title"] = "Rejected plan"
    revision = (await propose(client, agent_auth_headers, active, changed)).json()

    no_comment = await review(client, auth_headers, active, revision["revision_no"], "reject")
    assert no_comment.status_code == 422

    decided = await review(
        client, auth_headers, active, revision["revision_no"], "reject", comment="Out of scope"
    )
    assert decided.status_code == 200, decided.text
    events = (await db_session.execute(select(EventModel).order_by(EventModel.seq))).scalars().all()
    rejected = [event for event in events if event.event_type == "roadmap.rejected"]
    assert rejected[-1].payload["scope"] == "revision"
    assert rejected[-1].payload["comment"] == "Out of scope"


async def test_agent_and_readonly_cannot_review_their_own_proposal(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    readonly_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    changed = document()
    changed["title"] = "Agent plan"
    revision = (await propose(client, agent_auth_headers, active, changed)).json()

    denied_agent = await review(
        client, agent_auth_headers, active, revision["revision_no"], "approve"
    )
    assert denied_agent.status_code == 403
    assert error(denied_agent) == {
        "error_code": "forbidden",
        "resource": "roadmap",
        "action": "provision",
    }

    denied_readonly = await review(
        client, readonly_auth_headers, active, revision["revision_no"], "approve"
    )
    assert denied_readonly.status_code == 403

    still_pending = await client.get(
        f"/api/v1/roadmaps/{active['id']}/revisions/{revision['revision_no']}",
        headers=auth_headers,
    )
    assert still_pending.json()["status"] == "pending"


async def test_stale_base_is_refused_instead_of_applied(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    changed = document()
    changed["title"] = "Agent version"
    revision = (await propose(client, agent_auth_headers, active, changed)).json()

    human = await client.patch(
        f"/api/v1/roadmaps/{active['id']}/steps/S2",
        headers={
            **auth_headers,
            "If-Match-Version": str(step_of(active, "S2")["version"]),
        },
        json={"title": "Human edit"},
    )
    assert human.status_code == 200, human.text
    assert human.json()["approved_revision_no"] != revision["base_revision_no"]

    stale = await review(
        client,
        auth_headers,
        human.json(),
        revision["revision_no"],
        "approve",
        expected_version=human.json()["version"],
    )
    assert stale.status_code == 409, stale.text
    assert error(stale)["error_code"] == "base_revision_stale"
    assert error(stale)["server_revision_no"] == human.json()["approved_revision_no"]

    unchanged = await client.get(f"/api/v1/roadmaps/{active['id']}", headers=auth_headers)
    assert step_of(unchanged.json(), "S2")["title"] == "Human edit"


async def test_review_stale_expected_version_is_a_conflict(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    revision = (await propose(client, agent_auth_headers, active, document())).json()
    response = await review(
        client, auth_headers, active, revision["revision_no"], "approve", expected_version=999
    )
    assert response.status_code == 409
    assert error(response)["error_code"] == "version_conflict"


async def test_agent_id_provenance_must_belong_to_the_calling_machine(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel, agent: AgentModel
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    owned = await client.post(
        f"/api/v1/roadmaps/{active['id']}/proposals",
        headers=auth_headers,
        json={
            "base_revision_no": active["approved_revision_no"],
            "document": document(),
            "provenance": {"origin": "ai_proposal", "agent_id": str(agent.id)},
        },
    )
    assert owned.status_code == 201, owned.text
    assert owned.json()["provenance"]["agent_id"] == str(agent.id)

    foreign = await client.post(
        f"/api/v1/roadmaps/{active['id']}/proposals",
        headers=auth_headers,
        json={
            "base_revision_no": active["approved_revision_no"],
            "document": document(),
            "provenance": {"agent_id": str(uuid.uuid4())},
        },
    )
    assert foreign.status_code == 409
    assert error(foreign)["error_code"] == "actor_not_owned"


async def test_direct_agent_content_write_points_at_the_proposal_endpoint(
    client: AsyncClient, auth_headers: Headers, agent_auth_headers: Headers, project: ProjectModel
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    step = step_of(active, "S2")
    refused = await client.patch(
        f"/api/v1/roadmaps/{active['id']}/steps/S2",
        headers={**agent_auth_headers, "If-Match-Version": str(step["version"])},
        json={"title": "Agent rewrite"},
    )
    assert refused.status_code == 409
    assert error(refused)["error_code"] == "invalid_state"
    assert f"/roadmaps/{active['id']}/proposals" in error(refused)["message"]


async def test_review_queue_surfaces_both_proposal_scopes(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    revision = (await propose(client, agent_auth_headers, active, document())).json()

    queue = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert queue.status_code == 200
    items = [item for item in queue.json()["items"] if item["kind"] == "roadmap_proposal"]
    scopes = {(item["scope"], item["roadmap_id"]) for item in items}
    assert scopes == {("revision", active["id"])}
    revision_item = next(item for item in items if item["scope"] == "revision")
    assert revision_item["revision_no"] == revision["revision_no"]
    assert revision_item["base_revision_no"] == revision["base_revision_no"]
    assert revision_item["title"] == active["title"]

    # a whole roadmap submitted for first validation is the other scope
    created = await client.post(
        "/api/v1/roadmaps/import",
        headers=auth_headers,
        json={"project_id": str(project.id), "document": document(), "submit": True},
    )
    assert created.status_code == 201, created.text
    queue_again = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    scopes_again = {
        item["scope"] for item in queue_again.json()["items"] if item["kind"] == "roadmap_proposal"
    }
    assert scopes_again == {"roadmap", "revision"}


async def test_proposal_document_must_be_valid(
    client: AsyncClient, auth_headers: Headers, agent_auth_headers: Headers, project: ProjectModel
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    invalid = document()
    invalid["phases"][0]["steps"][0]["depends_on"] = ["S2"]
    invalid["phases"][0]["steps"][1]["depends_on"] = ["S1"]
    response = await propose(client, agent_auth_headers, active, invalid, expected_status=422)
    assert error(response)["error_code"] == "invalid_roadmap"
    assert error(response)["reason"] == "dependency_cycle"


async def test_a_proposal_cannot_be_reviewed_once_the_roadmap_left_active(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    changed = document()
    changed["title"] = "Pending"
    revision = (await propose(client, agent_auth_headers, active, changed)).json()

    completed = await client.post(
        f"/api/v1/roadmaps/{active['id']}/transitions",
        headers=auth_headers,
        json={"transition": "complete", "expected_version": active["version"]},
    )
    assert completed.status_code == 200, completed.text

    refused = await review(
        client, auth_headers, completed.json(), revision["revision_no"], "approve"
    )
    assert refused.status_code == 409
    assert error(refused)["error_code"] == "invalid_state"
    assert error(refused)["status"] == "completed"
    unchanged = await client.get(f"/api/v1/roadmaps/{active['id']}", headers=auth_headers)
    assert unchanged.json()["title"] == active["title"]


async def test_revision_numbers_never_collide_between_a_proposal_and_a_snapshot(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    first = (await propose(client, agent_auth_headers, active, document())).json()

    human = await client.patch(
        f"/api/v1/roadmaps/{active['id']}/steps/S2",
        headers={**auth_headers, "If-Match-Version": str(step_of(active, "S2")["version"])},
        json={"title": "Human edit"},
    )
    assert human.status_code == 200, human.text
    assert human.json()["approved_revision_no"] != first["revision_no"]

    revisions = (
        await client.get(f"/api/v1/roadmaps/{active['id']}/revisions", headers=auth_headers)
    ).json()
    numbers = [item["revision_no"] for item in revisions]
    assert len(numbers) == len(set(numbers)), numbers

    exported = await client.get(f"/api/v1/roadmaps/{active['id']}/export", headers=auth_headers)
    identical = (await propose(client, agent_auth_headers, human.json(), exported.json())).json()
    diff = await client.get(
        f"/api/v1/roadmaps/{active['id']}/proposals/{identical['revision_no']}/diff",
        headers=auth_headers,
    )
    assert diff.status_code == 200, diff.text
    assert diff.json()["base_revision_no"] == human.json()["approved_revision_no"]
    assert diff.json()["entries"] == []


async def test_unknown_roadmap_and_revision_are_structured_404(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    unknown_roadmap = await client.post(
        f"/api/v1/roadmaps/{uuid.uuid4()}/proposals",
        headers=auth_headers,
        json={"base_revision_no": 1, "document": document()},
    )
    assert unknown_roadmap.status_code == 404
    assert error(unknown_roadmap)["error_code"] == "not_found"
    unknown_revision = await review(client, auth_headers, active, 999, "approve")
    assert unknown_revision.status_code == 404
    assert error(unknown_revision)["error_code"] == "reference_not_found"
