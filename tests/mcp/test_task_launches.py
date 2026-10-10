from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.task_launch import TaskLaunchModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_mcp.tools.task_launches import (
    studio_get_task_launch,
    studio_list_task_launches,
    studio_pull_pending_launches,
)

from tests.mcp.conftest import FakeContext


async def _row(
    db_session: AsyncSession,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    status: str = "requested",
) -> TaskLaunchModel:
    machine_model, _ = machine
    task = TaskModel(project_id=project.id, title="t")
    db_session.add(task)
    await db_session.flush()
    user_id = machine_model.owner_user_id
    row = TaskLaunchModel(
        project_id=project.id,
        task_id=task.id,
        machine_id=machine_model.id,
        requested_by_user_id=user_id,
        harness_id="claude-code",
        status=status,
        reason_code="none",
        expires_at=datetime.now(UTC) + timedelta(seconds=900),
    )
    db_session.add(row)
    await db_session.flush()
    await db_session.refresh(row)
    return row


async def test_get_and_list_task_launch(
    auth_ctx: FakeContext,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    row = await _row(db_session, project, machine)
    fetched = await studio_get_task_launch(str(row.id), auth_ctx)
    assert fetched["id"] == str(row.id)
    assert fetched["status"] == "requested"
    assert fetched["version"] == 1
    listed = await studio_list_task_launches(str(project.id), auth_ctx)
    assert [item["id"] for item in listed["launches"]] == [str(row.id)]


async def test_list_task_launches_carries_the_protocol_proof(
    auth_ctx: FakeContext,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    row = await _row(db_session, project, machine)
    work_session = WorkSessionModel(
        task_id=row.task_id, machine_id=row.machine_id, started_at=datetime.now(UTC)
    )
    db_session.add(work_session)
    await db_session.flush()
    await db_session.refresh(work_session)
    work_session.ended_at = datetime.now(UTC)
    row.session_id = work_session.id
    await db_session.commit()
    listed = await studio_list_task_launches(str(project.id), auth_ctx)
    assert listed["launches"][0]["protocol"] == {
        "status": "handed_off",
        "session_id": str(work_session.id),
        "task_status": "created",
    }
    fetched = await studio_get_task_launch(str(row.id), auth_ctx)
    assert "protocol" not in fetched


async def test_get_task_launch_rejects_unknown_id(auth_ctx: FakeContext) -> None:
    result = await studio_get_task_launch("00000000-0000-0000-0000-000000000000", auth_ctx)
    assert result["error_code"] == "not_found"


@pytest.mark.isolation
async def test_pull_pending_returns_own_launches_only(
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    project: ProjectModel,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    mine = await _row(db_session, project, machine)
    await _row(db_session, project, other_machine)
    result = await studio_pull_pending_launches(auth_ctx)
    assert [item["id"] for item in result["launches"]] == [str(mine.id)]
    foreign = await studio_get_task_launch(str(mine.id), other_auth_ctx)
    assert foreign["error_code"] == "forbidden"
