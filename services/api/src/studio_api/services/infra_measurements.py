"""Infrastructure cost collector (phase M): sizes and counts, never content.

Each run appends one batch of `InfraMeasurementModel` rows. Per-project storage
uses the same definition as the transfer quota (`transfers.compute_consumption`:
non-deleted transfers), so the figure matches what a limit would be checked
against. Nothing here reads a title, a note body or a file name.
"""

from __future__ import annotations

import asyncio
import logging
import mmap
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.infra_measurement import InfraMeasurementModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.session import get_session_factory
from studio_api.services import event_stream
from studio_api.settings import Settings

logger = logging.getLogger(__name__)

# Fixed whitelist: the names are interpolated into `to_regclass`, never user input.
MEASURED_TABLES = (
    "events",
    "usage_ledger_entries",
    "vault_notes",
    "vault_note_versions",
    "transfers",
    "execution_snapshots",
    "ai_work_logs",
    "library_resource_versions",
)


def _process_rss_bytes() -> int | None:
    # shortcut: Linux only (/proc), the production host; None elsewhere. Improve
    # with a measured dependency if a non-Linux host ever needs it.
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            pages = int(handle.read().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return pages * mmap.PAGESIZE


def _directory_bytes(path: str) -> int | None:
    root = Path(path)
    if not root.is_dir():
        return None
    return sum(entry.stat().st_size for entry in root.rglob("*") if entry.is_file())


async def collect(
    session: AsyncSession, settings: Settings, *, now: datetime | None = None
) -> list[InfraMeasurementModel]:
    """Append one batch of measurements and return the rows (not committed)."""
    measured_at = now or datetime.now(UTC)
    rows: list[InfraMeasurementModel] = []

    def add(
        metric: str, value: int, *, subject: str = "", project_id: uuid.UUID | None = None
    ) -> None:
        rows.append(
            InfraMeasurementModel(
                metric=metric,
                subject=subject,
                project_id=project_id,
                value=value,
                measured_at=measured_at,
            )
        )

    for table in MEASURED_TABLES:
        size = (
            await session.execute(
                text("SELECT COALESCE(pg_total_relation_size(to_regclass(:name)), 0)"),
                {"name": table},
            )
        ).scalar_one()
        add("pg_table_bytes", int(size), subject=table)

    per_project = await session.execute(
        select(TransferModel.project_id, func.coalesce(func.sum(TransferModel.size_bytes), 0))
        .where(TransferModel.status != "deleted", TransferModel.project_id.is_not(None))
        .group_by(TransferModel.project_id)
    )
    for project_id, size in per_project.all():
        add("storage_bytes", int(size), project_id=project_id)

    add("sse_connections", event_stream.subscriber_count())
    rss = _process_rss_bytes()
    if rss is not None:
        add("process_rss_bytes", rss)
    if settings.infra_backup_dir:
        backup = await asyncio.to_thread(_directory_bytes, settings.infra_backup_dir)
        if backup is not None:
            add("backup_bytes", backup)

    session.add_all(rows)
    return rows


async def purge(session: AsyncSession, settings: Settings, *, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=settings.infra_measure_retention_days)
    result = await session.execute(
        delete(InfraMeasurementModel).where(InfraMeasurementModel.measured_at < cutoff)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def run_once(settings: Settings) -> int:
    async with get_session_factory()() as session:
        rows = await collect(session, settings)
        await purge(session, settings)
        await session.commit()
        return len(rows)


async def run_forever(settings: Settings) -> None:
    """Collector loop: a failed run is logged (class name only) and retried at
    the next interval; it never takes the API down."""
    interval = settings.infra_measure_interval_seconds
    while True:
        try:
            await run_once(settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the loop must survive any failure
            logger.warning("infra measurement run failed: %s", type(exc).__name__)
        await asyncio.sleep(interval)
