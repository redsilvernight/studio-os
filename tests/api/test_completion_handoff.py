from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.ai_work import AIWorkLogModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel

from tests.api.test_handoff import _claim_task, _resource_claim, _session, _task, _task_version


async def test_incomplete_evidence_does_not_close_and_verified_audit_closes_without_git(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    task = await _task(client, auth_headers, project)
    task_id = str(task["id"])
    await _claim_task(client, auth_headers, task_id)
    claim_id = await _resource_claim(client, auth_headers, project, task_id)
    session_id = await _session(client, auth_headers, machine, agent, task_id)
    body = {
        "project_id": str(project.id),
        "session_id": session_id,
        "expected_version": await _task_version(client, auth_headers, task_id),
        "task_status": {"status": "completed"},
        "agent_id": str(agent.id),
        "summary": "Audit verified",
        "completion": {
            "kind": "audit",
            "artifacts": ["vault:report"],
            "checks": [{"name": "pytest", "status": "passed", "exit_code": 1}],
        },
    }
    rejected = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["error_code"] == "completion_incomplete"
    current = (await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)).json()
    assert current["status"] == "in_progress"
    assert current["version"] == body["expected_version"]
    body["completion"]["checks"] = [{"name": "report review", "kind": "review", "status": "passed"}]
    headers = {**auth_headers, "Idempotency-Key": str(uuid4())}
    result = await client.post("/api/v1/handoff", headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["task_status"] == "completed"
    assert result.json()["released_claims"] == [claim_id]
    replay = await client.post("/api/v1/handoff", headers=headers, json=body)
    assert replay.json() == result.json()
    body["completion"]["artifacts"] = ["vault:other-report"]
    mismatch = await client.post("/api/v1/handoff", headers=headers, json=body)
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error_code"] == "idempotency_key_payload_mismatch"
    entry = await db_session.get(AIWorkLogModel, UUID(result.json()["ai_work_id"]))
    assert entry is not None
    assert "COMPLETION kind=audit ready=true" in entry.summary
    assert '"versioned": false' in entry.summary
    assert '"deployed": false' in entry.summary


@pytest.mark.parametrize("missing_field", ["agent_id", "summary"])
async def test_evidence_without_work_log_does_not_update_task(
    client: AsyncClient,
    auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    agent: AgentModel,
    project: ProjectModel,
    missing_field: str,
) -> None:
    task = await _task(client, auth_headers, project)
    task_id = str(task["id"])
    await _claim_task(client, auth_headers, task_id)
    session_id = await _session(client, auth_headers, machine, agent, task_id)
    version = await _task_version(client, auth_headers, task_id)
    body = {
        "project_id": str(project.id),
        "session_id": session_id,
        "expected_version": version,
        "task_status": {"status": "completed"},
        "agent_id": str(agent.id),
        "summary": "Verified audit",
        "completion": {
            "kind": "audit",
            "artifacts": ["vault:report"],
            "checks": [{"name": "report review", "kind": "review", "status": "passed"}],
        },
    }
    body.pop(missing_field)
    rejected = await client.post("/api/v1/handoff", headers=auth_headers, json=body)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["error_code"] == "completion_log_required"
    current = (await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)).json()
    assert current["status"] == "in_progress"
    assert current["version"] == version
