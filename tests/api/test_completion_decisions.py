"""DEC-0363 over HTTP: structured decision review at handoff.

v1 without a review closes with a non-blocking `decision_review_missing`
warning; v2 without a review refuses `completed` (`409`). Referenced ids must
exist in the project (`422 decision_reference_invalid`, one generic code that
reveals nothing outside the caller's scope); a `proposed` decision is a valid
reference and is never auto-accepted. Replay is idempotent, warnings included.
Needs the real Postgres test DB."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import projects as projects_service

from tests.api.test_decisions import _create_decision
from tests.api.test_handoff import _claim_task, _session, _task, _task_version

Json = dict[str, Any]


def _completion(**extra: Any) -> Json:
    return {
        "kind": "audit",
        "artifacts": ["vault:report"],
        "checks": [{"name": "report review", "kind": "review", "status": "passed"}],
        **extra,
    }


async def _handoff_body(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
    completion: Json,
    status: str = "completed",
) -> Json:
    task = await _task(client, auth_headers, project)
    task_id = str(task["id"])
    await _claim_task(client, auth_headers, task_id)
    session_id = await _session(client, auth_headers, machine, agent, task_id)
    return {
        "project_id": str(project.id),
        "session_id": session_id,
        "expected_version": await _task_version(client, auth_headers, task_id),
        "task_status": {"status": status},
        "agent_id": str(agent.id),
        "summary": "Reviewed work",
        "completion": completion,
    }


async def _second_project(db_session: AsyncSession) -> ProjectModel:
    return await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Other Project", None, creator=None
    )


async def test_v1_without_review_warns_but_closes(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    body = await _handoff_body(client, auth_headers, machine, agent, project, _completion())
    result = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["task_status"] == "completed"
    assert result.json()["warnings"] == ["decision_review_missing"]


async def test_v2_without_review_refuses_completed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    body = await _handoff_body(
        client, auth_headers, machine, agent, project, _completion(format="studio.completion/v2")
    )
    rejected = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["error_code"] == "completion_incomplete"
    assert "decision_review_missing" in rejected.json()["detail"]["issues"]


async def test_v2_with_existing_decision_closes_without_warning(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)
    body = await _handoff_body(
        client,
        auth_headers,
        machine,
        agent,
        project,
        _completion(
            format="studio.completion/v2",
            decisions={"outcome": "existing", "decision_ids": [decision["id"]]},
        ),
    )
    result = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["task_status"] == "completed"
    assert result.json()["warnings"] == []


async def test_v2_readable_id_reference_closes(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)
    body = await _handoff_body(
        client,
        auth_headers,
        machine,
        agent,
        project,
        _completion(
            format="studio.completion/v2",
            decisions={"outcome": "new", "decision_ids": [decision["readable_id"]]},
        ),
    )
    result = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert result.status_code == 200, result.text
    listing = await client.get(
        "/api/v1/decisions", headers=auth_headers, params={"project_id": str(project.id)}
    )
    matching = [d for d in listing.json() if d["id"] == decision["id"]]
    assert len(matching) == 1 and matching[0]["status"] == "proposed"


async def test_v2_motivated_absence_with_reason_closes(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    body = await _handoff_body(
        client,
        auth_headers,
        machine,
        agent,
        project,
        _completion(
            format="studio.completion/v2",
            decisions={
                "outcome": "none",
                "reason": "Routine dependency bump, no decision involved.",
            },
        ),
    )
    result = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["warnings"] == []


async def test_v2_motivated_absence_without_reason_is_refused(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    body = await _handoff_body(
        client,
        auth_headers,
        machine,
        agent,
        project,
        _completion(format="studio.completion/v2", decisions={"outcome": "none", "reason": "  "}),
    )
    rejected = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["error_code"] == "completion_incomplete"
    assert "decision_reason_missing" in rejected.json()["detail"]["issues"]


async def test_unknown_decision_id_is_rejected_without_oracle(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    body = await _handoff_body(
        client,
        auth_headers,
        machine,
        agent,
        project,
        _completion(decisions={"outcome": "existing", "decision_ids": [str(uuid.uuid4())]}),
    )
    rejected = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["error_code"] == "decision_reference_invalid"


async def test_other_project_decision_is_rejected_like_unknown(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    machine_model, _ = machine
    other = await _second_project(db_session)
    foreign = await _create_decision(client, auth_headers, other, machine_model.id)
    body = await _handoff_body(
        client,
        auth_headers,
        machine,
        agent,
        project,
        _completion(decisions={"outcome": "existing", "decision_ids": [foreign["id"]]}),
    )
    rejected = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert rejected.status_code == 422
    # Same generic error as an unknown id: no existence oracle, no leaked id.
    assert rejected.json()["detail"]["error_code"] == "decision_reference_invalid"
    assert set(rejected.json()["detail"]) == {"error_code", "message"}


async def test_decision_review_replay_is_idempotent(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
) -> None:
    machine_model, _ = machine
    decision = await _create_decision(client, auth_headers, project, machine_model.id)
    body = await _handoff_body(
        client,
        auth_headers,
        machine,
        agent,
        project,
        _completion(
            format="studio.completion/v2",
            decisions={"outcome": "existing", "decision_ids": [decision["id"]]},
        ),
    )
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    first = await client.post("/api/v1/handoff", headers=headers, json=body)
    assert first.status_code == 200, first.text
    replayed = await client.post("/api/v1/handoff", headers=headers, json=body)
    assert replayed.json() == first.json()
