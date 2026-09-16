from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.build import BuildModel
from studio_api.db.models.event import EventModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import github as github_service

_WEBHOOK_SECRET = "test-webhook-secret"
_REPO = "studio-org/studio-game"


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_GITHUB_WEBHOOK_SECRET", _WEBHOOK_SECRET)


def _workflow_payload(
    run_id: int,
    status_value: str,
    conclusion: str | None,
    pr_number: int | None = None,
    repo: str = _REPO,
) -> dict[str, object]:
    run: dict[str, object] = {
        "id": run_id,
        "name": "CI",
        "run_number": run_id,
        "status": status_value,
        "conclusion": conclusion,
        "head_branch": "main",
        "head_sha": "abc123def456",
        "html_url": f"https://github.com/studio-org/studio-game/actions/runs/{run_id}",
        "actor": {"login": "dev-one"},
        "pull_requests": [{"number": pr_number}] if pr_number is not None else [],
        "run_started_at": "2026-09-16T10:00:00Z",
        "updated_at": "2026-09-16T10:05:00Z",
    }
    return {
        "action": "completed",
        "workflow_run": run,
        "repository": {"full_name": repo},
    }


async def _deliver(
    client: AsyncClient, payload: dict[str, object], event: str, delivery: str
) -> None:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = await client.post(
        "/api/v1/github/webhook",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200


async def _wire_project(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    repo: str = _REPO,
) -> None:
    response = await client.post(
        f"/api/v1/projects/{project.id}/github-integration",
        headers=admin_auth_headers,
        json={"project_id": str(project.id), "repo_full_name": repo},
    )
    assert response.status_code == 201


async def _seed_builds(
    client: AsyncClient, admin_auth_headers: dict[str, str], project: ProjectModel
) -> None:
    await _wire_project(client, admin_auth_headers, project)
    await _deliver(client, _workflow_payload(2001, "completed", "success"), "workflow_run", "b-1")
    await _deliver(client, _workflow_payload(2002, "completed", "failure"), "workflow_run", "b-2")


async def test_builds_list_filter_and_get(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    empty = await client.get(
        "/api/v1/builds", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert empty.status_code == 200
    assert empty.json() == []

    await _seed_builds(client, admin_auth_headers, project)

    listed = await client.get(
        "/api/v1/builds", headers=auth_headers, params={"project_id": str(project.id)}
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 2

    failed = await client.get(
        "/api/v1/builds",
        headers=auth_headers,
        params={"project_id": str(project.id), "status": "failed"},
    )
    assert len(failed.json()) == 1
    assert failed.json()[0]["conclusion"] == "failure"

    build_id = failed.json()[0]["id"]
    fetched = await client.get(f"/api/v1/builds/{build_id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["workflow_run_id"] == 2002

    missing = await client.get(f"/api/v1/builds/{uuid.uuid4()}", headers=auth_headers)
    assert missing.status_code == 404

    invalid_status = await client.get(
        "/api/v1/builds", headers=auth_headers, params={"status": "exploded"}
    )
    assert invalid_status.status_code == 422


async def test_reconcile_is_idempotent_and_skips_disabled(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    from studio_api.services import projects as projects_service

    await _wire_project(client, admin_auth_headers, project)
    other_project = await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Other Project", None
    )
    response = await client.post(
        f"/api/v1/projects/{other_project.id}/github-integration",
        headers=admin_auth_headers,
        json={"project_id": str(other_project.id), "repo_full_name": "other/repo"},
    )
    assert response.status_code == 201
    response = await client.patch(
        f"/api/v1/projects/{other_project.id}/github-integration",
        headers=admin_auth_headers,
        json={"enabled": False},
    )
    assert response.status_code == 200

    runs = [
        {
            "id": 3001,
            "name": "CI",
            "run_number": 1,
            "status": "completed",
            "conclusion": "success",
            "head_branch": "main",
            "head_sha": "sha1",
            "html_url": "https://example.test/runs/3001",
            "actor": {"login": "dev-one"},
            "pull_requests": [],
            "run_started_at": "2026-09-16T10:00:00Z",
            "updated_at": "2026-09-16T10:05:00Z",
        },
        {
            "id": 3002,
            "name": "CI",
            "run_number": 2,
            "status": "completed",
            "conclusion": "failure",
            "head_branch": "main",
            "head_sha": "sha2",
            "html_url": "https://example.test/runs/3002",
            "actor": {"login": "dev-one"},
            "pull_requests": [],
            "run_started_at": "2026-09-16T11:00:00Z",
            "updated_at": "2026-09-16T11:05:00Z",
        },
    ]
    calls: list[str] = []

    async def _fake_fetch(repo: str, limit: int) -> list[dict[str, Any]]:
        calls.append(repo)
        assert limit == 30
        return runs

    fetch: Callable[[str, int], Awaitable[list[dict[str, Any]]]] = _fake_fetch
    first = await github_service.reconcile_builds(db_session, fetch, 30)
    assert len(first) == 2
    assert calls == [_REPO]

    builds_before = (
        await db_session.execute(select(func.count()).select_from(BuildModel))
    ).scalar_one()
    events_before = (
        await db_session.execute(select(func.count()).select_from(EventModel))
    ).scalar_one()
    second = await github_service.reconcile_builds(db_session, fetch, 30)
    assert len(second) == 2
    builds_after = (
        await db_session.execute(select(func.count()).select_from(BuildModel))
    ).scalar_one()
    events_after = (
        await db_session.execute(select(func.count()).select_from(EventModel))
    ).scalar_one()
    assert builds_after == builds_before
    assert events_after == events_before


async def test_transfer_links_to_build(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    await _seed_builds(client, admin_auth_headers, project)
    builds = await client.get(
        "/api/v1/builds", headers=auth_headers, params={"project_id": str(project.id)}
    )
    build_id = builds.json()[0]["id"]

    unknown = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "build_id": str(uuid.uuid4()),
            "category": "build",
            "filename": "game.zip",
            "content_type": "application/zip",
            "size_bytes": 1024,
        },
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["error_code"] == "build_not_found"

    created = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "build_id": build_id,
            "category": "build",
            "filename": "game.zip",
            "content_type": "application/zip",
            "size_bytes": 1024,
        },
    )
    assert created.status_code == 201
    assert created.json()["build_id"] == build_id


async def test_review_queue_shows_build_failure_and_pr_ready(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
) -> None:
    await _seed_builds(client, admin_auth_headers, project)
    pr = {
        "action": "opened",
        "pull_request": {
            "number": 9,
            "title": "Add level 3",
            "head": {"ref": "feat/level-3", "sha": "abc"},
            "base": {"ref": "main"},
            "merged": False,
            "merge_commit_sha": None,
            "user": {"login": "dev-one"},
            "html_url": "https://github.com/studio-org/studio-game/pull/9",
        },
        "repository": {"full_name": _REPO},
    }
    await _deliver(client, pr, "pull_request", "pr-9")

    response = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    kinds = {item["kind"] for item in response.json()["items"]}
    assert "build_failure" in kinds
    assert "pr_ready" in kinds
    failure = next(item for item in response.json()["items"] if item["kind"] == "build_failure")
    assert failure["conclusion"] == "failure"
    ready = next(item for item in response.json()["items"] if item["kind"] == "pr_ready")
    assert ready["pr_number"] == 9

    merged_pr = dict(pr)
    assert isinstance(merged_pr["pull_request"], dict)
    merged_pr["pull_request"] = {
        **merged_pr["pull_request"],
        "merged": True,
        "merge_commit_sha": "m1",
    }
    merged_pr["action"] = "closed"
    await _deliver(client, merged_pr, "pull_request", "pr-9-merged")

    response = await client.get(
        "/api/v1/review-queue", headers=auth_headers, params={"project_id": str(project.id)}
    )
    kinds = {item["kind"] for item in response.json()["items"]}
    assert "pr_ready" not in kinds
    assert "build_failure" in kinds


async def test_workflow_run_out_of_order_keeps_newer_status(
    client: AsyncClient,
    admin_auth_headers: dict[str, str],
    auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    """A stale `in_progress` delivery arriving after `succeeded` must not
    regress the stored status (nor `updated_at`), while a forward move
    still applies."""
    await _wire_project(client, admin_auth_headers, project)
    done = _workflow_payload(5001, "completed", "success")
    await _deliver(client, done, "workflow_run", "oo-1")
    builds = (
        (await db_session.execute(select(BuildModel).where(BuildModel.project_id == project.id)))
        .scalars()
        .all()
    )
    assert builds[0].status == "succeeded"
    updated_after_done = builds[0].updated_at

    stale = _workflow_payload(5001, "in_progress", None)
    await _deliver(client, stale, "workflow_run", "oo-2")
    builds = (
        (await db_session.execute(select(BuildModel).where(BuildModel.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(builds) == 1
    assert builds[0].status == "succeeded"
    assert builds[0].updated_at == updated_after_done


async def test_transfer_rejects_build_from_another_project(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_auth_headers: dict[str, str],
    project: ProjectModel,
    db_session: AsyncSession,
) -> None:
    from studio_api.services import projects as projects_service

    await _wire_project(client, admin_auth_headers, project)
    other_project = await projects_service.create_project(
        db_session, f"proj-{uuid.uuid4().hex[:8]}", "Other Project", None
    )
    await _wire_project(client, admin_auth_headers, other_project, repo="other/repo")
    await _deliver(
        client,
        _workflow_payload(5002, "completed", "success", repo="other/repo"),
        "workflow_run",
        "oo-3",
    )
    other_builds = await client.get(
        "/api/v1/builds", headers=auth_headers, params={"project_id": str(other_project.id)}
    )
    other_build_id = other_builds.json()[0]["id"]

    response = await client.post(
        "/api/v1/transfers",
        headers=auth_headers,
        json={
            "project_id": str(project.id),
            "build_id": other_build_id,
            "category": "build",
            "filename": "game.zip",
            "content_type": "application/zip",
            "size_bytes": 1024,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "build_project_mismatch"
