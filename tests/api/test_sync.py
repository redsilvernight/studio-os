"""`studio_sync` (C2, DEC-0157): single pull resync point — deterministic
`why` filter, per-session ack cursor, bounded answers, overflow counters,
live claim state. Real Postgres through the shared savepoint fixtures."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import get_settings

SYNC = "/api/v1/sync"


async def _task(
    client: AsyncClient, headers: dict[str, str], project: ProjectModel, title: str = "sync task"
) -> dict:
    created = await client.post(
        "/api/v1/tasks",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"project_id": str(project.id), "title": title},
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _start(
    client: AsyncClient,
    headers: dict[str, str],
    machine_id: str,
    task_id: str,
    agent_id: str | None = None,
) -> dict:
    response = await client.post(
        "/api/v1/sessions",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"task_id": task_id, "machine_id": machine_id, "agent_id": agent_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _second_machine(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> tuple[MachineModel, str]:
    """Another machine of the same user: same project access, distinct
    machine identity — the two-machine sync scenario."""
    model, _ = machine
    return await provisioning_service.create_machine(
        db_session, model.owner_user_id, "second-machine"
    )


def _second_headers(second: tuple[MachineModel, str]) -> dict[str, str]:
    _, token = second
    return {"Authorization": f"Bearer {token}"}


async def _patch_title(
    client: AsyncClient, headers: dict[str, str], task_id: str, version: int, title: str
) -> int:
    updated = await client.patch(
        f"/api/v1/tasks/{task_id}",
        headers={**headers, "If-Match-Version": str(version)},
        json={"title": title},
    )
    assert updated.status_code == 200, updated.text
    return int(updated.json()["version"])


async def _sync(client: AsyncClient, headers: dict[str, str], **params: object):
    return await client.get(SYNC, headers=headers, params=params)


async def _backdate(db_session: AsyncSession, session_id: str, age: timedelta) -> None:
    await db_session.execute(
        update(WorkSessionModel)
        .where(WorkSessionModel.id == uuid.UUID(session_id))
        .values(last_activity_at=datetime.now(UTC) - age)
    )
    await db_session.commit()


async def _second_agent(db_session: AsyncSession, second: tuple[MachineModel, str]) -> AgentModel:
    model, _ = second
    agent = AgentModel(machine_id=model.id, display_name="claude-code-b", agent_kind="claude_code")
    db_session.add(agent)
    await db_session.flush()
    await db_session.refresh(agent)
    return agent


async def _ai_work_lifecycle(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> tuple[dict, dict, str]:
    """One `ai_work` entry of my task logged then completed by the second
    machine: two matched events of one lifecycle, `started` then `completed`."""
    second = await _second_machine(db_session, machine)
    second_headers = _second_headers(second)
    other_agent = await _second_agent(db_session, second)
    task = await _task(client, auth_headers, project)
    mine = await _start(client, auth_headers, str(machine[0].id), task["id"])
    logged = await client.post(
        "/api/v1/ai-work",
        headers={**second_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "task_id": task["id"],
            "agent_id": str(other_agent.id),
            "summary": "Reduce the sync noise",
        },
    )
    assert logged.status_code == 201, logged.text
    work_id = logged.json()["id"]
    completed = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=second_headers, json={"status": "completed"}
    )
    assert completed.status_code == 200, completed.text
    return task, mine, work_id


async def _signal(
    client: AsyncClient,
    headers: dict[str, str],
    from_session_id: str,
    task_id: str,
    text: str,
) -> dict:
    sent = await client.post(
        "/api/v1/coordination",
        headers=headers,
        json={
            "from_session_id": from_session_id,
            "intent": "question",
            "task_id": task_id,
            "text": text,
            "refs": {"paths": ["services/api/src/studio_api/services/sync.py"]},
        },
    )
    assert sent.status_code == 201, sent.text
    return sent.json()


async def _mixed_batch(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
    *,
    signals: int,
) -> tuple[dict, list[dict]]:
    """Matched events of two sizes on my task, in `seq` order: `signals`
    coordination signals (wide — they quote their payload) emitted from a
    session of the second machine on another task, then one `task.updated`
    (narrow). Only those `signals + 1` events match my sync."""
    second = await _second_machine(db_session, machine)
    second_headers = _second_headers(second)
    task = await _task(client, auth_headers, project)
    mine = await _start(client, auth_headers, str(machine[0].id), task["id"])
    other = await _task(client, auth_headers, project, "signaller task")
    theirs = await _start(client, second_headers, str(second[0].id), other["id"])
    emitted = [
        await _signal(
            client,
            second_headers,
            theirs["id"],
            task["id"],
            f"signal {n} — " + "detail " * 30,
        )
        for n in range(signals)
    ]
    await _patch_title(client, second_headers, task["id"], task["version"], "touched by B")
    return mine, emitted


async def test_empty_sync_is_tiny(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    task = await _task(client, auth_headers, project)
    started = await _start(client, auth_headers, str(machine[0].id), task["id"])
    response = await _sync(client, auth_headers, session_id=started["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["overflow"] == {}
    assert body["resync"] is False
    assert len(json.dumps(body)) < 300


async def test_two_machines_task_events_and_own_exclusion(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    second = await _second_machine(db_session, machine)
    second_headers = _second_headers(second)
    task = await _task(client, auth_headers, project)
    started = await _start(client, auth_headers, str(machine[0].id), task["id"])

    version = await _patch_title(
        client, second_headers, task["id"], task["version"], "touched by B"
    )
    body = (await _sync(client, auth_headers, session_id=started["id"])).json()
    assert [(i["why"], i["task_id"]) for i in body["items"]] == [("own_task", task["id"])]
    assert body["items"][0]["event_type"] == "task.updated"
    assert body["next_cursor"] > 0

    await _patch_title(client, auth_headers, task["id"], version, "touched by A")
    again = (await _sync(client, auth_headers, session_id=started["id"])).json()
    assert len(again["items"]) == 1
    assert again["items"][0]["event_type"] == "task.updated"
    assert again["next_cursor"] == body["next_cursor"]


async def test_replay_same_ack_is_identical(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    second = await _second_machine(db_session, machine)
    task = await _task(client, auth_headers, project)
    started = await _start(client, auth_headers, str(machine[0].id), task["id"])
    await _patch_title(client, _second_headers(second), task["id"], task["version"], "bump")
    first = await _sync(client, auth_headers, session_id=started["id"])
    cursor = first.json()["next_cursor"]
    replayed = await _sync(client, auth_headers, session_id=started["id"], ack=cursor)
    reread = await _sync(client, auth_headers, session_id=started["id"], ack=cursor)
    assert replayed.json() == reread.json()
    assert replayed.json()["items"] == []


async def test_ack_persists_cursor(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    second = await _second_machine(db_session, machine)
    task = await _task(client, auth_headers, project)
    started = await _start(client, auth_headers, str(machine[0].id), task["id"])
    await _patch_title(client, _second_headers(second), task["id"], task["version"], "bump")
    fresh = (await _sync(client, auth_headers, session_id=started["id"])).json()
    assert len(fresh["items"]) == 1
    acked = (
        await _sync(client, auth_headers, session_id=started["id"], ack=fresh["next_cursor"])
    ).json()
    assert acked["items"] == []
    drained = (await _sync(client, auth_headers, session_id=started["id"])).json()
    assert drained["items"] == []
    assert drained["next_cursor"] == fresh["next_cursor"]


async def test_overflow_counters_and_bounds(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    second = await _second_machine(db_session, machine)
    second_headers = _second_headers(second)
    task = await _task(client, auth_headers, project)
    started = await _start(client, auth_headers, str(machine[0].id), task["id"])
    version = task["version"]
    for n in range(12):
        version = await _patch_title(client, second_headers, task["id"], version, f"bump {n}")
    body = (await _sync(client, auth_headers, session_id=started["id"], limit=5)).json()
    assert len(body["items"]) == 5
    assert body["overflow"] == {"own_task": 7}
    assert body["resync"] is False

    tiny = (await _sync(client, auth_headers, session_id=started["id"], max_chars=1000)).json()
    assert tiny["overflow"].get("own_task", 0) > 0
    assert len(tiny["items"]) < 12


async def test_expired_session_syncs_without_closing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    settings = get_settings()
    task = await _task(client, auth_headers, project)
    started = await _start(client, auth_headers, str(machine[0].id), task["id"])
    await _backdate(
        db_session,
        started["id"],
        timedelta(seconds=settings.session_expire_after_seconds + 60),
    )
    response = await _sync(client, auth_headers, session_id=started["id"])
    assert response.status_code == 200, response.text
    listing = await client.get(
        "/api/v1/sessions", headers=auth_headers, params={"task_id": task["id"]}
    )
    row = listing.json()[0]
    assert row["ended_at"] is None


async def test_handoff_cursor_inherited_by_next_session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    second = await _second_machine(db_session, machine)
    task = await _task(client, auth_headers, project)
    first = await _start(client, auth_headers, str(machine[0].id), task["id"])
    await _patch_title(client, _second_headers(second), task["id"], task["version"], "bump")
    fresh = (await _sync(client, auth_headers, session_id=first["id"])).json()
    cursor = fresh["next_cursor"]
    assert cursor > 0
    acked = (await _sync(client, auth_headers, session_id=first["id"], ack=cursor)).json()
    assert acked["items"] == []

    current = (await client.get(f"/api/v1/tasks/{task['id']}", headers=auth_headers)).json()
    handed = await client.post(
        "/api/v1/handoff",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "session_id": first["id"],
            "expected_version": current["version"],
        },
    )
    assert handed.status_code == 200, handed.text

    second_session = await _start(client, auth_headers, str(machine[0].id), task["id"])
    listing = await client.get(
        "/api/v1/sessions", headers=auth_headers, params={"task_id": task["id"]}
    )
    row = next(s for s in listing.json() if s["id"] == second_session["id"])
    assert row["sync_cursor_seq"] == cursor
    resumed = (await _sync(client, auth_headers, session_id=second_session["id"])).json()
    assert resumed["items"] == []
    assert resumed["next_cursor"] == cursor


async def test_claim_overlap_from_live_state(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    second = await _second_machine(db_session, machine)
    second_headers = _second_headers(second)
    task = await _task(client, auth_headers, project)
    other = await _task(client, auth_headers, project, "other task")
    started = await _start(client, auth_headers, str(machine[0].id), task["id"])

    mine = await client.post(
        "/api/v1/claims",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "task_id": task["id"],
            "resource_path": "src/app.py",
            "resource_type": "file",
            "ttl_seconds": 3600,
        },
    )
    assert mine.status_code == 201, mine.text
    theirs = await client.post(
        "/api/v1/claims",
        headers={**second_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "task_id": other["id"],
            "resource_path": "src",
            "resource_type": "folder",
            "ttl_seconds": 3600,
        },
    )
    assert theirs.status_code == 201, theirs.text

    body = (await _sync(client, auth_headers, session_id=started["id"])).json()
    claims = [i for i in body["items"] if i["kind"] == "claim"]
    assert [(c["why"], c["claim_id"], c["task_id"]) for c in claims] == [
        ("claim_overlap", theirs.json()["id"], other["id"])
    ]

    filed = await client.post(
        "/api/v1/claims",
        headers={**second_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "task_id": other["id"],
            "resource_path": "docs/notes.md",
            "resource_type": "file",
            "ttl_seconds": 3600,
        },
    )
    assert filed.status_code == 201, filed.text
    scoped = (
        await _sync(client, auth_headers, session_id=started["id"], files=["docs/notes.md"])
    ).json()
    scoped_claims = [i for i in scoped["items"] if i["kind"] == "claim"]
    assert filed.json()["id"] in {c["claim_id"] for c in scoped_claims}


async def test_decision_events_surfaced(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    second = await _second_machine(db_session, machine)
    second_headers = _second_headers(second)
    task = await _task(client, auth_headers, project)
    started = await _start(client, auth_headers, str(machine[0].id), task["id"])
    decided = await client.post(
        "/api/v1/decisions",
        headers={**second_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "task_id": task["id"],
            "title": "Adopt X",
            "body": "Because.",
            "proposed_by_type": "user",
            "proposed_by_id": str(second[0].owner_user_id),
        },
    )
    assert decided.status_code == 201, decided.text
    # Creation emits no event; the accept transition does (admin-only).
    accepted = await client.post(
        f"/api/v1/decisions/{decided.json()['id']}/accept",
        headers=admin_auth_headers,
    )
    assert accepted.status_code == 200, accepted.text
    body = (await _sync(client, auth_headers, session_id=started["id"])).json()
    assert [(i["why"], i["task_id"]) for i in body["items"]] == [("decision", task["id"])]


async def test_roadmap_dependency_events_surfaced(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    second = await _second_machine(db_session, machine)
    second_headers = _second_headers(second)
    task = await _task(client, auth_headers, project)
    upstream = await _task(client, auth_headers, project, "upstream task")
    started = await _start(client, auth_headers, str(machine[0].id), task["id"])

    imported = await client.post(
        "/api/v1/roadmaps/import",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "document": {
                "format": "studio.roadmap/v1",
                "title": "Sync plan",
                "phases": [
                    {
                        "key": "P1",
                        "title": "Phase",
                        "steps": [
                            {"key": "S1", "title": "Upstream step"},
                            {
                                "key": "S2",
                                "title": "Downstream step",
                                "depends_on": ["S1"],
                            },
                        ],
                    }
                ],
            },
        },
    )
    assert imported.status_code == 201, imported.text
    roadmap = imported.json()
    activated = await client.post(
        f"/api/v1/roadmaps/{roadmap['id']}/transitions",
        headers=auth_headers,
        json={
            "transition": "activate",
            "expected_version": roadmap["version"],
        },
    )
    assert activated.status_code == 200, activated.text
    for key, link_task in (("S1", upstream["id"]), ("S2", task["id"])):
        linked = await client.post(
            f"/api/v1/roadmaps/{roadmap['id']}/steps/{key}/links",
            headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"task_id": link_task},
        )
        assert linked.status_code == 201, linked.text

    await _patch_title(
        client, second_headers, upstream["id"], upstream["version"], "upstream moved"
    )
    body = (await _sync(client, auth_headers, session_id=started["id"])).json()
    assert [(i["why"], i["task_id"]) for i in body["items"]] == [
        ("roadmap_dependency", upstream["id"])
    ]


async def test_stateless_agent_task_path_replays(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    agent: AgentModel,
    db_session: AsyncSession,
) -> None:
    second = await _second_machine(db_session, machine)
    task = await _task(client, auth_headers, project)
    await _patch_title(client, _second_headers(second), task["id"], task["version"], "bump")
    params = {"agent_id": str(agent.id), "task_id": task["id"]}
    first = (await _sync(client, auth_headers, **params)).json()
    assert len(first["items"]) == 1
    assert first["items"][0]["why"] == "own_task"
    assert (await _sync(client, auth_headers, **params)).json() == first
    listing = await client.get(
        "/api/v1/sessions", headers=auth_headers, params={"task_id": task["id"]}
    )
    assert listing.json() == []


async def test_invalid_inputs(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    agent: AgentModel,
    db_session: AsyncSession,
) -> None:
    task = await _task(client, auth_headers, project)

    missing = await _sync(client, auth_headers)
    assert missing.status_code == 422
    assert missing.json()["detail"]["error_code"] == "invalid_sync_input"

    unknown = await _sync(client, auth_headers, session_id=str(uuid.uuid4()))
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["error_code"] == "session_not_found"

    bad_limit = await _sync(
        client, auth_headers, agent_id=str(agent.id), task_id=task["id"], limit=0
    )
    assert bad_limit.status_code == 422
    assert bad_limit.json()["detail"]["error_code"] == "invalid_sync_input"

    other_model, _ = await _second_machine(db_session, machine)
    foreign = AgentModel(machine_id=other_model.id, display_name="foreign", agent_kind="")
    db_session.add(foreign)
    await db_session.flush()
    refused = await _sync(client, auth_headers, agent_id=str(foreign.id), task_id=task["id"])
    assert refused.status_code == 409
    assert refused.json()["detail"]["error_code"] == "actor_not_owned"

    started = await _start(client, auth_headers, str(machine[0].id), task["id"])
    ended = await client.patch(f"/api/v1/sessions/{started['id']}/end", headers=auth_headers)
    assert ended.status_code == 200
    gone = await _sync(client, auth_headers, session_id=started["id"])
    assert gone.status_code == 404
    assert gone.json()["detail"]["error_code"] == "session_not_found"


async def test_ai_work_lifecycle_collapses_to_its_latest_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    task, mine, work_id = await _ai_work_lifecycle(
        client, auth_headers, machine, project, db_session
    )
    body = (await _sync(client, auth_headers, session_id=mine["id"])).json()
    assert [(i["why"], i["event_type"], i["task_id"]) for i in body["items"]] == [
        ("own_task", "ai_work.completed", task["id"])
    ]
    assert body["overflow"] == {}

    stored = await client.get(
        "/api/v1/events", headers=auth_headers, params={"project": str(project.id)}
    )
    events = [e for e in stored.json() if e["payload"].get("ai_work_id") == work_id]
    assert sorted(e["event_type"] for e in events) == [
        "ai_work.completed",
        "ai_work.started",
    ]


async def test_ai_work_collapse_replays_identically_without_ack(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    _task, mine, _work_id = await _ai_work_lifecycle(
        client, auth_headers, machine, project, db_session
    )
    first = (await _sync(client, auth_headers, session_id=mine["id"])).json()
    again = (await _sync(client, auth_headers, session_id=mine["id"])).json()
    assert again == first
    assert [i["event_type"] for i in again["items"]] == ["ai_work.completed"]
    assert again["overflow"] == {}


async def test_overflow_then_ack_redelivers_the_dropped_item(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    mine, emitted = await _mixed_batch(
        client, auth_headers, machine, project, db_session, signals=2
    )
    body = (await _sync(client, auth_headers, session_id=mine["id"], max_chars=1000)).json()
    assert [i["event_type"] for i in body["items"]] == [
        "coordination.question",
        "task.updated",
    ]
    assert body["overflow"] == {"coordination": 1}
    assert emitted[0]["seq"] <= body["next_cursor"] < emitted[1]["seq"]

    resumed = (
        await _sync(
            client, auth_headers, session_id=mine["id"], ack=body["next_cursor"], max_chars=1000
        )
    ).json()
    dropped = [i for i in resumed["items"] if i["event_type"] == "coordination.question"]
    assert [i["coordination"]["event_id"] for i in dropped] == [emitted[1]["event_id"]]


async def test_cursor_never_moves_backward_while_draining(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    mine, emitted = await _mixed_batch(
        client, auth_headers, machine, project, db_session, signals=3
    )
    body = (await _sync(client, auth_headers, session_id=mine["id"], max_chars=1000)).json()
    expected = {i["seq"] for i in body["items"]} | {s["seq"] for s in emitted}
    cursors = [body["next_cursor"]]
    delivered = {i["seq"] for i in body["items"]}
    for _ in range(6):
        if not body["items"] and not body["overflow"]:
            break
        body = (
            await _sync(
                client, auth_headers, session_id=mine["id"], ack=body["next_cursor"], max_chars=1000
            )
        ).json()
        cursors.append(body["next_cursor"])
        delivered.update(i["seq"] for i in body["items"] if i["seq"] is not None)
    assert cursors == sorted(cursors)
    assert len(cursors) > 2
    assert delivered == expected
    assert body["items"] == []
    assert body["overflow"] == {}
