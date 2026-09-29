from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import provisioning as provisioning_service
from studio_mcp.tools.tasks import (
    studio_claim_task,
    studio_create_task,
    studio_get_active_tasks,
    studio_get_task,
    studio_release_task,
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


async def test_get_active_tasks_lists_created_task(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_task(str(project.id), "Fix the bug", auth_ctx)
    result = await studio_get_active_tasks(str(project.id), auth_ctx)
    assert any(t["id"] == created["id"] for t in result["tasks"])


async def test_claim_then_release_task(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    created = await studio_create_task(str(project.id), "Ship it", auth_ctx)

    claimed = await studio_claim_task(created["id"], auth_ctx, verbose=False)
    assert set(claimed) == {"id", "status", "version", "claimed_by_machine_id"}
    assert claimed["status"] == "in_progress"
    assert claimed["claimed_by_machine_id"] == str(machine_model.id)

    released = await studio_release_task(created["id"], auth_ctx, verbose=False)
    assert set(released) == {"id", "status", "version", "claimed_by_machine_id"}
    assert released["claimed_by_machine_id"] is None

    detailed = await studio_claim_task(created["id"], auth_ctx)
    assert detailed["title"] == "Ship it"
    assert "description" in detailed


async def test_release_task_rejects_stale_expected_version(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_task(str(project.id), "Versioned release", auth_ctx)
    claimed = await studio_claim_task(created["id"], auth_ctx)

    stale = await studio_release_task(
        created["id"], auth_ctx, expected_version=claimed["version"] - 1
    )
    assert stale["error_code"] == "version_conflict"

    released = await studio_release_task(
        created["id"], auth_ctx, expected_version=claimed["version"]
    )
    assert released["claimed_by_machine_id"] is None


async def test_claim_task_conflicts_when_already_claimed(
    auth_ctx: FakeContext, project: ProjectModel, db_session: AsyncSession
) -> None:
    created = await studio_create_task(str(project.id), "Contested task", auth_ctx)
    await studio_claim_task(created["id"], auth_ctx)

    other_user = await provisioning_service.create_user(
        db_session, "Other Dev", "other-dev@example.test", "developer"
    )
    _, other_token = await provisioning_service.create_machine(
        db_session, other_user.id, "other-machine"
    )
    other_ctx = FakeContext(headers={"authorization": f"Bearer {other_token}"})
    result = await studio_claim_task(created["id"], other_ctx)
    assert result["error_code"] == "already_claimed"


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


async def test_claim_task_idempotency_key_replay_returns_original(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    """An MCP claim replay with the same key+arguments returns the original
    claim instead of re-running it (DEC-0027)."""
    created = await studio_create_task(str(project.id), "Replayable claim", auth_ctx)
    first = await studio_claim_task(created["id"], auth_ctx, idempotency_key="mcp-claim-1")
    second = await studio_claim_task(created["id"], auth_ctx, idempotency_key="mcp-claim-1")
    assert second["id"] == first["id"]
    assert second["version"] == first["version"]


async def test_claim_task_idempotency_distinguishes_compact_response(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_task(str(project.id), "Response shape", auth_ctx)
    await studio_claim_task(created["id"], auth_ctx, idempotency_key="mcp-claim-shape")
    mismatch = await studio_claim_task(
        created["id"],
        auth_ctx,
        idempotency_key="mcp-claim-shape",
        verbose=False,
    )
    assert mismatch["error_code"] == "idempotency_key_payload_mismatch"


async def test_claim_task_replay_without_key_is_a_noop(
    auth_ctx: FakeContext, project: ProjectModel, machine: tuple[MachineModel, str]
) -> None:
    """Same machine, same agent: a second claim changes nothing (no version
    bump), even without a key."""
    machine_model, _ = machine
    created = await studio_create_task(str(project.id), "No-op claim", auth_ctx)
    first = await studio_claim_task(created["id"], auth_ctx)
    second = await studio_claim_task(created["id"], auth_ctx)
    assert second["claimed_by_machine_id"] == str(machine_model.id)
    assert second["version"] == first["version"]
