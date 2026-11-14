from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_mcp.tools.tasks import (
    studio_create_task,
    studio_get_active_tasks,
    studio_get_task,
    studio_update_task,
)

from tests.mcp.conftest import FakeContext


async def test_create_and_get_task(auth_ctx: FakeContext, project: ProjectModel) -> None:
    created = await studio_create_task(str(project.id), "Design the level", auth_ctx)
    assert created["status"] == "created"

    fetched = await studio_get_task(created["id"], auth_ctx)
    assert fetched["id"] == created["id"]
    assert fetched["title"] == "Design the level"


async def test_get_task_rejects_unknown_id(auth_ctx: FakeContext) -> None:
    result = await studio_get_task("00000000-0000-0000-0000-000000000000", auth_ctx)
    assert result["error_code"] == "not_found"


async def test_default_active_tasks_are_bounded_with_exact_remaining_count(
    db_session: AsyncSession, project: ProjectModel, auth_ctx: FakeContext
) -> None:
    db_session.add_all(
        [
            TaskModel(project_id=project.id, title=f"Task {index:03d}", status="created")
            for index in range(101)
        ]
    )
    await db_session.flush()
    result = await studio_get_active_tasks(str(project.id), auth_ctx)
    assert result["returned"] == 100
    assert result["additional_available"] == 1
    assert result["tasks"][0]["title"] == "Task 000"
    assert result["tasks"][-1]["title"] == "Task 099"


async def test_get_active_tasks_lists_created_task(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_task(str(project.id), "Fix the bug", auth_ctx)
    result = await studio_get_active_tasks(str(project.id), auth_ctx)
    assert any(t["id"] == created["id"] for t in result["tasks"])


async def test_get_active_tasks_filters_limits_and_selects_fields(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    await studio_create_task(str(project.id), "Beta task", auth_ctx)
    alpha = await studio_create_task(str(project.id), "Alpha task", auth_ctx)
    await studio_create_task(str(project.id), "Alpine task", auth_ctx)

    result = await studio_get_active_tasks(
        str(project.id),
        auth_ctx,
        title_prefix="al",
        limit=1,
        fields=["title", "status"],
    )

    assert result == {
        "tasks": [{"id": alpha["id"], "title": "Alpha task", "status": "created"}],
        "returned": 1,
        "additional_available": 1,
    }


async def test_get_active_tasks_rejects_invalid_bounds_and_fields(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    bad_limit = await studio_get_active_tasks(str(project.id), auth_ctx, limit=0)
    assert bad_limit["error_code"] == "invalid_argument"

    bad_fields = await studio_get_active_tasks(
        str(project.id), auth_ctx, fields=["title", "secret"]
    )
    assert bad_fields["error_code"] == "invalid_argument"


async def test_update_task_rejects_stale_version(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_task(str(project.id), "Rename me", auth_ctx)
    result = await studio_update_task(
        created["id"], expected_version=999, ctx=auth_ctx, title="New title"
    )
    assert result["error_code"] == "version_conflict"


async def test_update_task_applies_new_title(auth_ctx: FakeContext, project: ProjectModel) -> None:
    created = await studio_create_task(str(project.id), "Rename me", auth_ctx)
    result = await studio_update_task(
        created["id"],
        expected_version=created["version"],
        ctx=auth_ctx,
        title="New title",
    )
    assert result["title"] == "New title"


async def test_update_task_can_return_compact_response(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_task(str(project.id), "Compact update", auth_ctx)
    result = await studio_update_task(
        created["id"],
        expected_version=created["version"],
        ctx=auth_ctx,
        status="blocked",
        verbose=False,
    )
    assert set(result) == {"id", "status", "version", "claimed_by_machine_id"}


async def test_create_task_idempotency_key_replay_returns_same_task(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    """DEC-0027: an MCP writer's idempotency_key must behave like the HTTP
    Idempotency-Key header — a replay with the same arguments returns the
    original task, never a second one."""
    first = await studio_create_task(
        str(project.id), "Retried call", auth_ctx, idempotency_key="mcp-task-key-1"
    )
    second = await studio_create_task(
        str(project.id), "Retried call", auth_ctx, idempotency_key="mcp-task-key-1"
    )
    assert second["id"] == first["id"]

    listing = await studio_get_active_tasks(str(project.id), auth_ctx)
    matches = [t for t in listing["tasks"] if t["title"] == "Retried call"]
    assert len(matches) == 1


async def test_create_task_idempotency_key_payload_mismatch_is_rejected(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    await studio_create_task(
        str(project.id), "Original title", auth_ctx, idempotency_key="mcp-task-key-2"
    )
    result = await studio_create_task(
        str(project.id), "Different title", auth_ctx, idempotency_key="mcp-task-key-2"
    )
    assert result["error_code"] == "idempotency_key_payload_mismatch"
