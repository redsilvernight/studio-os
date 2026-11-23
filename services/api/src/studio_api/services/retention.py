"""Announced retention purge of studio data (0054).

Retention is a two-step contract, never a silent deletion:

- `announce_due` compares, per studio and per kind, what is older than the
  duration declared by the studio's plan (`plan_limits`, key
  `<kind>_retention_days`). When something is due, it records one notice with
  the cutoff it computed and `purge_after = now + 7 days`. A `NULL` limit means
  unlimited: nothing is announced, nothing is ever purged. An open notice is
  not duplicated.
- `purge_announced` deletes only rows and objects older than the cutoff of an
  open notice whose `purge_after` elapsed, then closes the notice and writes a
  content-free `retention_purge_log` row (row and object counts only).

The timeline is a projection of the studio events (no separate store), so
`timeline` shares the events target. Transfers are the only kind carrying
objects: their object keys are deleted before their rows, and an unavailable
object storage leaves the notice open instead of orphaning objects.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.event import EventModel
from studio_api.db.models.execution_snapshot import ExecutionSnapshotModel
from studio_api.db.models.plan import PlanLimitModel, PlanModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.retention import (
    RetentionKind,
    RetentionPurgeLogModel,
    RetentionPurgeNoticeModel,
)
from studio_api.db.models.studio import StudioModel
from studio_api.db.models.studio_export import StudioExportModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.usage import UsageLedgerEntryModel
from studio_api.storage.provider import StorageProvider

logger = logging.getLogger(__name__)

PURGE_NOTICE_DAYS = 7
"""Grace window between the announcement and the first possible purge."""

LIMIT_KEYS: dict[RetentionKind, str] = {
    RetentionKind.EVENTS: "event_retention_days",
    RetentionKind.TIMELINE: "timeline_retention_days",
    RetentionKind.USAGE: "usage_retention_days",
    RetentionKind.TRANSFERS: "transfer_retention_days",
    RetentionKind.SNAPSHOTS: "snapshot_retention_days",
}

_EVENTS_KINDS = (RetentionKind.EVENTS, RetentionKind.TIMELINE)


@dataclass(frozen=True)
class RetentionPurgeOutcome:
    """What one executed purge removed, for the CLI log."""

    studio_id: uuid.UUID
    kind: RetentionKind
    rows_deleted: int
    objects_deleted: int
    purged_at: datetime


def _studio_projects(studio_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    return select(ProjectModel.id).where(ProjectModel.studio_id == studio_id)


def export_url(studio_id: uuid.UUID) -> str:
    """The owner-only export endpoint a member is pointed at by the notice."""
    return f"/api/v1/studios/{studio_id}/exports"


async def open_notices(
    session: AsyncSession, studio_id: uuid.UUID
) -> list[RetentionPurgeNoticeModel]:
    result = await session.execute(
        select(RetentionPurgeNoticeModel)
        .where(
            RetentionPurgeNoticeModel.studio_id == studio_id,
            RetentionPurgeNoticeModel.purged_at.is_(None),
        )
        .order_by(RetentionPurgeNoticeModel.purge_after, RetentionPurgeNoticeModel.kind)
    )
    return list(result.scalars())


async def _count_overdue(
    session: AsyncSession, studio_id: uuid.UUID, kind: RetentionKind, cutoff: datetime
) -> int:
    if kind in _EVENTS_KINDS:
        count = await session.scalar(
            select(func.count())
            .select_from(EventModel)
            .where(
                EventModel.project_id.in_(_studio_projects(studio_id)),
                EventModel.server_timestamp < cutoff,
            )
        )
    elif kind is RetentionKind.USAGE:
        count = await session.scalar(
            select(func.count())
            .select_from(UsageLedgerEntryModel)
            .where(
                UsageLedgerEntryModel.project_id.in_(_studio_projects(studio_id)),
                UsageLedgerEntryModel.created_at < cutoff,
            )
        )
    elif kind is RetentionKind.SNAPSHOTS:
        count = await session.scalar(
            select(func.count())
            .select_from(ExecutionSnapshotModel)
            .where(
                ExecutionSnapshotModel.project_id.in_(_studio_projects(studio_id)),
                ExecutionSnapshotModel.created_at < cutoff,
            )
        )
    else:
        count = await session.scalar(
            select(func.count())
            .select_from(TransferModel)
            .where(
                TransferModel.studio_id == studio_id,
                TransferModel.created_at < cutoff,
            )
        )
    return int(count or 0)


async def _delete_overdue(
    session: AsyncSession, studio_id: uuid.UUID, kind: RetentionKind, cutoff: datetime
) -> int:
    if kind in _EVENTS_KINDS:
        result = await session.execute(
            delete(EventModel).where(
                EventModel.project_id.in_(_studio_projects(studio_id)),
                EventModel.server_timestamp < cutoff,
            )
        )
    elif kind is RetentionKind.USAGE:
        result = await session.execute(
            delete(UsageLedgerEntryModel).where(
                UsageLedgerEntryModel.project_id.in_(_studio_projects(studio_id)),
                UsageLedgerEntryModel.created_at < cutoff,
            )
        )
    elif kind is RetentionKind.SNAPSHOTS:
        result = await session.execute(
            delete(ExecutionSnapshotModel).where(
                ExecutionSnapshotModel.project_id.in_(_studio_projects(studio_id)),
                ExecutionSnapshotModel.created_at < cutoff,
            )
        )
    else:
        result = await session.execute(
            delete(TransferModel).where(
                TransferModel.studio_id == studio_id,
                TransferModel.created_at < cutoff,
            )
        )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def _delete_transfer_objects(
    session: AsyncSession,
    storage: StorageProvider,
    studio_id: uuid.UUID,
    cutoff: datetime,
) -> int | None:
    keys = (
        await session.execute(
            select(TransferModel.object_key).where(
                TransferModel.studio_id == studio_id,
                TransferModel.created_at < cutoff,
            )
        )
    ).scalars()
    object_keys = list(keys)
    try:
        for object_key in object_keys:
            await storage.delete_object(object_key)
    except (BotoCoreError, ClientError):
        logger.warning(
            "retention purge skipped studio %s transfers: object storage unavailable", studio_id
        )
        return None
    return len(object_keys)


async def announce_due(
    session: AsyncSession, now: datetime | None = None
) -> list[RetentionPurgeNoticeModel]:
    """Open one notice per `(studio, kind)` whose plan duration is exceeded."""
    announced_at = now or datetime.now(UTC)
    default_plan = (
        await session.scalar(select(PlanModel.code).where(PlanModel.is_default.is_(True))) or "free"
    )
    limits: dict[tuple[str, str], int | None] = {}
    limit_rows = (
        await session.execute(
            select(
                PlanLimitModel.plan_code,
                PlanLimitModel.limit_key,
                PlanLimitModel.max_value,
            ).where(PlanLimitModel.limit_key.in_(LIMIT_KEYS.values()))
        )
    ).all()
    for plan_code, limit_key, max_value in limit_rows:
        limits[(plan_code, limit_key)] = max_value

    open_rows = (
        await session.execute(
            select(RetentionPurgeNoticeModel.studio_id, RetentionPurgeNoticeModel.kind).where(
                RetentionPurgeNoticeModel.purged_at.is_(None)
            )
        )
    ).all()
    open_notice_keys = {(studio_id, kind) for studio_id, kind in open_rows}

    created: list[RetentionPurgeNoticeModel] = []
    studios = (await session.execute(select(StudioModel.id, StudioModel.plan))).all()
    for studio_id, plan_code in studios:
        plan = plan_code or default_plan
        exported_hint: bool | None = None
        for kind, limit_key in LIMIT_KEYS.items():
            days = limits.get((plan, limit_key))
            if days is None:
                continue
            if (studio_id, kind.value) in open_notice_keys:
                continue
            cutoff = announced_at - timedelta(days=days)
            if await _count_overdue(session, studio_id, kind, cutoff) == 0:
                continue
            if exported_hint is None:
                exported_hint = (
                    await session.scalar(
                        select(StudioExportModel.id)
                        .where(StudioExportModel.studio_id == studio_id)
                        .limit(1)
                    )
                    is not None
                )
            notice = RetentionPurgeNoticeModel(
                studio_id=studio_id,
                kind=kind.value,
                cutoff=cutoff,
                announced_at=announced_at,
                purge_after=announced_at + timedelta(days=PURGE_NOTICE_DAYS),
                exported_hint=exported_hint,
            )
            session.add(notice)
            created.append(notice)
            open_notice_keys.add((studio_id, kind.value))
    return created


async def purge_announced(
    session: AsyncSession,
    storage: StorageProvider,
    now: datetime | None = None,
) -> list[RetentionPurgeOutcome]:
    """Execute every open notice whose `purge_after` elapsed, and only those."""
    purged_at = now or datetime.now(UTC)
    notices = (
        (
            await session.execute(
                select(RetentionPurgeNoticeModel)
                .where(
                    RetentionPurgeNoticeModel.purged_at.is_(None),
                    RetentionPurgeNoticeModel.purge_after <= purged_at,
                )
                .order_by(RetentionPurgeNoticeModel.purge_after, RetentionPurgeNoticeModel.kind)
            )
        )
        .scalars()
        .all()
    )
    outcomes: list[RetentionPurgeOutcome] = []
    for notice in notices:
        kind = RetentionKind(notice.kind)
        objects_deleted = 0
        if kind is RetentionKind.TRANSFERS:
            deleted_objects = await _delete_transfer_objects(
                session, storage, notice.studio_id, notice.cutoff
            )
            if deleted_objects is None:
                continue
            objects_deleted = deleted_objects
        rows_deleted = await _delete_overdue(session, notice.studio_id, kind, notice.cutoff)
        notice.purged_at = purged_at
        session.add(
            RetentionPurgeLogModel(
                studio_id=notice.studio_id,
                kind=kind.value,
                rows_deleted=rows_deleted,
                objects_deleted=objects_deleted,
                purged_at=purged_at,
            )
        )
        outcomes.append(
            RetentionPurgeOutcome(
                studio_id=notice.studio_id,
                kind=kind,
                rows_deleted=rows_deleted,
                objects_deleted=objects_deleted,
                purged_at=purged_at,
            )
        )
    return outcomes
