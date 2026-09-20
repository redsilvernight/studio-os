"""HTTP acceptance of the Roadmap domain (Roadmaps P2 + P3, DEC-0084/0085/0086).

Real Postgres through the shared savepoint fixtures. Covers: lifecycle and
authority, the write matrix, structure/order/dependencies, Step<->Task links
and derived progress, idempotent hydration, import/export, provenance, events,
permissions and the OpenAPI surface.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.roadmap import RoadmapRevisionModel
from studio_api.db.models.task import TaskModel
from studio_api.main import app
from studio_contracts.roadmaps import Roadmap, RoadmapDocument

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
                    "tasks": [
                        {"hydration_key": "t1", "title": "Task one"},
                        {"hydration_key": "t2", "title": "Task two"},
                    ],
                },
                {
                    "key": "S2",
                    "title": "Step two",
                    "depends_on": ["S1"],
                    "acceptance_criteria": ["first", "second"],
                },
            ],
        },
        {"key": "P2", "title": "Phase two", "steps": [{"key": "S3", "title": "Step three"}]},
    ],
}


def document(**overrides: Any) -> dict[str, Any]:
    return {**copy.deepcopy(DOCUMENT), **overrides}


async def import_roadmap(
    client: AsyncClient,
    headers: Headers,
    project: ProjectModel,
    doc: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/roadmaps/import",
        headers=headers,
        json={"project_id": str(project.id), "document": doc or document(), **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def transition(
    client: AsyncClient,
    headers: Headers,
    roadmap: dict[str, Any],
    name: str,
    comment: str | None = None,
) -> Any:
    return await client.post(
        f"/api/v1/roadmaps/{roadmap['id']}/transitions",
        headers=headers,
        json={"transition": name, "expected_version": roadmap["version"], "comment": comment},
    )


async def active_roadmap(
    client: AsyncClient, headers: Headers, project: ProjectModel, doc: dict[str, Any] | None = None
) -> dict[str, Any]:
    roadmap = await import_roadmap(client, headers, project, doc)
    response = await transition(client, headers, roadmap, "activate")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    return response.json()  # type: ignore[no-any-return]


async def get(client: AsyncClient, headers: Headers, roadmap_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/roadmaps/{roadmap_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def step_of(roadmap: dict[str, Any], key: str) -> dict[str, Any]:
    for phase in roadmap["phases"]:
        for step in phase["steps"]:
            if step["key"] == key:
                return step  # type: ignore[no-any-return]
    raise AssertionError(f"no step {key}")


def error(response: Any) -> dict[str, Any]:
    return response.json()["detail"]  # type: ignore[no-any-return]


async def make_task(client: AsyncClient, headers: Headers, project: ProjectModel) -> str:
    response = await client.post(
        "/api/v1/tasks", headers=headers, json={"project_id": str(project.id), "title": "T"}
    )
    assert response.status_code == 201
    return response.json()["id"]  # type: ignore[no-any-return]


# --- creation, import, export ---
async def test_create_empty_draft_and_list_by_status(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    created = await client.post(
        "/api/v1/roadmaps",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Empty", "metadata": {"k": 1}},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    Roadmap.model_validate(body)
    assert body["status"] == "draft"
    assert body["version"] == 1
    assert body["revision_no"] == 0
    assert body["phases"] == []
    assert body["progress"] == {"done": 0, "total": 0, "skipped": 0, "ratio": 1.0}
    assert body["provenance"]["actor_type"] == "user"

    listing = await client.get(f"/api/v1/projects/{project.id}/roadmaps", headers=auth_headers)
    assert [item["id"] for item in listing.json()] == [body["id"]]
    assert "phases" not in listing.json()[0]
    none = await client.get(
        f"/api/v1/projects/{project.id}/roadmaps",
        headers=auth_headers,
        params={"status": "active"},
    )
    assert none.json() == []


async def test_unknown_ids_are_structured_404(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    missing = await client.get(f"/api/v1/roadmaps/{uuid.uuid4()}", headers=auth_headers)
    assert missing.status_code == 404
    assert error(missing)["error_code"] == "not_found"
    no_project = await client.post(
        "/api/v1/roadmaps",
        headers=auth_headers,
        json={"project_id": str(uuid.uuid4()), "title": "X"},
    )
    assert no_project.status_code == 404
    assert error(no_project)["error_code"] == "reference_not_found"
    listing = await client.get(f"/api/v1/projects/{uuid.uuid4()}/roadmaps", headers=auth_headers)
    assert listing.status_code == 404


async def test_import_builds_plan_without_creating_tasks(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel, db_session: AsyncSession
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    assert roadmap["status"] == "draft"
    assert [phase["key"] for phase in roadmap["phases"]] == ["P1", "P2"]
    assert [phase["position"] for phase in roadmap["phases"]] == [0, 1]
    s1, s2, s3 = (step_of(roadmap, key) for key in ("S1", "S2", "S3"))
    assert [step["position"] for step in roadmap["phases"][0]["steps"]] == [0, 1]
    assert s2["depends_on"] == ["S1"]
    assert [item["hydration_key"] for item in s1["tasks"]] == ["t1", "t2"]
    assert s1["linked_tasks"] == []
    assert s2["waiting_on"] == ["S1"]
    assert s2["available"] is False
    assert s1["available"] and s3["available"]
    assert roadmap["current_step_key"] == "S1"
    assert roadmap["provenance"]["origin"] == "import"
    tasks = (await db_session.execute(select(TaskModel))).scalars().all()
    assert tasks == []


async def test_import_invalid_document_is_422_invalid_roadmap_and_writes_nothing(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    cyclic = document()
    cyclic["phases"][0]["steps"][0]["depends_on"] = ["S2"]
    response = await client.post(
        "/api/v1/roadmaps/import",
        headers=auth_headers,
        json={"project_id": str(project.id), "document": cyclic},
    )
    assert response.status_code == 422
    assert error(response)["error_code"] == "invalid_roadmap"
    assert error(response)["reason"] == "dependency_cycle"

    duplicate = document()
    duplicate["phases"][1]["steps"][0]["key"] = "S1"
    response = await client.post(
        "/api/v1/roadmaps/import",
        headers=auth_headers,
        json={"project_id": str(project.id), "document": duplicate},
    )
    assert error(response)["reason"] == "duplicate_step_key"

    listing = await client.get(f"/api/v1/projects/{project.id}/roadmaps", headers=auth_headers)
    assert listing.json() == []


async def test_import_rejects_unknown_format_and_extra_fields(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    for bad in (
        document(format="studio.roadmap/v2"),
        {**document(), "provider": "x"},
    ):
        response = await client.post(
            "/api/v1/roadmaps/import",
            headers=auth_headers,
            json={"project_id": str(project.id), "document": bad},
        )
        assert response.status_code == 422


async def test_import_submit_creates_proposed_with_frozen_proposal_revision(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel, db_session: AsyncSession
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project, submit=True)
    assert roadmap["status"] == "proposed"
    assert roadmap["revision_no"] == 1
    revisions = (
        (
            await db_session.execute(
                select(RoadmapRevisionModel).where(
                    RoadmapRevisionModel.roadmap_id == uuid.UUID(roadmap["id"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(r.kind, r.status, r.revision_no) for r in revisions] == [("proposal", "pending", 1)]
    assert revisions[0].content is not None
    RoadmapDocument.model_validate(revisions[0].content)


async def test_export_round_trips_the_neutral_document(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    exported = await client.get(f"/api/v1/roadmaps/{roadmap['id']}/export", headers=auth_headers)
    assert exported.status_code == 200
    body = exported.json()
    assert body["format"] == "studio.roadmap/v1"
    assert body["exported_at"] is not None
    assert body["revision_no"] == roadmap["revision_no"]
    for stamp in ("exported_at", "revision_no"):
        body.pop(stamp)
    assert _strip_empty(body) == _strip_empty(document())

    reimported = await client.post(
        "/api/v1/roadmaps/import",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "document": exported.json(),
        },
    )
    assert reimported.status_code == 201, reimported.text
    assert reimported.json()["id"] != roadmap["id"]

    pdf = await client.get(
        f"/api/v1/roadmaps/{roadmap['id']}/export", headers=auth_headers, params={"format": "pdf"}
    )
    assert pdf.status_code == 501


def _strip_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_empty(v) for k, v in value.items() if v not in (None, [], {})}
    if isinstance(value, list):
        return [_strip_empty(item) for item in value]
    return value


async def test_create_and_import_are_idempotent_and_reject_payload_mismatch(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    payload = {"project_id": str(project.id), "document": document()}
    first = await client.post("/api/v1/roadmaps/import", headers=headers, json=payload)
    second = await client.post("/api/v1/roadmaps/import", headers=headers, json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    mismatch = await client.post(
        "/api/v1/roadmaps/import",
        headers=headers,
        json={**payload, "document": document(title="Other")},
    )
    assert mismatch.status_code == 409
    assert error(mismatch)["error_code"] == "idempotency_key_payload_mismatch"
    listing = await client.get(f"/api/v1/projects/{project.id}/roadmaps", headers=auth_headers)
    assert len(listing.json()) == 1


# --- header edit ---
async def test_patch_header_semantics_and_version_conflict(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    url = f"/api/v1/roadmaps/{roadmap['id']}"
    ok = await client.patch(
        url,
        headers={**auth_headers, "If-Match-Version": str(roadmap["version"])},
        json={"title": "Renamed", "objective": "", "metadata": {"a": "b"}},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["title"] == "Renamed"
    assert ok.json()["objective"] is None
    assert ok.json()["metadata"] == {"a": "b"}
    assert ok.json()["version"] == roadmap["version"] + 1
    assert ok.json()["revision_no"] == 0  # draft edits make no revision

    stale = await client.patch(
        url,
        headers={**auth_headers, "If-Match-Version": str(roadmap["version"])},
        json={"title": "Lost"},
    )
    assert stale.status_code == 409
    assert error(stale) == {
        "error_code": "version_conflict",
        "server_version": ok.json()["version"],
    }
    cleared = await client.patch(
        url,
        headers={**auth_headers, "If-Match-Version": str(ok.json()["version"])},
        json={"metadata": {}},
    )
    assert cleared.json()["metadata"] == {}
    assert cleared.json()["title"] == "Renamed"


# --- lifecycle and authority ---
async def test_full_lifecycle_with_comments_snapshots_and_events(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel, db_session: AsyncSession
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)

    proposed = await transition(client, auth_headers, roadmap, "submit")
    assert proposed.status_code == 200 and proposed.json()["status"] == "proposed"
    assert proposed.json()["revision_no"] == 1

    no_comment = await client.post(
        f"/api/v1/roadmaps/{roadmap['id']}/transitions",
        headers=auth_headers,
        json={"transition": "request_changes", "expected_version": proposed.json()["version"]},
    )
    assert no_comment.status_code == 422

    back = await transition(client, auth_headers, proposed.json(), "request_changes", "Split S1")
    assert back.json()["status"] == "draft"

    again = await transition(client, auth_headers, back.json(), "submit")
    approved = await transition(client, auth_headers, again.json(), "approve")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "active"
    assert body["approved_revision_no"] == 2 == body["revision_no"]

    completed = await transition(client, auth_headers, body, "complete")
    assert completed.json()["status"] == "completed"
    no_reason = await client.post(
        f"/api/v1/roadmaps/{roadmap['id']}/transitions",
        headers=auth_headers,
        json={"transition": "reopen", "expected_version": completed.json()["version"]},
    )
    assert no_reason.status_code == 422
    reopened = await transition(client, auth_headers, completed.json(), "reopen", "Missed a bit")
    assert reopened.json()["status"] == "active"
    archived = await transition(client, auth_headers, reopened.json(), "archive")
    assert archived.json()["status"] == "archived"
    terminal = await transition(client, auth_headers, archived.json(), "reopen", "no")
    assert terminal.status_code == 409
    assert error(terminal)["error_code"] == "invalid_state"
    assert error(terminal)["status"] == "archived"

    revisions = (
        (
            await db_session.execute(
                select(RoadmapRevisionModel)
                .where(RoadmapRevisionModel.roadmap_id == uuid.UUID(roadmap["id"]))
                .order_by(RoadmapRevisionModel.revision_no)
            )
        )
        .scalars()
        .all()
    )
    assert [(r.kind, r.status) for r in revisions] == [
        ("proposal", "changes_requested"),
        ("proposal", "approved"),
    ]
    assert revisions[0].review_comment == "Split S1"

    events = (
        (
            await db_session.execute(
                select(EventModel)
                .where(EventModel.project_id == project.id)
                .order_by(EventModel.seq)
            )
        )
        .scalars()
        .all()
    )
    kinds = [event.event_type for event in events]
    assert kinds == [
        "roadmap.created",
        "roadmap.proposed",
        "roadmap.changes_requested",
        "roadmap.proposed",
        "roadmap.approved",
        "roadmap.activated",
        "roadmap.completed",
        "roadmap.activated",
        "roadmap.archived",
    ]
    approved_event = events[4]
    assert approved_event.payload["scope"] == "roadmap"
    assert approved_event.payload["roadmap_id"] == roadmap["id"]
    assert approved_event.actor_type == "user"


async def test_direct_activation_snapshots_and_activate_twice_is_a_noop(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel, db_session: AsyncSession
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    assert active["revision_no"] == 1
    assert active["approved_revision_no"] == 1
    again = await transition(client, auth_headers, {**active, "version": 999}, "activate")
    assert again.status_code == 200
    assert again.json()["version"] == active["version"]
    snapshots = (
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
    assert [r.kind for r in snapshots] == ["snapshot"]


async def test_only_one_active_roadmap_per_project(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    first = await active_roadmap(client, auth_headers, project)
    second = await import_roadmap(client, auth_headers, project)
    blocked = await transition(client, auth_headers, second, "activate")
    assert blocked.status_code == 409
    assert error(blocked)["error_code"] == "active_roadmap_exists"
    done = await transition(client, auth_headers, first, "complete")
    assert done.status_code == 200
    assert (await transition(client, auth_headers, second, "activate")).status_code == 200


async def test_transition_authority_agent_role_writes_but_never_validates(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    readonly_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    roadmap = await import_roadmap(client, agent_auth_headers, project)  # writer may create
    assert roadmap["status"] == "draft"
    denied = await transition(client, agent_auth_headers, roadmap, "activate")
    assert denied.status_code == 403
    assert error(denied) == {
        "error_code": "forbidden",
        "resource": "roadmap",
        "action": "provision",
    }
    submitted = await transition(client, agent_auth_headers, roadmap, "submit")
    assert submitted.status_code == 200 and submitted.json()["status"] == "proposed"
    approve = await transition(client, agent_auth_headers, submitted.json(), "approve")
    assert approve.status_code == 403
    read_only = await transition(client, readonly_auth_headers, submitted.json(), "approve")
    assert read_only.status_code == 403
    assert (await transition(client, auth_headers, submitted.json(), "approve")).status_code == 200


async def test_invalid_transition_and_stale_version(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    invalid = await transition(client, auth_headers, roadmap, "complete")
    assert invalid.status_code == 409
    assert error(invalid)["error_code"] == "invalid_state"
    assert error(invalid)["transition"] == "complete"
    stale = await transition(client, auth_headers, {**roadmap, "version": 77}, "submit")
    assert stale.status_code == 409
    assert error(stale) == {"error_code": "version_conflict", "server_version": roadmap["version"]}


# --- write matrix ---
async def test_write_matrix_by_status(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    proposed = (await transition(client, auth_headers, roadmap, "submit")).json()
    step = step_of(proposed, "S1")
    for method, url, body in (
        ("PATCH", "/steps/S1", {"title": "x"}),
        ("PATCH", "/steps/S1/progress", {"notes": "x"}),
    ):
        response = await client.request(
            method,
            f"/api/v1/roadmaps/{proposed['id']}{url}",
            headers={**auth_headers, "If-Match-Version": str(step["version"])},
            json=body,
        )
        assert response.status_code == 409, response.text
        assert error(response)["error_code"] == "invalid_state"
        assert error(response)["status"] == "proposed"
    phase = await client.post(
        f"/api/v1/roadmaps/{proposed['id']}/phases",
        headers=auth_headers,
        json={"key": "P3", "title": "x", "expected_roadmap_version": proposed["version"]},
    )
    assert phase.status_code == 409

    done = (await transition(client, auth_headers, proposed, "approve")).json()
    closed = (await transition(client, auth_headers, done, "complete")).json()
    progress = await client.patch(
        f"/api/v1/roadmaps/{closed['id']}/steps/S1/progress",
        headers={**auth_headers, "If-Match-Version": str(step["version"])},
        json={"notes": "late"},
    )
    assert progress.status_code == 409
    assert error(progress)["status"] == "completed"


async def test_agent_content_write_on_active_is_refused_but_progress_is_direct(
    client: AsyncClient,
    auth_headers: Headers,
    agent_auth_headers: Headers,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    step = step_of(active, "S2")
    content = await client.patch(
        f"/api/v1/roadmaps/{active['id']}/steps/S2",
        headers={**agent_auth_headers, "If-Match-Version": str(step["version"])},
        json={"title": "Agent rewrite"},
    )
    assert content.status_code == 409
    assert error(content)["error_code"] == "invalid_state"
    assert "proposal" in error(content)["message"]

    declared = await client.patch(
        f"/api/v1/roadmaps/{active['id']}/steps/S2",
        headers={**auth_headers, "If-Match-Version": str(step["version"])},
        json={"title": "Human but declared ai", "provenance": {"origin": "ai_proposal"}},
    )
    assert declared.status_code == 409  # a declared ai_proposal is an agent write

    progress = await client.patch(
        f"/api/v1/roadmaps/{active['id']}/steps/S2/progress",
        headers={**agent_auth_headers, "If-Match-Version": str(step["version"])},
        json={"criteria_checked": [0], "notes": "half done"},
    )
    assert progress.status_code == 200, progress.text
    assert step_of(progress.json(), "S2")["criteria_checked"] == [0]
    assert progress.json()["revision_no"] == active["revision_no"]  # no snapshot

    human = await client.patch(
        f"/api/v1/roadmaps/{active['id']}/steps/S2",
        headers={
            **auth_headers,
            "If-Match-Version": str(step_of(progress.json(), "S2")["version"]),
        },
        json={"title": "Human rewrite"},
    )
    assert human.status_code == 200
    assert human.json()["revision_no"] == active["revision_no"] + 1
    assert human.json()["approved_revision_no"] == human.json()["revision_no"]
    snapshot = (
        await db_session.execute(
            select(RoadmapRevisionModel).where(
                RoadmapRevisionModel.roadmap_id == uuid.UUID(active["id"]),
                RoadmapRevisionModel.revision_no == human.json()["revision_no"],
            )
        )
    ).scalar_one()
    assert snapshot.kind == "snapshot"
    assert snapshot.content is not None
    assert "Human rewrite" in json.dumps(snapshot.content)


async def test_readonly_reads_everything_and_writes_nothing(
    client: AsyncClient,
    auth_headers: Headers,
    readonly_auth_headers: Headers,
    project: ProjectModel,
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    for path in ("", "/export"):
        read = await client.get(
            f"/api/v1/roadmaps/{active['id']}{path}", headers=readonly_auth_headers
        )
        assert read.status_code == 200
    preview = await client.post(
        f"/api/v1/roadmaps/{active['id']}/hydration/preview",
        headers=readonly_auth_headers,
        json={},
    )
    assert preview.status_code == 200
    for method, url, body in (
        ("POST", "/roadmaps", {"project_id": str(project.id), "title": "x"}),
        ("PATCH", f"/roadmaps/{active['id']}", {"title": "x"}),
        (
            "POST",
            f"/roadmaps/{active['id']}/hydration/apply",
            {"expected_version": active["version"]},
        ),
        ("POST", f"/roadmaps/{active['id']}/dependencies", {}),
    ):
        response = await client.request(
            method,
            f"/api/v1{url}",
            headers={**readonly_auth_headers, "If-Match-Version": "1"},
            json=body,
        )
        assert response.status_code in (403, 422), (url, response.text)
    denied = await client.post(
        f"/api/v1/roadmaps/{active['id']}/hydration/apply",
        headers=readonly_auth_headers,
        json={"expected_version": active["version"]},
    )
    assert denied.status_code == 403


# --- structure ---
async def test_phase_and_step_crud_ordering_and_duplicates(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    rid = roadmap["id"]
    version = roadmap["version"]

    phase = await client.post(
        f"/api/v1/roadmaps/{rid}/phases",
        headers=auth_headers,
        json={"key": "P3", "title": "Third", "expected_roadmap_version": version},
    )
    assert phase.status_code == 201, phase.text
    assert [p["key"] for p in phase.json()["phases"]] == ["P1", "P2", "P3"]
    version = phase.json()["version"]
    assert version == roadmap["version"] + 1

    stale = await client.post(
        f"/api/v1/roadmaps/{rid}/phases",
        headers=auth_headers,
        json={"key": "P4", "title": "x", "expected_roadmap_version": roadmap["version"]},
    )
    assert stale.status_code == 409 and error(stale)["server_version"] == version
    duplicate = await client.post(
        f"/api/v1/roadmaps/{rid}/phases",
        headers=auth_headers,
        json={"key": "P3", "title": "x", "expected_roadmap_version": version},
    )
    assert duplicate.status_code == 409
    assert error(duplicate) == {"error_code": "duplicate_key", "field": "key"}

    step = await client.post(
        f"/api/v1/roadmaps/{rid}/phases/P3/steps",
        headers=auth_headers,
        json={
            "content": {
                "key": "S9",
                "title": "New",
                "depends_on": ["S3"],
                "tasks": [{"hydration_key": "a", "title": "A"}],
            },
            "expected_roadmap_version": version,
        },
    )
    assert step.status_code == 201, step.text
    assert step_of(step.json(), "S9")["depends_on"] == ["S3"]
    assert step_of(step.json(), "S9")["position"] == 0
    version = step.json()["version"]

    dup_step = await client.post(
        f"/api/v1/roadmaps/{rid}/phases/P1/steps",
        headers=auth_headers,
        json={
            "content": {"key": "S9", "title": "dup"},
            "expected_roadmap_version": version,
        },
    )
    assert dup_step.status_code == 409 and error(dup_step)["error_code"] == "duplicate_key"
    unknown_dep = await client.post(
        f"/api/v1/roadmaps/{rid}/phases/P1/steps",
        headers=auth_headers,
        json={
            "content": {"key": "S10", "title": "x", "depends_on": ["nope"]},
            "expected_roadmap_version": version,
        },
    )
    assert unknown_dep.status_code == 404
    assert error(unknown_dep)["error_code"] == "reference_not_found"
    self_dep = await client.post(
        f"/api/v1/roadmaps/{rid}/phases/P1/steps",
        headers=auth_headers,
        json={
            "content": {"key": "S10", "title": "x", "depends_on": ["S10"]},
            "expected_roadmap_version": version,
        },
    )
    assert self_dep.status_code == 422 and error(self_dep)["reason"] == "self_dependency"
    no_phase = await client.post(
        f"/api/v1/roadmaps/{rid}/phases/PX/steps",
        headers=auth_headers,
        json={"content": {"key": "S11", "title": "x"}, "expected_roadmap_version": version},
    )
    assert no_phase.status_code == 404

    edited = await client.patch(
        f"/api/v1/roadmaps/{rid}/steps/S9",
        headers={**auth_headers, "If-Match-Version": str(step_of(step.json(), "S9")["version"])},
        json={
            "title": "Renamed",
            "acceptance_criteria": ["one"],
            "tasks": [{"hydration_key": "a", "title": "A2"}],
            "metadata": {"z": True},
        },
    )
    assert edited.status_code == 200, edited.text
    assert step_of(edited.json(), "S9")["title"] == "Renamed"
    assert step_of(edited.json(), "S9")["tasks"][0]["title"] == "A2"
    dup_plan = await client.patch(
        f"/api/v1/roadmaps/{rid}/steps/S9",
        headers={**auth_headers, "If-Match-Version": str(step_of(edited.json(), "S9")["version"])},
        json={
            "tasks": [
                {"hydration_key": "a", "title": "A"},
                {"hydration_key": "a", "title": "B"},
            ]
        },
    )
    assert dup_plan.status_code == 422
    assert error(dup_plan)["reason"] == "duplicate_hydration_key"

    phase_patch = await client.patch(
        f"/api/v1/roadmaps/{rid}/phases/P3",
        headers={**auth_headers, "If-Match-Version": "1"},
        json={"title": "Third bis", "objective": "Goal"},
    )
    assert phase_patch.status_code == 200
    assert phase_patch.json()["phases"][2]["title"] == "Third bis"
    phase_stale = await client.patch(
        f"/api/v1/roadmaps/{rid}/phases/P3",
        headers={**auth_headers, "If-Match-Version": "1"},
        json={"title": "x"},
    )
    assert phase_stale.status_code == 409 and error(phase_stale)["server_version"] == 2


async def test_reorder_is_an_atomic_permutation(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    rid = roadmap["id"]
    ok = await client.post(
        f"/api/v1/roadmaps/{rid}/phases/P1/steps/reorder",
        headers=auth_headers,
        json={"ordered_keys": ["S2", "S1"], "expected_roadmap_version": roadmap["version"]},
    )
    assert ok.status_code == 200, ok.text
    assert [s["key"] for s in ok.json()["phases"][0]["steps"]] == ["S2", "S1"]
    assert [s["position"] for s in ok.json()["phases"][0]["steps"]] == [0, 1]
    assert ok.json()["version"] == roadmap["version"] + 1

    for bad in (["S1"], ["S1", "S1"], ["S1", "S2", "S3"], ["S2", "SX"]):
        response = await client.post(
            f"/api/v1/roadmaps/{rid}/phases/P1/steps/reorder",
            headers=auth_headers,
            json={"ordered_keys": bad, "expected_roadmap_version": ok.json()["version"]},
        )
        assert response.status_code == 422, bad
        assert error(response)["reason"] == "invalid_reorder"
    after = await get(client, auth_headers, rid)
    assert [s["key"] for s in after["phases"][0]["steps"]] == ["S2", "S1"]
    assert after["version"] == ok.json()["version"]  # rejected reorders change nothing

    phases = await client.post(
        f"/api/v1/roadmaps/{rid}/phases/reorder",
        headers=auth_headers,
        json={"ordered_keys": ["P2", "P1"], "expected_roadmap_version": after["version"]},
    )
    assert [p["key"] for p in phases.json()["phases"]] == ["P2", "P1"]
    assert phases.json()["current_step_key"] == "S3"
    stale = await client.post(
        f"/api/v1/roadmaps/{rid}/phases/reorder",
        headers=auth_headers,
        json={"ordered_keys": ["P1", "P2"], "expected_roadmap_version": after["version"]},
    )
    assert stale.status_code == 409


async def test_delete_only_on_draft_and_never_with_links(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    rid = roadmap["id"]
    task_id = await make_task(client, auth_headers, project)
    linked = await client.post(
        f"/api/v1/roadmaps/{rid}/steps/S1/links", headers=auth_headers, json={"task_id": task_id}
    )
    assert linked.status_code == 201
    version = linked.json()["version"]
    blocked = await client.delete(
        f"/api/v1/roadmaps/{rid}/steps/S1",
        headers={**auth_headers, "If-Match-Version": str(version)},
    )
    assert blocked.status_code == 409 and error(blocked)["error_code"] == "step_has_links"
    phase_blocked = await client.delete(
        f"/api/v1/roadmaps/{rid}/phases/P1",
        headers={**auth_headers, "If-Match-Version": str(version)},
    )
    assert error(phase_blocked)["error_code"] == "step_has_links"

    removed = await client.delete(
        f"/api/v1/roadmaps/{rid}/steps/S3",
        headers={**auth_headers, "If-Match-Version": str(version)},
    )
    assert removed.status_code == 200
    assert [s["key"] for s in removed.json()["phases"][1]["steps"]] == []
    dropped = await client.delete(
        f"/api/v1/roadmaps/{rid}/phases/P2",
        headers={**auth_headers, "If-Match-Version": str(removed.json()["version"])},
    )
    assert [p["key"] for p in dropped.json()["phases"]] == ["P1"]


async def test_delete_on_active_roadmap_is_invalid_state(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    response = await client.delete(
        f"/api/v1/roadmaps/{active['id']}/steps/S3",
        headers={**auth_headers, "If-Match-Version": str(active["version"])},
    )
    assert response.status_code == 409
    assert error(response)["error_code"] == "invalid_state"


async def test_dependencies_cycle_prevention_and_noops(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    rid = roadmap["id"]
    version = roadmap["version"]

    cycle = await client.post(
        f"/api/v1/roadmaps/{rid}/dependencies",
        headers=auth_headers,
        json={"step_key": "S1", "depends_on_key": "S2", "expected_roadmap_version": version},
    )
    assert cycle.status_code == 409
    assert error(cycle)["error_code"] == "dependency_cycle"
    assert error(cycle)["path"] == ["S1", "S2", "S1"]
    assert (await get(client, auth_headers, rid))["version"] == version

    added = await client.post(
        f"/api/v1/roadmaps/{rid}/dependencies",
        headers=auth_headers,
        json={"step_key": "S3", "depends_on_key": "S2", "expected_roadmap_version": version},
    )
    assert added.status_code == 200, added.text
    assert step_of(added.json(), "S3")["depends_on"] == ["S2"]
    assert step_of(added.json(), "S3")["waiting_on"] == ["S2"]
    version = added.json()["version"]

    long_cycle = await client.post(
        f"/api/v1/roadmaps/{rid}/dependencies",
        headers=auth_headers,
        json={"step_key": "S1", "depends_on_key": "S3", "expected_roadmap_version": version},
    )
    assert long_cycle.status_code == 409
    assert set(error(long_cycle)["path"]) == {"S1", "S2", "S3"}

    again = await client.post(
        f"/api/v1/roadmaps/{rid}/dependencies",
        headers=auth_headers,
        json={"step_key": "S3", "depends_on_key": "S2", "expected_roadmap_version": version},
    )
    assert again.status_code == 200 and again.json()["version"] == version

    self_edge = await client.post(
        f"/api/v1/roadmaps/{rid}/dependencies",
        headers=auth_headers,
        json={"step_key": "S3", "depends_on_key": "S3", "expected_roadmap_version": version},
    )
    assert self_edge.status_code == 422 and error(self_edge)["reason"] == "self_dependency"
    unknown = await client.post(
        f"/api/v1/roadmaps/{rid}/dependencies",
        headers=auth_headers,
        json={"step_key": "S3", "depends_on_key": "ZZ", "expected_roadmap_version": version},
    )
    assert unknown.status_code == 404

    removed = await client.post(
        f"/api/v1/roadmaps/{rid}/dependencies/remove",
        headers=auth_headers,
        json={"step_key": "S3", "depends_on_key": "S2", "expected_roadmap_version": version},
    )
    assert step_of(removed.json(), "S3")["depends_on"] == []
    noop = await client.post(
        f"/api/v1/roadmaps/{rid}/dependencies/remove",
        headers=auth_headers,
        json={
            "step_key": "S3",
            "depends_on_key": "S2",
            "expected_roadmap_version": removed.json()["version"],
        },
    )
    assert noop.status_code == 200 and noop.json()["version"] == removed.json()["version"]


# --- links, derived state, progress ---
async def test_links_derive_state_and_progress_from_tasks(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await active_roadmap(client, auth_headers, project)
    rid = roadmap["id"]
    task_a = await make_task(client, auth_headers, project)
    task_b = await make_task(client, auth_headers, project)
    for task_id in (task_a, task_b):
        linked = await client.post(
            f"/api/v1/roadmaps/{rid}/steps/S1/links",
            headers=auth_headers,
            json={"task_id": task_id},
        )
        assert linked.status_code == 201, linked.text
    state = await get(client, auth_headers, rid)
    s1 = step_of(state, "S1")
    assert s1["state"] == "not_started"
    assert s1["task_progress"] == {"completed": 0, "total": 2}
    assert {link["task_id"] for link in s1["linked_tasks"]} == {task_a, task_b}
    assert state["progress"]["done"] == 0

    claim = await client.post(f"/api/v1/tasks/{task_a}/claim", headers=auth_headers)
    assert claim.status_code == 200
    assert step_of(await get(client, auth_headers, rid), "S1")["state"] == "in_progress"

    for task_id in (task_a, task_b):
        current = (await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)).json()
        done = await client.patch(
            f"/api/v1/tasks/{task_id}",
            headers={**auth_headers, "If-Match-Version": str(current["version"])},
            json={"status": "completed"},
        )
        assert done.status_code == 200
    state = await get(client, auth_headers, rid)
    assert step_of(state, "S1")["state"] == "done"
    assert step_of(state, "S1")["task_progress"] == {"completed": 2, "total": 2}
    assert step_of(state, "S2")["available"] is True
    assert step_of(state, "S2")["waiting_on"] == []
    assert state["progress"] == {"done": 1, "total": 3, "skipped": 0, "ratio": 1 / 3}
    assert state["phases"][0]["progress"]["done"] == 1
    assert state["current_step_key"] == "S2"

    unlink = await client.delete(
        f"/api/v1/roadmaps/{rid}/steps/S1/links/{task_a}", headers=auth_headers
    )
    assert unlink.status_code == 200
    assert step_of(unlink.json(), "S1")["task_progress"] == {"completed": 1, "total": 1}
    task_still = await client.get(f"/api/v1/tasks/{task_a}", headers=auth_headers)
    assert task_still.status_code == 200 and task_still.json()["status"] == "completed"
    again = await client.delete(
        f"/api/v1/roadmaps/{rid}/steps/S1/links/{task_a}", headers=auth_headers
    )
    assert again.status_code == 200


async def test_link_errors_and_idempotence(
    client: AsyncClient,
    auth_headers: Headers,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    roadmap = await import_roadmap(client, auth_headers, project)
    rid = roadmap["id"]
    task_id = await make_task(client, auth_headers, project)
    first = await client.post(
        f"/api/v1/roadmaps/{rid}/steps/S1/links", headers=auth_headers, json={"task_id": task_id}
    )
    second = await client.post(
        f"/api/v1/roadmaps/{rid}/steps/S1/links", headers=auth_headers, json={"task_id": task_id}
    )
    assert first.status_code == second.status_code == 201
    assert len(step_of(second.json(), "S1")["linked_tasks"]) == 1
    assert second.json()["version"] == first.json()["version"]

    other_project = ProjectModel(slug=f"other-{uuid.uuid4().hex[:6]}", name="Other")
    db_session.add(other_project)
    await db_session.flush()
    foreign = await client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"project_id": str(other_project.id), "title": "Foreign"},
    )
    mismatch = await client.post(
        f"/api/v1/roadmaps/{rid}/steps/S1/links",
        headers=auth_headers,
        json={"task_id": foreign.json()["id"]},
    )
    assert mismatch.status_code == 422
    assert error(mismatch)["error_code"] == "task_project_mismatch"
    missing = await client.post(
        f"/api/v1/roadmaps/{rid}/steps/S1/links",
        headers=auth_headers,
        json={"task_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 404 and error(missing)["error_code"] == "reference_not_found"
    no_step = await client.post(
        f"/api/v1/roadmaps/{rid}/steps/NOPE/links", headers=auth_headers, json={"task_id": task_id}
    )
    assert no_step.status_code == 404


async def test_task_and_project_work_without_any_roadmap(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    task_id = await make_task(client, auth_headers, project)
    task = (await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)).json()
    assert "roadmap_id" not in task
    assert (await client.get("/api/v1/projects", headers=auth_headers)).status_code == 200
    listing = await client.get(f"/api/v1/projects/{project.id}/roadmaps", headers=auth_headers)
    assert listing.status_code == 200 and listing.json() == []
    claim = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    assert claim.status_code == 200


async def test_step_progress_override_criteria_and_notes(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    roadmap = await active_roadmap(client, auth_headers, project)
    rid = roadmap["id"]
    s2 = step_of(roadmap, "S2")
    url = f"/api/v1/roadmaps/{rid}/steps/S2/progress"

    out_of_range = await client.patch(
        url,
        headers={**auth_headers, "If-Match-Version": str(s2["version"])},
        json={"criteria_checked": [2]},
    )
    assert out_of_range.status_code == 422
    assert error(out_of_range)["error_code"] == "invalid_roadmap"

    checked = await client.patch(
        url,
        headers={**auth_headers, "If-Match-Version": str(s2["version"])},
        json={"criteria_checked": [1, 0], "notes": "wip"},
    )
    assert checked.status_code == 200
    s2 = step_of(checked.json(), "S2")
    assert s2["criteria_checked"] == [0, 1] and s2["notes"] == "wip"
    assert (
        checked.json()["version"] == roadmap["version"]
    )  # notes/criteria keep the roadmap version

    skipped = await client.patch(
        url,
        headers={**auth_headers, "If-Match-Version": str(s2["version"])},
        json={"state_override": "skipped", "state_override_reason": "descoped"},
    )
    assert skipped.status_code == 200
    s2 = step_of(skipped.json(), "S2")
    assert s2["state"] == "skipped" and s2["state_override_reason"] == "descoped"
    assert skipped.json()["version"] == roadmap["version"] + 1
    assert skipped.json()["progress"] == {"done": 0, "total": 2, "skipped": 1, "ratio": 0.0}
    assert step_of(skipped.json(), "S3")["available"] is True

    cleared = await client.patch(
        url,
        headers={**auth_headers, "If-Match-Version": str(s2["version"])},
        json={"clear_state_override": True},
    )
    s2 = step_of(cleared.json(), "S2")
    assert s2["state"] == "not_started" and s2["state_override"] is None
    assert s2["state_override_reason"] is None

    milestone = await client.patch(
        url,
        headers={**auth_headers, "If-Match-Version": str(s2["version"])},
        json={"state_override": "done"},
    )
    assert step_of(milestone.json(), "S2")["state"] == "done"

    edited = await client.patch(
        f"/api/v1/roadmaps/{rid}/steps/S2",
        headers={
            **auth_headers,
            "If-Match-Version": str(step_of(milestone.json(), "S2")["version"]),
        },
        json={"acceptance_criteria": ["only one"]},
    )
    assert edited.status_code == 200, edited.text
    assert step_of(edited.json(), "S2")["criteria_checked"] == []


# --- hydration ---
async def test_hydration_preview_writes_nothing_and_is_not_applicable_on_draft(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel, db_session: AsyncSession
) -> None:
    draft = await import_roadmap(client, auth_headers, project)
    preview = await client.post(
        f"/api/v1/roadmaps/{draft['id']}/hydration/preview", headers=auth_headers, json={}
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["applied"] is False and body["applicable"] is False
    assert body["not_applicable_reason"] == "roadmap_not_active"
    assert body["counts"] == {"create": 2, "reuse": 0, "skip": 0}
    assert (await db_session.execute(select(TaskModel))).scalars().all() == []

    apply = await client.post(
        f"/api/v1/roadmaps/{draft['id']}/hydration/apply",
        headers=auth_headers,
        json={"expected_version": draft["version"]},
    )
    assert apply.status_code == 409 and error(apply)["error_code"] == "invalid_state"
    assert (await db_session.execute(select(TaskModel))).scalars().all() == []


async def test_hydration_apply_is_idempotent_by_key_and_by_hydration_key(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel, db_session: AsyncSession
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    rid = active["id"]
    preview = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/preview", headers=auth_headers, json={}
    )
    assert preview.json()["applicable"] is True
    assert preview.json()["counts"] == {"create": 2, "reuse": 0, "skip": 0}
    version = preview.json()["roadmap_version"]
    assert version == active["version"]

    key = str(uuid.uuid4())
    payload = {"expected_version": version}
    first = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/apply",
        headers={**auth_headers, "Idempotency-Key": key},
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert first.json()["applied"] is True
    assert first.json()["counts"] == {"create": 2, "reuse": 0, "skip": 0}
    task_ids = [item["task_id"] for item in first.json()["items"]]
    assert all(task_ids)

    replay = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/apply",
        headers={**auth_headers, "Idempotency-Key": key},
        json=payload,
    )
    assert replay.json() == first.json()

    fresh_key = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/apply",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json=payload,
    )
    assert fresh_key.status_code == 200, fresh_key.text
    assert fresh_key.json()["counts"] == {"create": 0, "reuse": 2, "skip": 0}
    assert [item["task_id"] for item in fresh_key.json()["items"]] == task_ids

    tasks = (await db_session.execute(select(TaskModel))).scalars().all()
    assert len(tasks) == 2
    assert {task.title for task in tasks} == {"Task one", "Task two"}
    assert all(task.status == "created" and task.version == 1 for task in tasks)
    state = await get(client, auth_headers, rid)
    assert [t["hydration_key"] for t in step_of(state, "S1")["linked_tasks"]] == ["t1", "t2"]
    assert {t["task_id"] for t in step_of(state, "S1")["linked_tasks"]} == set(task_ids)

    after_preview = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/preview", headers=auth_headers, json={}
    )
    assert after_preview.json()["counts"] == {"create": 0, "reuse": 2, "skip": 0}

    events = (
        (
            await db_session.execute(
                select(EventModel).where(EventModel.event_type == "roadmap.hydrated")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1  # the reuse-only replay emitted nothing
    assert events[0].payload["counts"] == {"create": 2, "reuse": 0, "skip": 0}


async def test_hydration_apply_expected_version_and_subset(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    rid = active["id"]
    changed = await client.patch(
        f"/api/v1/roadmaps/{rid}",
        headers={**auth_headers, "If-Match-Version": str(active["version"])},
        json={"context": "changed after preview"},
    )
    assert changed.status_code == 200
    stale = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/apply",
        headers=auth_headers,
        json={"expected_version": active["version"]},
    )
    assert stale.status_code == 409
    assert error(stale) == {
        "error_code": "version_conflict",
        "server_version": changed.json()["version"],
    }
    unknown = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/apply",
        headers=auth_headers,
        json={"expected_version": changed.json()["version"], "step_keys": ["NOPE"]},
    )
    assert unknown.status_code == 404
    subset = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/apply",
        headers=auth_headers,
        json={"expected_version": changed.json()["version"], "step_keys": ["S2"]},
    )
    assert subset.status_code == 200 and subset.json()["items"] == []  # S2 has no plan


async def test_hydration_skips_done_and_skipped_steps_and_never_touches_existing_tasks(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel, db_session: AsyncSession
) -> None:
    active = await active_roadmap(client, auth_headers, project)
    rid = active["id"]
    s1 = step_of(active, "S1")
    skipped = await client.patch(
        f"/api/v1/roadmaps/{rid}/steps/S1/progress",
        headers={**auth_headers, "If-Match-Version": str(s1["version"])},
        json={"state_override": "skipped"},
    )
    preview = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/preview", headers=auth_headers, json={}
    )
    assert preview.json()["counts"] == {"create": 0, "reuse": 0, "skip": 2}
    assert {item["reason"] for item in preview.json()["items"]} == {"step_skipped"}

    existing = await make_task(client, auth_headers, project)
    await client.delete(f"/api/v1/roadmaps/{rid}/steps/S1/links/{existing}", headers=auth_headers)
    cleared = await client.patch(
        f"/api/v1/roadmaps/{rid}/steps/S1/progress",
        headers={
            **auth_headers,
            "If-Match-Version": str(step_of(skipped.json(), "S1")["version"]),
        },
        json={"clear_state_override": True},
    )
    assert cleared.status_code == 200
    link = await client.post(
        f"/api/v1/roadmaps/{rid}/steps/S1/links", headers=auth_headers, json={"task_id": existing}
    )
    assert link.status_code == 201
    before = (
        await db_session.execute(select(TaskModel).where(TaskModel.id == uuid.UUID(existing)))
    ).scalar_one()
    snapshot = (before.title, before.status, before.version, before.description)
    applied = await client.post(
        f"/api/v1/roadmaps/{rid}/hydration/apply",
        headers=auth_headers,
        json={"expected_version": link.json()["version"]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["counts"]["create"] == 2  # the manual link has no hydration_key
    await db_session.refresh(before)
    assert (before.title, before.status, before.version, before.description) == snapshot


# --- provenance, events, neutrality ---
async def test_provenance_agent_must_belong_to_the_calling_machine(
    client: AsyncClient,
    auth_headers: Headers,
    other_auth_headers: Headers,
    project: ProjectModel,
    agent: AgentModel,
) -> None:
    ok = await client.post(
        "/api/v1/roadmaps",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "title": "By agent",
            "provenance": {"origin": "ai_proposal", "agent_id": str(agent.id)},
        },
    )
    assert ok.status_code == 201, ok.text
    provenance = ok.json()["provenance"]
    assert provenance["origin"] == "ai_proposal"
    assert provenance["actor_type"] == "agent"
    assert provenance["actor_id"] == provenance["agent_id"] == str(agent.id)
    assert set(provenance) == {"origin", "actor_type", "actor_id", "agent_id", "machine_id", "at"}

    stolen = await client.post(
        "/api/v1/roadmaps",
        headers=other_auth_headers,
        json={
            "project_id": str(project.id),
            "title": "Spoofed",
            "provenance": {"agent_id": str(agent.id)},
        },
    )
    assert stolen.status_code == 409
    assert error(stolen)["error_code"] == "actor_not_owned"
    unknown = await client.post(
        "/api/v1/roadmaps",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "title": "Ghost",
            "provenance": {"agent_id": str(uuid.uuid4())},
        },
    )
    assert error(unknown)["error_code"] == "actor_not_owned"


async def test_events_carry_the_authenticated_actor(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    agent: AgentModel,
    db_session: AsyncSession,
) -> None:
    created = await client.post(
        "/api/v1/roadmaps",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "title": "Audited",
            "provenance": {"agent_id": str(agent.id)},
        },
    )
    assert created.status_code == 201
    event = (
        await db_session.execute(
            select(EventModel).where(
                EventModel.project_id == project.id, EventModel.event_type == "roadmap.created"
            )
        )
    ).scalar_one()
    assert event.actor_type == "agent" and event.actor_id == agent.id
    assert event.machine_id == machine[0].id
    assert event.payload["roadmap_id"] == created.json()["id"]


def test_no_provider_model_or_harness_column_or_field_in_the_roadmap_domain() -> None:
    from studio_api.db.models import roadmap as models

    forbidden = ("provider", "model", "harness", "claude", "openai", "opencode")
    for name in dir(models):
        table = getattr(getattr(models, name), "__table__", None)
        if table is None or not str(table.name).startswith("roadmap"):
            continue
        for column in table.columns:
            assert not any(token in column.name.lower() for token in forbidden), column.name

    schema = app.openapi()
    roadmap_schemas = {
        name: body
        for name, body in schema["components"]["schemas"].items()
        if name.startswith(("Roadmap", "Phase", "Step", "Hydration", "Reorder", "Dependency"))
    }
    assert roadmap_schemas
    dumped = json.dumps(roadmap_schemas).lower()
    for token in ("provider", "harness", "openai", "claude", "opencode"):
        assert token not in dumped


def test_openapi_documents_every_roadmap_route_with_errors() -> None:
    paths = app.openapi()["paths"]
    expected = {
        ("get", "/api/v1/projects/{project_id}/roadmaps"),
        ("post", "/api/v1/roadmaps"),
        ("post", "/api/v1/roadmaps/import"),
        ("get", "/api/v1/roadmaps/{roadmap_id}"),
        ("patch", "/api/v1/roadmaps/{roadmap_id}"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/transitions"),
        ("get", "/api/v1/roadmaps/{roadmap_id}/export"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/phases"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/phases/reorder"),
        ("patch", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}"),
        ("delete", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}/steps"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/phases/{phase_key}/steps/reorder"),
        ("patch", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}"),
        ("patch", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/progress"),
        ("delete", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/dependencies"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/dependencies/remove"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/links"),
        ("delete", "/api/v1/roadmaps/{roadmap_id}/steps/{step_key}/links/{task_id}"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/hydration/preview"),
        ("post", "/api/v1/roadmaps/{roadmap_id}/hydration/apply"),
    }
    documented = {(method, path) for path, ops in paths.items() for method in ops}
    assert expected <= documented
    for method, path in expected:
        operation = paths[path][method]
        assert operation.get("description"), (method, path)
        assert operation.get("security") or "401" in operation["responses"], (method, path)
        assert "roadmaps" in operation["tags"]
    for path in (
        "/api/v1/roadmaps/{roadmap_id}/transitions",
        "/api/v1/roadmaps/{roadmap_id}/hydration/apply",
    ):
        responses = paths[path]["post"]["responses"]
        assert {"401", "403", "404", "409", "422"} <= set(responses)
    apply_params = paths["/api/v1/roadmaps/{roadmap_id}/hydration/apply"]["post"]["parameters"]
    assert "Idempotency-Key" in {p["name"] for p in apply_params}
    patch_params = paths["/api/v1/roadmaps/{roadmap_id}"]["patch"]["parameters"]
    assert "If-Match-Version" in {p["name"] for p in patch_params}


async def test_per_request_bounds_are_422_limit_exceeded(
    client: AsyncClient, auth_headers: Headers, project: ProjectModel
) -> None:
    full = document()
    full["phases"] = [
        {
            "key": "P1",
            "title": "Full",
            "steps": [{"key": f"S{n}", "title": f"Step {n}"} for n in range(50)],
        }
    ]
    roadmap = await import_roadmap(client, auth_headers, project, full)
    over = await client.post(
        f"/api/v1/roadmaps/{roadmap['id']}/phases/P1/steps",
        headers=auth_headers,
        json={
            "content": {"key": "S50", "title": "One too many"},
            "expected_roadmap_version": roadmap["version"],
        },
    )
    assert over.status_code == 422
    assert error(over) == {"error_code": "limit_exceeded", "limit": "steps_per_phase"}
    unchanged = await get(client, auth_headers, roadmap["id"])
    assert unchanged["version"] == roadmap["version"]
    assert len(unchanged["phases"][0]["steps"]) == 50
