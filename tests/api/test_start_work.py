"""`POST /start-work` (L2/DEC-0159): start or resume work in one call.
With a task: idempotent claim + resume-or-create session + scoped context.
Without: context + candidates, nothing claimed. Real Postgres."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.claim import ResourceClaimModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel

START = "/api/v1/start-work"
Headers = dict[str, str]


async def _task_id(client: AsyncClient, headers: Headers, project: ProjectModel) -> str:
    created = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"project_id": str(project.id), "title": "work task"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _body(project: ProjectModel, agent: AgentModel, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": str(project.id),
        "agent_id": str(agent.id),
    }
    payload.update(overrides)
    return payload


async def test_with_task_claims_starts_and_returns_context(
    client: AsyncClient,
    auth_headers: Headers,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    machine_model, _ = machine
    task_id = await _task_id(client, auth_headers, project)

    response = await client.post(
        START, headers=auth_headers, json=_body(project, agent, task_id=task_id)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["claimed"] is True
    assert body["resumed"] is False
    assert body["task"]["id"] == task_id
    assert body["task"]["claimed_by_machine_id"] == str(machine_model.id)
    assert body["session"]["agent_id"] == str(agent.id)
    assert body["session"]["status"] == "active"
    assert body["prepared_context"]["project"]["id"] == str(project.id)

    sessions = await client.get(
        "/api/v1/sessions", headers=auth_headers, params={"task_id": task_id, "open": "true"}
    )
    assert [row["id"] for row in sessions.json()] == [body["session"]["id"]]


async def test_replay_resumes_and_never_starts_a_second_session(
    client: AsyncClient,
    auth_headers: Headers,
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task_id = await _task_id(client, auth_headers, project)
    body = _body(project, agent, task_id=task_id)

    first = await client.post(START, headers=auth_headers, json=body)
    second = await client.post(START, headers=auth_headers, json=body)
    assert first.status_code == second.status_code == 200
    assert second.json()["resumed"] is True
    assert second.json()["session"]["id"] == first.json()["session"]["id"]

    sessions = await client.get(
        "/api/v1/sessions", headers=auth_headers, params={"task_id": task_id, "open": "true"}
    )
    assert len(sessions.json()) == 1


@pytest.mark.parametrize("resource_owner", [None, "first", "second"])
async def test_same_machine_other_agent_cannot_silently_replace_claim(
    client: AsyncClient,
    auth_headers: Headers,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    db_session: AsyncSession,
    resource_owner: str | None,
) -> None:
    second_agent = AgentModel(machine_id=machine[0].id, display_name="second", agent_kind="codex")
    db_session.add(second_agent)
    await db_session.flush()
    task_id = await _task_id(client, auth_headers, project)
    first = await client.post(
        START, headers=auth_headers, json=_body(project, agent, task_id=task_id)
    )
    assert first.status_code == 200, first.text
    conflict = await client.post(
        START, headers=auth_headers, json=_body(project, second_agent, task_id=task_id)
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error_code"] == "already_claimed"
    manual_claim = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    assert manual_claim.status_code == 409
    task = (await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)).json()
    assert task["claimed_by_agent_id"] == str(agent.id)
    assert task["version"] == first.json()["task"]["version"]
    sessions = (
        await client.get(
            "/api/v1/sessions", headers=auth_headers, params={"task_id": task_id, "open": "true"}
        )
    ).json()
    assert [item["id"] for item in sessions] == [first.json()["session"]["id"]]
    released = await client.post(
        f"/api/v1/tasks/{task_id}/release",
        headers={
            **auth_headers,
            "If-Match-Version": str(task["version"]),
        },
    )
    assert released.status_code == 200, released.text
    transferred = await client.post(
        START, headers=auth_headers, json=_body(project, second_agent, task_id=task_id)
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["session"]["id"] != first.json()["session"]["id"]
    sessions = (
        await client.get("/api/v1/sessions", headers=auth_headers, params={"task_id": task_id})
    ).json()
    assert {item["agent_id"] for item in sessions} == {str(agent.id), str(second_agent.id)}
    claim = await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "task_id": task_id,
            "resource_path": "src/owned-by-second.py",
            "resource_type": "file",
            "ttl_seconds": 600,
        },
    )
    assert claim.status_code == 201, claim.text
    if resource_owner is not None:
        await db_session.execute(
            update(ResourceClaimModel)
            .where(ResourceClaimModel.id == uuid.UUID(claim.json()["id"]))
            .values(claimed_by_agent_id=agent.id if resource_owner == "first" else second_agent.id)
        )
        await db_session.flush()
    old_session_id = first.json()["session"]["id"]
    old_handoff = await client.post(
        "/api/v1/handoff",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "session_id": old_session_id,
            "agent_id": str(agent.id),
            "summary": "Late handoff",
        },
    )
    assert old_handoff.status_code == 409
    assert old_handoff.json()["detail"]["error_code"] == "already_claimed"
    ended = await client.patch(f"/api/v1/sessions/{old_session_id}/end", headers=auth_headers)
    assert ended.status_code == 200, ended.text
    task = (await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)).json()
    assert task["claimed_by_agent_id"] == str(second_agent.id)
    claims = (
        await client.get(
            "/api/v1/claims", headers=auth_headers, params={"project_id": str(project.id)}
        )
    ).json()
    expected_claim_status = "released" if resource_owner == "first" else "active"
    assert (
        next(item for item in claims if item["id"] == claim.json()["id"])["status"]
        == expected_claim_status
    )


async def test_idempotency_key_replays_the_original_result(
    client: AsyncClient,
    auth_headers: Headers,
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task_id = await _task_id(client, auth_headers, project)
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    body = _body(project, agent, task_id=task_id)

    first = await client.post(START, headers=headers, json=body)
    second = await client.post(START, headers=headers, json=body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    # The replayed response is the original (resumed=False), not a re-run.
    assert second.json()["resumed"] is False


async def test_without_task_returns_candidates_and_claims_nothing(
    client: AsyncClient,
    auth_headers: Headers,
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    task_id = await _task_id(client, auth_headers, project)

    response = await client.post(START, headers=auth_headers, json=_body(project, agent))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task"] is None
    assert body["session"] is None
    assert body["claimed"] is False
    assert [c["task_id"] for c in body["candidates"]] == [task_id]
    assert body["candidates"][0]["why"]["reason"] == "project_scope"

    untouched = await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert untouched.json()["claimed_by_machine_id"] is None


async def test_unknown_or_foreign_task_is_not_found(
    client: AsyncClient,
    auth_headers: Headers,
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    unknown = await client.post(
        START,
        headers=auth_headers,
        json=_body(project, agent, task_id=str(uuid.uuid4())),
    )
    assert unknown.status_code == 404


async def test_agent_of_another_machine_is_refused(
    client: AsyncClient,
    auth_headers: Headers,
    project: ProjectModel,
    db_session: AsyncSession,
    other_machine: tuple[MachineModel, str],
) -> None:
    other_model, _ = other_machine
    foreign_agent = AgentModel(
        machine_id=other_model.id, display_name="foreign", agent_kind="other"
    )
    db_session.add(foreign_agent)
    await db_session.flush()

    response = await client.post(START, headers=auth_headers, json=_body(project, foreign_agent))
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "actor_not_owned"


async def test_readonly_is_forbidden(
    client: AsyncClient,
    readonly_auth_headers: Headers,
    project: ProjectModel,
    db_session: AsyncSession,
    readonly_machine: tuple[MachineModel, str],
) -> None:
    readonly_model, _ = readonly_machine
    agent = AgentModel(machine_id=readonly_model.id, display_name="ro", agent_kind="")
    db_session.add(agent)
    await db_session.flush()

    # Authorization runs before the idempotency short-circuit: a valid key
    # never lets a read-only caller through.
    response = await client.post(
        START,
        headers={**readonly_auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json=_body(project, agent),
    )
    assert response.status_code == 403
