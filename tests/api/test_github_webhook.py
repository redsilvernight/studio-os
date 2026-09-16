from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.build import BuildModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel

_WEBHOOK_SECRET = "test-webhook-secret"
_REPO = "studio-org/studio-game"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _headers(github_event: str, body: bytes, delivery: str | None = None) -> dict[str, str]:
    headers = {
        "X-GitHub-Event": github_event,
        "X-Hub-Signature-256": _sign(body),
        "Content-Type": "application/json",
    }
    if delivery is not None:
        headers["X-GitHub-Delivery"] = delivery
    return headers


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_GITHUB_WEBHOOK_SECRET", _WEBHOOK_SECRET)


async def _wire_project(
    client: AsyncClient, admin_auth_headers: dict[str, str], project: ProjectModel
) -> None:
    response = await client.post(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=admin_auth_headers,
        json={"project_id": str(project.id), "repo_full_name": _REPO},
    )
    assert response.status_code == 201


async def _event_count(db_session: AsyncSession) -> int:
    return (await db_session.execute(select(func.count()).select_from(EventModel))).scalar_one()


def _push_payload() -> dict[str, object]:
    return {
        "ref": "refs/heads/main",
        "after": "abc123def456",
        "deleted": False,
        "head_commit": {
            "id": "abc123def456",
            "message": "Add level 3",
            "author": {"username": "dev-one"},
        },
        "repository": {"full_name": _REPO},
    }


def _pr_payload(action: str, merged: bool = False) -> dict[str, object]:
    return {
        "action": action,
        "pull_request": {
            "number": 7,
            "title": "Add level 3",
            "head": {"ref": "feat/level-3", "sha": "abc123def456"},
            "base": {"ref": "main"},
            "merged": merged,
            "merge_commit_sha": "merge999" if merged else None,
            "user": {"login": "dev-one"},
            "html_url": "https://github.com/studio-org/studio-game/pull/7",
        },
        "repository": {"full_name": _REPO},
    }


def _workflow_payload(
    run_id: int = 1001, status_value: str = "completed", conclusion: str | None = "success"
) -> dict[str, object]:
    return {
        "action": "completed",
        "workflow_run": {
            "id": run_id,
            "name": "CI",
            "run_number": 5,
            "status": status_value,
            "conclusion": conclusion,
            "head_branch": "main",
            "head_sha": "abc123def456",
            "html_url": "https://github.com/studio-org/studio-game/actions/runs/1001",
            "actor": {"login": "dev-one"},
            "pull_requests": [],
            "run_started_at": "2026-09-16T10:00:00Z",
            "updated_at": "2026-09-16T10:05:00Z",
        },
        "repository": {"full_name": _REPO},
    }


async def test_webhook_rejects_missing_secret(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STUDIO_GITHUB_WEBHOOK_SECRET", raising=False)
    body = json.dumps(_push_payload()).encode()
    response = await client.post(
        "/api/v1/github/webhook", content=body, headers=_headers("push", body, "d-1")
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "webhook_not_configured"


async def test_webhook_rejects_bad_signature(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    body = json.dumps(_push_payload()).encode()
    headers = _headers("push", body, "d-1")
    headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    response = await client.post("/api/v1/github/webhook", content=body, headers=headers)
    assert response.status_code == 401


async def test_webhook_rejects_missing_signature(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    body = json.dumps(_push_payload()).encode()
    headers = _headers("push", body, "d-1")
    del headers["X-Hub-Signature-256"]
    response = await client.post("/api/v1/github/webhook", content=body, headers=headers)
    assert response.status_code == 401


async def test_webhook_rejects_oversize_body(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    monkeypatch.setenv("STUDIO_GITHUB_WEBHOOK_MAX_BODY_BYTES", "10")
    body = json.dumps(_push_payload()).encode()
    response = await client.post(
        "/api/v1/github/webhook", content=body, headers=_headers("push", body, "d-1")
    )
    assert response.status_code == 413


async def test_webhook_rejects_invalid_json(client: AsyncClient) -> None:
    body = b"{not json"
    response = await client.post(
        "/api/v1/github/webhook", content=body, headers=_headers("push", body, "d-1")
    )
    assert response.status_code == 400


async def test_webhook_requires_delivery_headers(client: AsyncClient) -> None:
    body = json.dumps(_push_payload()).encode()
    headers = _headers("push", body)
    response = await client.post("/api/v1/github/webhook", content=body, headers=headers)
    assert response.status_code == 400


async def test_push_emits_branch_and_commit(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    body = json.dumps(_push_payload()).encode()
    response = await client.post(
        "/api/v1/github/webhook", content=body, headers=_headers("push", body, "d-push-1")
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    types = (
        (
            await db_session.execute(
                select(EventModel.event_type).where(EventModel.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert "git.branch.changed" in types
    assert "git.commit" in types


async def test_push_redelivery_creates_no_duplicate_events(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    body = json.dumps(_push_payload()).encode()
    headers = _headers("push", body, "d-push-2")
    first = await client.post("/api/v1/github/webhook", content=body, headers=headers)
    assert first.status_code == 200
    count_after_first = await _event_count(db_session)
    second = await client.post("/api/v1/github/webhook", content=body, headers=headers)
    assert second.status_code == 200
    assert await _event_count(db_session) == count_after_first


async def test_pr_opened_then_merged(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    opened = json.dumps(_pr_payload("opened")).encode()
    response = await client.post(
        "/api/v1/github/webhook", content=opened, headers=_headers("pull_request", opened, "d-pr-1")
    )
    assert response.status_code == 200
    assert response.json()["pr_number"] == 7
    merged = json.dumps(_pr_payload("closed", merged=True)).encode()
    response = await client.post(
        "/api/v1/github/webhook", content=merged, headers=_headers("pull_request", merged, "d-pr-2")
    )
    assert response.status_code == 200
    types = (
        (
            await db_session.execute(
                select(EventModel.event_type).where(EventModel.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert "git.pr.opened" in types
    assert "git.pr.merged" in types


async def test_pr_uninteresting_action_is_ignored(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    body = json.dumps(_pr_payload("synchronize")).encode()
    before = await _event_count(db_session)
    response = await client.post(
        "/api/v1/github/webhook",
        content=body,
        headers=_headers("pull_request", body, "d-pr-3"),
    )
    assert response.status_code == 202
    assert await _event_count(db_session) == before


async def test_unknown_event_is_202(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    body = json.dumps({"zen": "hello", "repository": {"full_name": _REPO}}).encode()
    before = await _event_count(db_session)
    response = await client.post(
        "/api/v1/github/webhook", content=body, headers=_headers("ping", body, "d-ping-1")
    )
    assert response.status_code == 202
    assert await _event_count(db_session) == before


async def test_unknown_repository_is_202(
    client: AsyncClient,
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    payload = _push_payload()
    assert isinstance(payload["repository"], dict)
    payload["repository"] = {"full_name": "someone-else/other-repo"}
    body = json.dumps(payload).encode()
    before = await _event_count(db_session)
    response = await client.post(
        "/api/v1/github/webhook", content=body, headers=_headers("push", body, "d-unknown-1")
    )
    assert response.status_code == 202
    assert await _event_count(db_session) == before


async def test_workflow_run_upserts_build_and_emits_started_then_succeeded(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    running = json.dumps(_workflow_payload(status_value="in_progress", conclusion=None)).encode()
    response = await client.post(
        "/api/v1/github/webhook",
        content=running,
        headers=_headers("workflow_run", running, "d-run-1"),
    )
    assert response.status_code == 200
    build_id = response.json()["build_id"]
    assert build_id is not None

    done = json.dumps(_workflow_payload()).encode()
    response = await client.post(
        "/api/v1/github/webhook",
        content=done,
        headers=_headers("workflow_run", done, "d-run-2"),
    )
    assert response.status_code == 200
    assert response.json()["build_id"] == build_id

    builds = (
        (await db_session.execute(select(BuildModel).where(BuildModel.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(builds) == 1
    assert builds[0].status == "succeeded"
    types = (
        (
            await db_session.execute(
                select(EventModel.event_type).where(EventModel.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert "build.started" in types
    assert "build.succeeded" in types


async def test_workflow_run_redelivery_upserts_same_row(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    body = json.dumps(_workflow_payload()).encode()
    headers = _headers("workflow_run", body, "d-run-3")
    await client.post("/api/v1/github/webhook", content=body, headers=headers)
    await client.post("/api/v1/github/webhook", content=body, headers=headers)
    builds = (
        (await db_session.execute(select(BuildModel).where(BuildModel.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(builds) == 1


async def test_workflow_run_failed_status(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    body = json.dumps(_workflow_payload(status_value="completed", conclusion="failure")).encode()
    response = await client.post(
        "/api/v1/github/webhook",
        content=body,
        headers=_headers("workflow_run", body, "d-run-4"),
    )
    assert response.status_code == 200
    builds = (
        (await db_session.execute(select(BuildModel).where(BuildModel.project_id == project.id)))
        .scalars()
        .all()
    )
    assert builds[0].status == "failed"
    types = (
        (
            await db_session.execute(
                select(EventModel.event_type).where(EventModel.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    assert "build.failed" in types


async def test_disabled_integration_is_ignored(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    response = await client.patch(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=admin_auth_headers,
        json={"enabled": False},
    )
    assert response.status_code == 200
    body = json.dumps(_push_payload()).encode()
    before = await _event_count(db_session)
    response = await client.post(
        "/api/v1/github/webhook", content=body, headers=_headers("push", body, "d-push-9")
    )
    assert response.status_code == 202
    assert await _event_count(db_session) == before


async def test_integration_crud_and_roles(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    auth_headers: dict[str, str],
    readonly_auth_headers: dict[str, str],
    agent_auth_headers: dict[str, str],
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    assert machine is not None
    created = await client.post(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=auth_headers,
        json={"project_id": str(project.id), "repo_full_name": _REPO},
    )
    assert created.status_code == 201
    assert created.json()["repo_full_name"] == _REPO
    assert created.json()["default_branch"] == "main"
    assert created.json()["enabled"] is True

    duplicate = await client.post(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=admin_auth_headers,
        json={"project_id": str(project.id), "repo_full_name": "other/repo"},
    )
    assert duplicate.status_code == 409

    mismatched = await client.post(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=admin_auth_headers,
        json={"project_id": str(uuid.uuid4()), "repo_full_name": "other/repo"},
    )
    assert mismatched.status_code == 409

    readonly = await client.post(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=readonly_auth_headers,
        json={"project_id": str(project.id), "repo_full_name": "other/repo"},
    )
    assert readonly.status_code == 403

    agent_denied = await client.post(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=agent_auth_headers,
        json={"project_id": str(project.id), "repo_full_name": "other/repo"},
    )
    assert agent_denied.status_code == 403

    fetched = await client.get(
        f"/api/v1/projects/{project.id}/github-integration", headers=auth_headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created.json()["id"]

    patched = await client.patch(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=admin_auth_headers,
        json={"default_branch": "develop"},
    )
    assert patched.status_code == 200
    assert patched.json()["default_branch"] == "develop"

    patched_denied = await client.patch(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=readonly_auth_headers,
        json={"enabled": False},
    )
    assert patched_denied.status_code == 403
