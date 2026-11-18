"""Infrastructure cost collector (phase M, migration 0045): measures sizes and
counts only, per-project storage matches the transfer quota definition, the
retention purge bounds the table, and no content column exists."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models import InfraMeasurementModel, ProjectModel, TransferModel
from studio_api.services import infra_measurements, transfers
from studio_api.services import provisioning as provisioning_service
from studio_api.settings import Settings

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    return Settings(infra_measure_retention_days=90, **overrides)  # type: ignore[arg-type]


async def _transfer(
    db_session: AsyncSession, project: ProjectModel, size: int, status: str
) -> None:
    sender = await provisioning_service.create_user(
        db_session, "Sender", f"{uuid.uuid4()}@example.test", "developer"
    )
    db_session.add(
        TransferModel(
            transfer_code=f"TRF-{uuid.uuid4().hex[:8].upper()}",
            sender_user_id=sender.id,
            project_id=project.id,
            category="build",
            object_key=f"t/{uuid.uuid4().hex}",
            size_bytes=size,
            status=status,
            filename="f.bin",
            content_type="application/octet-stream",
            created_at=NOW,
        )
    )
    await db_session.flush()


async def test_collect_records_table_sizes_and_connections(db_session: AsyncSession) -> None:
    rows = await infra_measurements.collect(db_session, _settings(), now=NOW)
    await db_session.flush()
    subjects = {r.subject for r in rows if r.metric == "pg_table_bytes"}
    assert subjects == set(infra_measurements.MEASURED_TABLES)
    assert all(r.value >= 0 and r.measured_at == NOW for r in rows)
    assert any(r.metric == "sse_connections" and r.value == 0 for r in rows)


async def test_project_storage_matches_quota_definition(
    db_session: AsyncSession, project: ProjectModel
) -> None:
    await _transfer(db_session, project, 1_000, "completed")
    await _transfer(db_session, project, 500, "created")
    await _transfer(db_session, project, 9_999, "deleted")
    rows = await infra_measurements.collect(db_session, _settings(), now=NOW)
    stored = [r for r in rows if r.metric == "storage_bytes" and r.project_id == project.id]
    assert [r.value for r in stored] == [1_500]
    assert stored[0].value == await transfers.compute_consumption(db_session, project.id)


async def test_purge_removes_only_rows_past_retention(db_session: AsyncSession) -> None:
    old = InfraMeasurementModel(
        metric="sse_connections", value=1, measured_at=NOW - timedelta(days=91)
    )
    recent = InfraMeasurementModel(
        metric="sse_connections", value=2, measured_at=NOW - timedelta(days=89)
    )
    db_session.add_all([old, recent])
    await db_session.flush()
    removed = await infra_measurements.purge(db_session, _settings(), now=NOW)
    remaining = (await db_session.execute(select(InfraMeasurementModel.value))).scalars().all()
    assert removed == 1 and 2 in remaining and 1 not in remaining


def test_no_content_column() -> None:
    columns = {c.name for c in InfraMeasurementModel.__table__.columns}
    assert columns == {"id", "metric", "subject", "project_id", "value", "measured_at"}
