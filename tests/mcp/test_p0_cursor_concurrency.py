from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.user import UserModel
from studio_api.db.models.work_session import WorkSessionModel
from studio_api.services import sessions


@pytest_asyncio.fixture
async def cursor_rows(engine: AsyncEngine) -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        user = UserModel(
            display_name="P0 cursor", email=f"{uuid.uuid4()}@example.test", role="admin"
        )
        project = ProjectModel(slug=f"p0-cursor-{uuid.uuid4().hex}", name="P0 cursor")
        setup.add_all([user, project])
        await setup.flush()
        machine = MachineModel(
            owner_user_id=user.id, display_name="P0 cursor", credential_hash="not-a-credential"
        )
        task = TaskModel(project_id=project.id, title="P0 cursor")
        setup.add_all([machine, task])
        await setup.flush()
        work = WorkSessionModel(
            task_id=task.id, machine_id=machine.id, started_at=datetime.now(UTC)
        )
        setup.add(work)
        await setup.commit()
        ids = work.id, task.id
        machine_id, project_id, user_id = machine.id, project.id, user.id
    try:
        yield ids
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(WorkSessionModel).where(WorkSessionModel.id == ids[0]))
            await cleanup.execute(delete(TaskModel).where(TaskModel.id == ids[1]))
            await cleanup.execute(delete(MachineModel).where(MachineModel.id == machine_id))
            await cleanup.execute(delete(ProjectModel).where(ProjectModel.id == project_id))
            await cleanup.execute(delete(UserModel).where(UserModel.id == user_id))
            await cleanup.commit()


@pytest.mark.parametrize("first,second", [(20, 10), (10, 20)])
@pytest.mark.parametrize("initial", [None, 5, 30])
@pytest.mark.parametrize("kind", ["sync", "handoff"])
async def test_ack_with_stale_reads_is_monotone(
    engine: AsyncEngine,
    cursor_rows: tuple[uuid.UUID, uuid.UUID],
    first: int,
    second: int,
    initial: int | None,
    kind: str,
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    work_id, task_id = cursor_rows
    model = WorkSessionModel if kind == "sync" else TaskModel
    row_id = work_id if kind == "sync" else task_id
    field = "sync_cursor_seq" if kind == "sync" else "handoff_cursor_seq"
    ack_cursor = sessions.ack_sync_cursor if kind == "sync" else sessions.ack_handoff_cursor
    async with factory() as setup:
        row = await setup.get(model, row_id)
        assert row is not None
        setattr(row, field, initial)
        await setup.commit()
    both_read = asyncio.Barrier(2)
    first_committed = asyncio.Event()

    async def ack(seq: int, is_first: bool) -> None:
        async with factory() as transaction:
            stale = await transaction.get(model, row_id)
            assert stale is not None and getattr(stale, field) == initial
            await both_read.wait()
            if not is_first:
                await first_committed.wait()
            try:
                result = await ack_cursor(transaction, row_id, seq)
                assert result is not None
                assert getattr(result, field) >= seq
            finally:
                if is_first:
                    first_committed.set()

    await asyncio.wait_for(asyncio.gather(ack(first, True), ack(second, False)), timeout=10)
    async with factory() as check:
        final = await check.scalar(select(getattr(model, field)).where(model.id == row_id))
        assert final == max(initial or 0, first, second)


@pytest.mark.parametrize("kind", ["sync", "handoff"])
async def test_ack_interrupted_before_commit_rolls_back_and_retries(
    engine: AsyncEngine,
    cursor_rows: tuple[uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    model = WorkSessionModel if kind == "sync" else TaskModel
    row_id = cursor_rows[0] if kind == "sync" else cursor_rows[1]
    field = "sync_cursor_seq" if kind == "sync" else "handoff_cursor_seq"
    ack_cursor = sessions.ack_sync_cursor if kind == "sync" else sessions.ack_handoff_cursor

    async def interrupted() -> None:
        raise RuntimeError("interrupted before cursor commit")

    async with factory() as transaction:
        with monkeypatch.context() as patch:
            patch.setattr(transaction, "commit", interrupted)
            with pytest.raises(RuntimeError, match="interrupted before cursor commit"):
                await ack_cursor(transaction, row_id, 20)
        await transaction.rollback()
    async with factory() as check:
        assert await check.scalar(select(getattr(model, field)).where(model.id == row_id)) is None
        advanced = await ack_cursor(check, row_id, 20)
        assert advanced is not None and getattr(advanced, field) == 20
        replay = await ack_cursor(check, row_id, 10)
        assert replay is not None and getattr(replay, field) == 20


async def test_unknown_cursor_targets_remain_missing(engine: AsyncEngine) -> None:
    async with AsyncSession(engine) as session:
        assert await sessions.ack_sync_cursor(session, uuid.uuid4(), 20) is None
        assert await sessions.ack_handoff_cursor(session, uuid.uuid4(), 20) is None
