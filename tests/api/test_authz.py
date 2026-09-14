from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.user import UserModel
from studio_api.services import provisioning as provisioning_service

# --- Write-gate matrix: `readonly` never writes shared state anywhere ---


async def _post_task(client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID) -> int:
    response = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"project_id": str(project_id), "title": "t"},
    )
    return response.status_code


async def test_readonly_cannot_create_task(
    client: AsyncClient, readonly_auth_headers: dict[str, str], project: ProjectModel
) -> None:
    status_code = await _post_task(client, readonly_auth_headers, project.id)
    assert status_code == 403


async def test_readonly_cannot_create_claim(
    client: AsyncClient, readonly_auth_headers: dict[str, str], project: ProjectModel
) -> None:
    response = await client.post(
        "/api/v1/claims",
        headers=readonly_auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "src/foo.py",
            "resource_type": "file",
            "ttl_seconds": 60,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "forbidden"


async def test_readonly_cannot_start_session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    readonly_machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    task_response = await client.post(
        "/api/v1/tasks", headers=auth_headers, json={"project_id": str(project.id), "title": "t"}
    )
    task_id = task_response.json()["id"]

    response = await client.post(
        "/api/v1/sessions",
        headers=readonly_auth_headers,
        json={"task_id": task_id, "machine_id": str(readonly_machine[0].id)},
    )
    assert response.status_code == 403


async def test_readonly_cannot_log_ai_work(
    client: AsyncClient,
    readonly_auth_headers: dict[str, str],
    readonly_machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    agent = AgentModel(
        machine_id=readonly_machine[0].id, display_name="ro-agent", agent_kind="claude_code"
    )
    db_session.add(agent)
    await db_session.flush()
    await db_session.refresh(agent)

    response = await client.post(
        "/api/v1/ai-work",
        headers=readonly_auth_headers,
        json={"project_id": str(project.id), "agent_id": str(agent.id), "summary": "s"},
    )
    assert response.status_code == 403


async def test_readonly_cannot_add_decision(
    client: AsyncClient,
    readonly_auth_headers: dict[str, str],
    readonly_machine: tuple[MachineModel, str],
) -> None:
    response = await client.post(
        "/api/v1/decisions",
        headers=readonly_auth_headers,
        json={
            "title": "t",
            "body": "b",
            "proposed_by_type": "user",
            "proposed_by_id": str(readonly_machine[0].owner_user_id),
        },
    )
    assert response.status_code == 403


async def test_readonly_cannot_post_event(
    client: AsyncClient,
    readonly_auth_headers: dict[str, str],
    readonly_machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    response = await client.post(
        "/api/v1/events",
        headers=readonly_auth_headers,
        json={
            "event_id": str(uuid.uuid4()),
            "event_type": "task.created",
            "project_id": str(project.id),
            "actor_type": "user",
            "actor_id": str(readonly_machine[0].owner_user_id),
            "client_timestamp": datetime.now(UTC).isoformat(),
            "payload": {},
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "forbidden"


async def test_readonly_cannot_create_transfer(
    client: AsyncClient, readonly_auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/transfers",
        headers=readonly_auth_headers,
        json={
            "category": "temporary",
            "filename": "f.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 10,
        },
    )
    assert response.status_code == 403


async def test_readonly_can_still_read_and_heartbeat(
    client: AsyncClient,
    readonly_auth_headers: dict[str, str],
    readonly_machine: tuple[MachineModel, str],
) -> None:
    projects = await client.get("/api/v1/projects", headers=readonly_auth_headers)
    assert projects.status_code == 200

    machine_model, _ = readonly_machine
    response = await client.post(
        "/api/v1/heartbeats",
        headers=readonly_auth_headers,
        json={
            "machine_id": str(machine_model.id),
            "client_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200


async def test_agent_role_writes_like_developer_but_cannot_provision(
    client: AsyncClient, agent_auth_headers: dict[str, str], project: ProjectModel
) -> None:
    task_status = await _post_task(client, agent_auth_headers, project.id)
    assert task_status == 201

    provision = await client.post(
        "/api/v1/projects",
        headers=agent_auth_headers,
        json={"slug": f"p-{uuid.uuid4().hex[:6]}", "name": "n"},
    )
    assert provision.status_code == 403


# --- Ownership: task release, claim renew/release, session end, ai-work PATCH ---


async def test_task_release_by_non_owning_machine_is_forbidden(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    created = await client.post(
        "/api/v1/tasks", headers=auth_headers, json={"project_id": str(project.id), "title": "t"}
    )
    task_id = created.json()["id"]
    claimed = await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    assert claimed.status_code == 200

    forbidden = await client.post(f"/api/v1/tasks/{task_id}/release", headers=other_auth_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["error_code"] == "forbidden"

    allowed = await client.post(f"/api/v1/tasks/{task_id}/release", headers=auth_headers)
    assert allowed.status_code == 200


async def test_task_release_by_admin_is_allowed_regardless_of_owner(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    created = await client.post(
        "/api/v1/tasks", headers=auth_headers, json={"project_id": str(project.id), "title": "t"}
    )
    task_id = created.json()["id"]
    await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)

    response = await client.post(f"/api/v1/tasks/{task_id}/release", headers=admin_auth_headers)
    assert response.status_code == 200


async def test_claim_renew_and_release_by_non_owning_machine_is_forbidden(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    created = await client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "resource_path": "src/bar.py",
            "resource_type": "file",
            "ttl_seconds": 60,
        },
    )
    claim_id = created.json()["id"]

    renew_forbidden = await client.post(
        f"/api/v1/claims/{claim_id}/renew", headers=other_auth_headers
    )
    assert renew_forbidden.status_code == 403

    release_forbidden = await client.delete(
        f"/api/v1/claims/{claim_id}", headers=other_auth_headers
    )
    assert release_forbidden.status_code == 403

    renew_ok = await client.post(f"/api/v1/claims/{claim_id}/renew", headers=auth_headers)
    assert renew_ok.status_code == 200


async def test_session_end_by_non_owning_machine_is_forbidden(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    task = await client.post(
        "/api/v1/tasks", headers=auth_headers, json={"project_id": str(project.id), "title": "t"}
    )
    task_id = task.json()["id"]
    session = await client.post(
        "/api/v1/sessions",
        headers=auth_headers,
        json={"task_id": task_id, "machine_id": str(machine[0].id)},
    )
    session_id = session.json()["id"]

    forbidden = await client.patch(f"/api/v1/sessions/{session_id}/end", headers=other_auth_headers)
    assert forbidden.status_code == 403

    allowed = await client.patch(f"/api/v1/sessions/{session_id}/end", headers=auth_headers)
    assert allowed.status_code == 200


async def test_ai_work_patch_by_non_owning_machine_is_forbidden(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    agent = AgentModel(
        machine_id=machine[0].id, display_name="owner-agent", agent_kind="claude_code"
    )
    db_session.add(agent)
    await db_session.flush()
    await db_session.refresh(agent)

    created = await client.post(
        "/api/v1/ai-work",
        headers=auth_headers,
        json={"project_id": str(project.id), "agent_id": str(agent.id), "summary": "s"},
    )
    work_id = created.json()["id"]

    forbidden = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=other_auth_headers, json={"summary": "hijacked"}
    )
    assert forbidden.status_code == 403

    allowed = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"summary": "updated"}
    )
    assert allowed.status_code == 200


# --- Transfer: sender / recipient / broadcast / admin, per TECH/04 Autorisation ---


async def test_transfer_third_party_cannot_read_scoped_transfer(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    # sender = `auth_headers`; recipient is a third user with no machine in
    # this test, so `other_auth_headers` is a genuinely uninvolved party
    # (neither sender, recipient, nor a broadcast with recipient_user_id=None).
    recipient = await provisioning_service.create_user(
        db_session, "Recipient", f"{uuid.uuid4()}@example.test", "developer"
    )
    created = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "recipient_user_id": str(recipient.id),
            "category": "temporary",
            "filename": "f.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 10,
        },
    )
    transfer_id = created.json()["id"]

    third_party = await client.get(f"/api/v1/transfers/{transfer_id}", headers=other_auth_headers)
    assert third_party.status_code == 403
    assert third_party.json()["detail"]["error_code"] == "forbidden"

    sender_read = await client.get(f"/api/v1/transfers/{transfer_id}", headers=auth_headers)
    assert sender_read.status_code == 200

    admin_read = await client.get(f"/api/v1/transfers/{transfer_id}", headers=admin_auth_headers)
    assert admin_read.status_code == 200


async def test_transfer_recipient_can_read_but_not_delete(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    recipient_user_id = other_machine[0].owner_user_id
    created = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "recipient_user_id": str(recipient_user_id),
            "category": "temporary",
            "filename": "f.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 10,
        },
    )
    transfer_id = created.json()["id"]

    recipient_read = await client.get(
        f"/api/v1/transfers/{transfer_id}", headers=other_auth_headers
    )
    assert recipient_read.status_code == 200

    recipient_delete = await client.delete(
        f"/api/v1/transfers/{transfer_id}", headers=other_auth_headers
    )
    assert recipient_delete.status_code == 403

    sender_delete = await client.delete(f"/api/v1/transfers/{transfer_id}", headers=auth_headers)
    assert sender_delete.status_code == 204


async def test_transfer_download_url_forbidden_for_uninvolved_third_party(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    recipient = await provisioning_service.create_user(
        db_session, "Recipient", f"{uuid.uuid4()}@example.test", "developer"
    )
    created = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "recipient_user_id": str(recipient.id),
            "category": "temporary",
            "filename": "f.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 10,
        },
    )
    transfer_id = created.json()["id"]

    third_party = await client.post(
        f"/api/v1/transfers/{transfer_id}/download-url", headers=other_auth_headers
    )
    assert third_party.status_code == 403
    assert third_party.json()["detail"]["error_code"] == "forbidden"

    sender = await client.post(
        f"/api/v1/transfers/{transfer_id}/download-url", headers=auth_headers
    )
    assert sender.status_code == 200


async def test_broadcast_transfer_readable_by_any_authenticated_user(
    client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "category": "build",
            "filename": "build.zip",
            "content_type": "application/zip",
            "size_bytes": 10,
        },
    )
    transfer_id = created.json()["id"]

    read_by_other = await client.get(f"/api/v1/transfers/{transfer_id}", headers=other_auth_headers)
    assert read_by_other.status_code == 200

    write_by_other = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=other_auth_headers,
        json={"content_md5": "irrelevant"},
    )
    assert write_by_other.status_code == 403


async def test_transfer_list_filters_by_visibility_not_403(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    recipient = await provisioning_service.create_user(
        db_session, "Recipient", f"{uuid.uuid4()}@example.test", "developer"
    )
    created = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "recipient_user_id": str(recipient.id),
            "category": "temporary",
            "filename": "private.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 10,
        },
    )
    transfer_id = created.json()["id"]

    listing = await client.get("/api/v1/transfers", headers=other_auth_headers)
    assert listing.status_code == 200
    assert transfer_id not in [t["id"] for t in listing.json()]


# --- Idempotent replay never bypasses authorization ---


async def test_idempotent_replay_after_role_downgrade_is_still_forbidden(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
    project: ProjectModel,
) -> None:
    """`run_idempotent`'s cache-hit path returns the stored response without
    ever calling `_create()` again — if the write-gate lived only inside
    `tasks_service.create_task` (reached only through `_create()`), a caller
    downgraded to `readonly` after its original write could still replay the
    same `Idempotency-Key` + body and get back the original 201, never
    seeing a 403. `ensure_can_write` must run unconditionally, ahead of the
    idempotency check itself, so a replay under a since-downgraded role is
    rejected exactly like a first attempt (DEC-0036)."""
    machine_model, token = machine
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
    body = {"project_id": str(project.id), "title": "t"}

    first = await client.post("/api/v1/tasks", headers=headers, json=body)
    assert first.status_code == 201

    owner = await db_session.get(UserModel, machine_model.owner_user_id)
    assert owner is not None
    owner.role = "readonly"
    await db_session.flush()

    replay = await client.post("/api/v1/tasks", headers=headers, json=body)
    assert replay.status_code == 403
    assert replay.json()["detail"]["error_code"] == "forbidden"


# --- Revocation stays immediate on a role-gated write endpoint ---


async def test_revoked_machine_cannot_write_even_with_developer_role(
    client: AsyncClient,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
    project: ProjectModel,
) -> None:
    machine_model, token = machine
    headers = {"Authorization": f"Bearer {token}"}
    ok = await _post_task(client, headers, project.id)
    assert ok == 201

    machine_model.credential_revoked_at = datetime.now(UTC)
    await db_session.flush()

    denied = await _post_task(client, headers, project.id)
    assert denied == 401
