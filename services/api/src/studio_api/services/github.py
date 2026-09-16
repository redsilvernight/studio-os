from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.builds import (
    BuildStatus,
    GitHubIntegrationCreate,
    GitHubIntegrationUpdate,
)
from studio_contracts.events import EventCreate, EventType

from studio_api.db.models.build import BuildModel, GitHubIntegrationModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import events as events_service
from studio_api.services.authz import Principal, ensure_can_provision

_GITHUB_API = "https://api.github.com"


def verify_signature(secret: bytes, body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 check of the raw webhook body (DEC-0059) —
    the body must be read before any JSON parsing, and the secret is never
    logged nor returned. Missing or malformed signature is simply False."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    try:
        received = bytes.fromhex(signature_header[len("sha256=") :])
    except ValueError:
        return False
    expected = hmac.new(secret, body, hashlib.sha256).digest()
    return hmac.compare_digest(received, expected)


def _event_id(*parts: str) -> UUID:
    """Stable-first identity (DEC-0006): a GitHub redelivery, and later the
    reconcile worker observing the same state, resolve to the same `event_id`
    — `create_event`'s get-or-create then deduplicates instead of doubling."""
    return uuid.uuid5(uuid.NAMESPACE_URL, "studio-github:" + ":".join(parts))


def _parse_dt(value: object) -> datetime | None:
    """GitHub ships ISO-8601 strings (`run_started_at`, `updated_at`) where
    the DB columns need real datetimes — unparseable or missing stays null
    rather than failing the whole delivery."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def _emit(
    session: AsyncSession,
    integration: GitHubIntegrationModel,
    event_id: UUID,
    event_type: EventType,
    task_id: UUID | None,
    payload: dict[str, object],
) -> None:
    await events_service.create_event(
        session,
        EventCreate(
            event_id=event_id,
            event_type=event_type,
            project_id=integration.project_id,
            task_id=task_id,
            machine_id=None,
            actor_type="system",
            actor_id=integration.id,
            client_timestamp=datetime.now(UTC),
            payload=payload,
        ),
    )


_STATUS_RANK = {"queued": 0, "in_progress": 1, "succeeded": 2, "failed": 2}


async def upsert_build(
    session: AsyncSession,
    integration: GitHubIntegrationModel | None,
    project_id: UUID,
    run: dict[str, Any],
) -> BuildModel:
    """Atomic upsert on `(project_id, workflow_run_id)` — a webhook
    redelivery and the reconcile worker converge on the same row (DEC-0059).
    Status only ever moves forward (`queued` -> `in_progress` ->
    `succeeded`/`failed`, per `BuildStatus`): a stale out-of-order delivery
    updates the other columns but never regresses `status` — enforced in the
    same statement (`ON CONFLICT DO UPDATE ... WHERE`), so no read-then-write
    race can undo a newer state."""
    values: dict[str, Any] = {
        "project_id": project_id,
        "task_id": run.get("task_id"),
        "github_integration_id": integration.id if integration is not None else None,
        "workflow_run_id": run["workflow_run_id"],
        "workflow_name": run["workflow_name"],
        "run_number": run["run_number"],
        "branch": run["branch"],
        "commit_sha": run["commit_sha"],
        "pr_number": run.get("pr_number"),
        "status": run["status"],
        "conclusion": run.get("conclusion"),
        "html_url": run["html_url"],
        "actor_login": run["actor_login"],
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
    }
    stored_rank = case(_STATUS_RANK, value=BuildModel.status, else_=0)
    new_rank = _STATUS_RANK[run["status"]]
    set_values: dict[str, Any] = {
        key: value for key, value in values.items() if key != "project_id"
    }
    set_values["updated_at"] = datetime.now(UTC)
    stmt = (
        pg_insert(BuildModel)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_builds_project_workflow_run",
            set_=set_values,
            where=stored_rank <= new_rank,
        )
        .returning(BuildModel.id)
    )
    result = await session.execute(stmt)
    build_id = result.scalar_one_or_none()
    await session.commit()
    build: BuildModel
    if build_id is None:
        # A staler state lost the `WHERE` above — load the winning row.
        existing = await session.execute(
            select(BuildModel).where(
                BuildModel.project_id == project_id,
                BuildModel.workflow_run_id == run["workflow_run_id"],
            )
        )
        build = existing.scalar_one()
    else:
        fetched = await session.get(BuildModel, build_id)
        assert fetched is not None
        build = fetched
    await session.refresh(build)
    return build


def _build_event_type(status: str, conclusion: str | None) -> EventType | None:
    if status == "completed":
        if conclusion == "success":
            return EventType.BUILD_SUCCEEDED
        if conclusion in ("failure", "timed_out", "cancelled"):
            return EventType.BUILD_FAILED
        return None
    if status in ("queued", "waiting", "requested", "pending", "in_progress"):
        return EventType.BUILD_STARTED
    return None


async def _ingest_workflow_run(
    session: AsyncSession, integration: GitHubIntegrationModel, payload: dict[str, Any]
) -> dict[str, object]:
    run = payload.get("workflow_run") or {}
    status_value = str(run.get("status") or "")
    conclusion = run.get("conclusion")
    conclusion_str = conclusion if isinstance(conclusion, str) else None
    event_type = _build_event_type(status_value, conclusion_str)
    try:
        run_id = int(run["id"])
    except (KeyError, TypeError, ValueError):
        return {"status": "ignored_malformed", "reason": "workflow_run.id missing"}
    pr_number: int | None = None
    prs = run.get("pull_requests") or []
    if prs and isinstance(prs[0], dict) and isinstance(prs[0].get("number"), int):
        pr_number = prs[0]["number"]
    build = await upsert_build(
        session,
        integration,
        integration.project_id,
        {
            "workflow_run_id": run_id,
            "workflow_name": str(run.get("name") or "unknown"),
            "run_number": int(run.get("run_number") or 0),
            "branch": str(run.get("head_branch") or ""),
            "commit_sha": str(run.get("head_sha") or ""),
            "pr_number": pr_number,
            "status": (
                BuildStatus.QUEUED.value
                if status_value in ("queued", "waiting", "requested", "pending")
                else BuildStatus.IN_PROGRESS.value
                if status_value == "in_progress"
                else BuildStatus.SUCCEEDED.value
                if event_type == EventType.BUILD_SUCCEEDED
                else BuildStatus.FAILED.value
                if event_type == EventType.BUILD_FAILED
                else BuildStatus.IN_PROGRESS.value
            ),
            "conclusion": conclusion if isinstance(conclusion, str) else None,
            "html_url": str(run.get("html_url") or ""),
            "actor_login": str((run.get("actor") or {}).get("login") or "unknown"),
            "started_at": _parse_dt(run.get("run_started_at")),
            "completed_at": _parse_dt(run.get("updated_at")),
        },
    )
    if event_type is not None:
        await _emit(
            session,
            integration,
            _event_id(str(integration.project_id), f"run-{run_id}", event_type.value),
            event_type,
            build.task_id,
            {
                "source": "github_webhook",
                "build_id": str(build.id),
                "workflow_run_id": run_id,
                "workflow_name": build.workflow_name,
                "branch": build.branch,
                "commit_sha": build.commit_sha,
                "pr_number": pr_number,
                "conclusion": conclusion,
                "html_url": build.html_url,
            },
        )
    return {"status": "accepted", "build_id": str(build.id)}


async def _ingest_push(
    session: AsyncSession,
    integration: GitHubIntegrationModel,
    delivery: str,
    payload: dict[str, Any],
) -> dict[str, object]:
    ref = str(payload.get("ref") or "")
    branch = ref.removeprefix("refs/heads/")
    deleted = bool(payload.get("deleted"))
    head = payload.get("head_commit") or {}
    commit_sha = str(head.get("id") or payload.get("after") or "")
    key = commit_sha or delivery
    await _emit(
        session,
        integration,
        _event_id(str(integration.project_id), f"push-{key}", "git.branch.changed"),
        EventType.GIT_BRANCH_CHANGED,
        None,
        {"source": "github_webhook", "branch": branch, "deleted": deleted},
    )
    if not deleted and commit_sha:
        await _emit(
            session,
            integration,
            _event_id(str(integration.project_id), f"push-{key}", "git.commit"),
            EventType.GIT_COMMIT,
            None,
            {
                "source": "github_webhook",
                "branch": branch,
                "commit_sha": commit_sha,
                "message": str(head.get("message") or ""),
                "author": str((head.get("author") or {}).get("username") or ""),
            },
        )
    return {"status": "accepted"}


async def _ingest_pull_request(
    session: AsyncSession, integration: GitHubIntegrationModel, payload: dict[str, Any]
) -> dict[str, object]:
    action = str(payload.get("action") or "")
    pr = payload.get("pull_request") or {}
    try:
        pr_number = int(pr["number"])
    except (KeyError, TypeError, ValueError):
        return {"status": "ignored_malformed", "reason": "pull_request.number missing"}
    if action == "opened":
        event_type = EventType.GIT_PR_OPENED
    elif action == "closed" and bool(pr.get("merged")):
        event_type = EventType.GIT_PR_MERGED
    else:
        return {"status": "ignored_action", "action": action}
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    await _emit(
        session,
        integration,
        _event_id(str(integration.project_id), f"pr-{pr_number}", event_type.value),
        event_type,
        None,
        {
            "source": "github_webhook",
            "pr_number": pr_number,
            "title": str(pr.get("title") or ""),
            "head_branch": str(head.get("ref") or ""),
            "base_branch": str(base.get("ref") or ""),
            "head_sha": str(head.get("sha") or ""),
            "merge_commit_sha": str(pr.get("merge_commit_sha") or ""),
            "author": str((pr.get("user") or {}).get("login") or ""),
            "html_url": str(pr.get("html_url") or ""),
        },
    )
    return {"status": "accepted", "pr_number": pr_number}


async def ingest_webhook(
    session: AsyncSession,
    integration: GitHubIntegrationModel,
    github_event: str,
    delivery: str,
    payload: dict[str, Any],
) -> dict[str, object]:
    """Maps one verified GitHub delivery to server-side events/builds
    (DEC-0059 §5). Unknown event names are a silent 202 at the router —
    here they surface as `ignored_unknown_event`, never an exception."""
    if not integration.enabled:
        return {"status": "ignored_disabled"}
    if github_event == "push":
        return await _ingest_push(session, integration, delivery, payload)
    if github_event == "pull_request":
        return await _ingest_pull_request(session, integration, payload)
    if github_event == "workflow_run":
        return await _ingest_workflow_run(session, integration, payload)
    return {"status": "ignored_unknown_event", "github_event": github_event}


async def get_integration_by_repo(
    session: AsyncSession, repo_full_name: str
) -> GitHubIntegrationModel | None:
    result = await session.execute(
        select(GitHubIntegrationModel).where(
            GitHubIntegrationModel.repo_full_name == repo_full_name
        )
    )
    return result.scalar_one_or_none()


async def get_integration_by_project(
    session: AsyncSession, project_id: UUID
) -> GitHubIntegrationModel | None:
    result = await session.execute(
        select(GitHubIntegrationModel).where(GitHubIntegrationModel.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def create_integration(
    session: AsyncSession, principal: Principal, integration_in: GitHubIntegrationCreate
) -> GitHubIntegrationModel:
    ensure_can_provision(principal, "github_integration")
    project = await session.get(ProjectModel, integration_in.project_id)
    if project is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "project_not_found", "message": "project not found"},
        )
    if await get_integration_by_project(session, integration_in.project_id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error_code": "integration_exists",
                "message": "project already has a GitHub integration",
            },
        )
    integration = GitHubIntegrationModel(
        project_id=integration_in.project_id,
        repo_full_name=integration_in.repo_full_name,
        default_branch=integration_in.default_branch or "main",
        enabled=integration_in.enabled if integration_in.enabled is not None else True,
        created_by_user_id=principal.user.id,
    )
    session.add(integration)
    await session.commit()
    await session.refresh(integration)
    return integration


async def update_integration(
    session: AsyncSession,
    principal: Principal,
    integration: GitHubIntegrationModel,
    integration_in: GitHubIntegrationUpdate,
) -> GitHubIntegrationModel:
    ensure_can_provision(principal, "github_integration")
    if integration_in.repo_full_name is not None:
        integration.repo_full_name = integration_in.repo_full_name
    if integration_in.default_branch is not None:
        integration.default_branch = integration_in.default_branch
    if integration_in.enabled is not None:
        integration.enabled = integration_in.enabled
    await session.commit()
    await session.refresh(integration)
    return integration


async def list_builds(
    session: AsyncSession,
    project_id: UUID | None = None,
    status_value: str | None = None,
    limit: int = 100,
) -> list[BuildModel]:
    stmt = select(BuildModel).order_by(BuildModel.created_at.desc()).limit(limit)
    if project_id is not None:
        stmt = stmt.where(BuildModel.project_id == project_id)
    if status_value is not None:
        stmt = stmt.where(BuildModel.status == status_value)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_build(session: AsyncSession, build_id: UUID) -> BuildModel | None:
    return await session.get(BuildModel, build_id)


async def fetch_workflow_runs(
    repo_full_name: str, token: str, limit: int, client: httpx.AsyncClient
) -> list[dict[str, Any]]:
    """Bounded GitHub API read (reconcile worker only, never the Bloc B —
    DEC-0059 §2). Minimal `actions:read` scope; honors `Retry-After` once."""
    response = await client.get(
        f"{_GITHUB_API}/repos/{repo_full_name}/actions/runs",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        params={"per_page": max(1, min(limit, 100))},
        timeout=30.0,
    )
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            import asyncio

            await asyncio.sleep(min(int(retry_after), 60))
            response = await client.get(
                f"{_GITHUB_API}/repos/{repo_full_name}/actions/runs",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                params={"per_page": max(1, min(limit, 100))},
                timeout=30.0,
            )
    response.raise_for_status()
    return list(response.json().get("workflow_runs", []))


def _normalize_api_run(run: dict[str, Any]) -> dict[str, Any] | None:
    try:
        run_id = int(run["id"])
    except (KeyError, TypeError, ValueError):
        return None
    status_value = str(run.get("status") or "")
    conclusion = run.get("conclusion")
    conclusion_str = conclusion if isinstance(conclusion, str) else None
    event_type = _build_event_type(status_value, conclusion_str)
    pr_number: int | None = None
    prs = run.get("pull_requests") or []
    if prs and isinstance(prs[0], dict) and isinstance(prs[0].get("number"), int):
        pr_number = prs[0]["number"]
    return {
        "workflow_run_id": run_id,
        "workflow_name": str(run.get("name") or "unknown"),
        "run_number": int(run.get("run_number") or 0),
        "branch": str(run.get("head_branch") or ""),
        "commit_sha": str(run.get("head_sha") or ""),
        "pr_number": pr_number,
        "status": (
            BuildStatus.QUEUED.value
            if status_value in ("queued", "waiting", "requested", "pending")
            else BuildStatus.IN_PROGRESS.value
            if status_value == "in_progress"
            else BuildStatus.SUCCEEDED.value
            if event_type == EventType.BUILD_SUCCEEDED
            else BuildStatus.FAILED.value
            if event_type == EventType.BUILD_FAILED
            else BuildStatus.IN_PROGRESS.value
        ),
        "conclusion": conclusion if isinstance(conclusion, str) else None,
        "html_url": str(run.get("html_url") or ""),
        "actor_login": str((run.get("actor") or {}).get("login") or "unknown"),
        "started_at": _parse_dt(run.get("run_started_at")),
        "completed_at": _parse_dt(run.get("updated_at")),
        "event_type": event_type,
    }


async def reconcile_builds(
    session: AsyncSession,
    fetch: Callable[[str, int], Awaitable[list[dict[str, Any]]]],
    per_integration_limit: int,
) -> list[BuildModel]:
    """Catches up on deliveries the webhook missed (DEC-0059 §2, same model
    as DEC-0020/DEC-0037: scheduled CLI job, no in-process scheduler).
    Idempotent: the `(project_id, workflow_run_id)` upsert and the
    run-keyed event ids make a re-run converge without duplicates. `fetch`
    is injected so tests run this against a fake without network."""
    result = await session.execute(
        select(GitHubIntegrationModel).where(GitHubIntegrationModel.enabled.is_(True))
    )
    reconciled: list[BuildModel] = []
    for integration in result.scalars().all():
        runs = await fetch(integration.repo_full_name, per_integration_limit)
        for raw in runs:
            normalized = _normalize_api_run(raw)
            if normalized is None:
                continue
            event_type = normalized.pop("event_type")
            build = await upsert_build(session, integration, integration.project_id, normalized)
            reconciled.append(build)
            if event_type is not None:
                await _emit(
                    session,
                    integration,
                    _event_id(
                        str(integration.project_id),
                        f"run-{normalized['workflow_run_id']}",
                        event_type.value,
                    ),
                    event_type,
                    build.task_id,
                    {
                        "source": "github_reconcile",
                        "build_id": str(build.id),
                        "workflow_run_id": normalized["workflow_run_id"],
                        "workflow_name": build.workflow_name,
                        "branch": build.branch,
                        "commit_sha": build.commit_sha,
                        "pr_number": normalized["pr_number"],
                        "conclusion": normalized["conclusion"],
                        "html_url": build.html_url,
                    },
                )
    return reconciled
