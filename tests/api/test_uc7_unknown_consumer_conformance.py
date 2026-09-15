from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime

import httpx
from httpx import AsyncClient
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel

# UC-7 conformance: a fictional client — `unknown-harness` /
# `unknown-provider` / `unknown-model`, no predefined profile, no internal
# documentation consulted — integrates from the public interfaces alone and
# fails only if the core requires prior knowledge of a harness/provider/model
# or a profile. Exercises tasks, events, worklogs, offline-style replay and
# transfers end to end.

UNKNOWN_RUNTIME = {
    "harness": "unknown-harness",
    "provider": "unknown-provider",
    "model": "unknown-model",
}


def _md5_b64(payload: bytes) -> str:
    return base64.b64encode(hashlib.md5(payload).digest()).decode()


async def test_unknown_client_full_vertical_from_public_interfaces(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    machine: tuple[MachineModel, str],
    project: ProjectModel,
) -> None:
    machine_model, _ = machine

    # Discovery/health are reachable with no credential at all.
    health = await client.get("/healthz")
    assert health.status_code == 200

    # Capability absence is detected per response, never presumed.
    unknown_route = await client.get("/api/v1/not-a-real-capability", headers=auth_headers)
    assert unknown_route.status_code == 404

    # Register a provenance identity, declaring unknown runtime metadata.
    registered = await client.post(
        "/api/v1/agents",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"display_name": "unknown client", **UNKNOWN_RUNTIME},
    )
    assert registered.status_code == 201
    agent_id = registered.json()["id"]

    heartbeat = await client.post(
        "/api/v1/heartbeats",
        headers=auth_headers,
        json={
            "machine_id": str(machine_model.id),
            "agent_id": agent_id,
            "client_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert heartbeat.status_code == 200

    # Task lifecycle.
    created = await client.post(
        "/api/v1/tasks",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"project_id": str(project.id), "title": "UC-7 task"},
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert (
        await client.post(f"/api/v1/tasks/{task_id}/claim", headers=auth_headers)
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/tasks/{task_id}/release", headers=auth_headers)
    ).status_code == 200

    # Offline-style replay: the same event_id must never duplicate.
    event_id = uuid.uuid4()
    event_body = {
        "event_id": str(event_id),
        "event_type": "task.updated",
        "project_id": str(project.id),
        "task_id": task_id,
        "actor_type": "agent",
        "actor_id": agent_id,
        "client_timestamp": datetime.now(UTC).isoformat(),
        "payload": {"note": "replayed offline write"},
    }
    first = await client.post("/api/v1/events", headers=auth_headers, json=event_body)
    second = await client.post("/api/v1/events", headers=auth_headers, json=event_body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["server_timestamp"] == second.json()["server_timestamp"]

    history = await client.get(f"/api/v1/events?project={project.id}", headers=auth_headers)
    assert history.status_code == 200
    assert sum(1 for e in history.json() if e["event_id"] == str(event_id)) == 1

    # Worklog lifecycle, incl. the preserved admin-only review.
    work = await client.post(
        "/api/v1/ai-work",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "project_id": str(project.id),
            "task_id": task_id,
            "agent_id": agent_id,
            "summary": "UC-7 work",
            **UNKNOWN_RUNTIME,
        },
    )
    assert work.status_code == 201
    work_id = work.json()["id"]
    for key, value in UNKNOWN_RUNTIME.items():
        assert work.json()[key] == value

    assert (
        await client.patch(
            f"/api/v1/ai-work/{work_id}",
            headers=auth_headers,
            json={"status": "review_requested"},
        )
    ).status_code == 200
    self_approve = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=auth_headers, json={"status": "approved"}
    )
    assert self_approve.status_code == 403
    approved = await client.patch(
        f"/api/v1/ai-work/{work_id}", headers=admin_auth_headers, json={"status": "approved"}
    )
    assert approved.status_code == 200

    # Transfer: bytes never transit through the API (single-PUT via MinIO).
    payload = b"uc7 unknown consumer payload" * 100
    sha256 = hashlib.sha256(payload).hexdigest()
    content_md5 = _md5_b64(payload)
    transfer = await client.post(
        "/api/v1/transfers",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "category": "temporary",
            "filename": "uc7.bin",
            "content_type": "application/octet-stream",
            "size_bytes": len(payload),
        },
    )
    assert transfer.status_code == 201
    transfer_id = transfer.json()["id"]

    initiate = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": content_md5},
    )
    assert initiate.status_code == 200
    assert initiate.json()["multipart"] is False

    async with httpx.AsyncClient() as raw:
        put_response = await raw.put(
            initiate.json()["upload_url"],
            content=payload,
            headers={"Content-Type": "application/octet-stream", "Content-MD5": content_md5},
        )
    assert put_response.status_code == 200

    complete = await client.post(
        f"/api/v1/transfers/{transfer_id}/upload/complete",
        headers=auth_headers,
        json={"size_bytes": len(payload), "sha256": sha256},
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "ready"


async def test_unknown_runtime_metadata_never_gates_capabilities(
    client: AsyncClient,
    auth_headers: dict[str, str],
    other_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    """Two consumers declaring different runtime metadata (one neutral, one
    with privileged-sounding values) get identical capabilities: nothing in
    the core branches on those values. The unknown consumer is never worse
    off than a recognized-sounding one."""
    neutral = await client.post(
        "/api/v1/agents", headers=auth_headers, json={"display_name": "neutral"}
    )
    disguised = await client.post(
        "/api/v1/agents",
        headers=other_auth_headers,
        json={
            "display_name": "disguised",
            "agent_profile": "admin",
            "harness": "totally-unknown-harness",
            "provider": "totally-unknown-provider",
            "model": "totally-unknown-model",
        },
    )
    assert neutral.status_code == 201
    assert disguised.status_code == 201

    for headers in (auth_headers, other_auth_headers):
        created = await client.post(
            "/api/v1/tasks",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"project_id": str(project.id), "title": "capability parity"},
        )
        assert created.status_code == 201


async def test_transfer_payload_is_never_proxied_by_the_api(
    client: AsyncClient, auth_headers: dict[str, str], project: ProjectModel
) -> None:
    """The golden rule holds for an unknown consumer too: `POST /transfers`
    returns metadata, then `upload/initiate` a pre-signed URL — never bytes."""
    transfer = await client.post(
        "/api/v1/transfers",
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "category": "temporary",
            "filename": "uc7-probe.bin",
            "content_type": "application/octet-stream",
            "size_bytes": 16,
        },
    )
    assert transfer.status_code == 201
    assert "upload_url" not in transfer.json()

    initiate = await client.post(
        f"/api/v1/transfers/{transfer.json()['id']}/upload/initiate",
        headers=auth_headers,
        json={"content_md5": _md5_b64(b"0123456789abcdef")},
    )
    assert initiate.status_code == 200
    assert initiate.json()["upload_url"].startswith("http")
