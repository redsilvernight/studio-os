from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.build import GitHubIntegrationModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import github as github_service
from studio_mcp.tools.builds import studio_get_builds, studio_request_producer_job

from tests.mcp.conftest import FakeContext


async def _seed_build(
    db_session: AsyncSession, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    integration = GitHubIntegrationModel(
        project_id=project.id,
        repo_full_name="studio-org/studio-game",
        default_branch="main",
        enabled=True,
        created_by_user_id=machine_model.owner_user_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(integration)
    await db_session.flush()
    await github_service.upsert_build(
        db_session,
        integration,
        project.id,
        {
            "workflow_run_id": 4001,
            "workflow_name": "CI",
            "run_number": 1,
            "branch": "main",
            "commit_sha": "sha1",
            "pr_number": None,
            "status": "failed",
            "conclusion": "failure",
            "html_url": "https://example.test/runs/4001",
            "actor_login": "dev-one",
            "started_at": None,
            "completed_at": None,
        },
    )


async def test_get_builds_empty(auth_ctx: FakeContext, project: ProjectModel) -> None:
    result = await studio_get_builds(auth_ctx, project_id=str(project.id))
    assert result["builds"] == []


async def test_get_builds_lists_and_rejects_bad_status(
    auth_ctx: FakeContext,
    project: ProjectModel,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    await _seed_build(db_session, project, machine)
    result = await studio_get_builds(auth_ctx, project_id=str(project.id))
    assert len(result["builds"]) == 1
    assert result["builds"][0]["status"] == "failed"

    filtered = await studio_get_builds(auth_ctx, project_id=str(project.id), status="succeeded")
    assert filtered["builds"] == []

    invalid = await studio_get_builds(auth_ctx, project_id=str(project.id), status="exploded")
    assert invalid["error_code"] == "invalid_status"

    bad_project = await studio_get_builds(auth_ctx, project_id="not-a-uuid")
    assert bad_project["error_code"] == "invalid_argument"


async def test_request_producer_job_and_replay(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_request_producer_job(
        str(project.id), "priority_analysis", auth_ctx, idempotency_key="mcp-producer-1"
    )
    assert created["status"] == "completed"
    assert created["result"]["ranking"] == []

    replayed = await studio_request_producer_job(
        str(project.id), "priority_analysis", auth_ctx, idempotency_key="mcp-producer-1"
    )
    assert replayed["id"] == created["id"]


async def test_request_producer_job_rejects_bad_kind_and_readonly(
    auth_ctx: FakeContext,
    readonly_auth_ctx: FakeContext,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
) -> None:
    assert machine is not None
    invalid = await studio_request_producer_job(str(project.id), "telepathy", auth_ctx)
    assert invalid["error_code"] == "invalid_kind"

    readonly = await studio_request_producer_job(
        str(project.id), "priority_analysis", readonly_auth_ctx
    )
    assert readonly["error_code"] == "forbidden"

    missing_task = await studio_request_producer_job(str(project.id), "decomposition", auth_ctx)
    assert missing_task["error_code"] == "task_required"
