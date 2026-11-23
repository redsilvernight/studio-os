"""Announced retention purge (0054).

Real PostgreSQL. Retention is announced first, executed only after the 7-day
window, at the cutoff fixed by the announcement, and only for the studio the
notice names. The purge journal counts rows and objects — it stores no content.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from botocore.exceptions import ClientError
from httpx import AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.event import EventModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.plan import PlanLimitModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.retention import (
    RetentionKind,
    RetentionPurgeLogModel,
    RetentionPurgeNoticeModel,
)
from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.usage import UsageLedgerEntryModel
from studio_api.services import projects as projects_service
from studio_api.services import retention as retention_service

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


class _Storage:
    """Records deletions; `fail=True` simulates an unavailable object storage."""

    def __init__(self, *, fail: bool = False) -> None:
        self.deleted: list[str] = []
        self.fail = fail

    async def delete_object(self, object_key: str) -> None:
        if self.fail:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")
        self.deleted.append(object_key)


async def _studio(session: AsyncSession, plan: str = "free") -> StudioModel:
    studio = StudioModel(slug=f"ret-{uuid.uuid4().hex[:8]}", name="Retention", plan=plan)
    session.add(studio)
    await session.flush()
    return studio


async def _project(session: AsyncSession, studio: StudioModel) -> ProjectModel:
    return await projects_service.create_project(
        session,
        f"ret-proj-{uuid.uuid4().hex[:8]}",
        "Retention Project",
        None,
        creator=None,
        studio_id=studio.id,
    )


async def _event(
    session: AsyncSession,
    project: ProjectModel,
    age: timedelta,
    payload: dict[str, Any] | None = None,
) -> EventModel:
    moment = NOW - age
    event = EventModel(
        event_type="task.created",
        project_id=project.id,
        actor_type="user",
        actor_id=uuid.uuid4(),
        client_timestamp=moment,
        server_timestamp=moment,
        payload=payload or {},
    )
    session.add(event)
    await session.flush()
    return event


async def _usage(
    session: AsyncSession, project: ProjectModel, machine: MachineModel, age: timedelta
) -> UsageLedgerEntryModel:
    moment = NOW - age
    entry = UsageLedgerEntryModel(
        project_id=project.id,
        machine_id=machine.id,
        source_event_id=f"evt-{uuid.uuid4().hex[:12]}",
        collector="runtime",
        period_start=moment,
        period_end=moment,
        created_at=moment,
    )
    session.add(entry)
    await session.flush()
    return entry


async def _transfer(
    session: AsyncSession,
    studio: StudioModel,
    user_id: uuid.UUID,
    age: timedelta,
    filename: str = "secret-report.txt",
) -> TransferModel:
    transfer = TransferModel(
        studio_id=studio.id,
        transfer_code=f"TRF-{uuid.uuid4().hex[:8].upper()}",
        sender_user_id=user_id,
        category="temporary",
        filename=filename,
        object_key=f"retention/{uuid.uuid4().hex}/{filename}",
        content_type="text/plain",
        size_bytes=10,
        status="ready",
        created_at=NOW - age,
    )
    session.add(transfer)
    await session.flush()
    return transfer


async def _event_count(session: AsyncSession, project_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(EventModel).where(EventModel.project_id == project_id)
        )
        or 0
    )


async def _notice(
    session: AsyncSession, studio_id: uuid.UUID, kind: RetentionKind
) -> RetentionPurgeNoticeModel | None:
    return await session.scalar(
        select(RetentionPurgeNoticeModel).where(
            RetentionPurgeNoticeModel.studio_id == studio_id,
            RetentionPurgeNoticeModel.kind == kind.value,
        )
    )


async def _set_limit(session: AsyncSession, plan: str, key: str, value: int | None) -> None:
    await session.execute(
        update(PlanLimitModel)
        .where(PlanLimitModel.plan_code == plan, PlanLimitModel.limit_key == key)
        .values(max_value=value)
    )
    await session.flush()


def _headers(token: str, studio_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Studio-Id": str(studio_id)}


async def test_nothing_is_purged_without_an_announcement(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    studio = await _studio(db_session)
    project = await _project(db_session, studio)
    await _event(db_session, project, 400 * DAY)
    storage = _Storage()

    outcomes = await retention_service.purge_announced(db_session, storage, now=NOW)

    assert outcomes == []
    assert await _event_count(db_session, project.id) == 1
    assert await db_session.scalar(select(func.count()).select_from(RetentionPurgeLogModel)) == 0


async def test_purge_wait_for_the_seven_day_window_then_honours_the_cutoff(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    studio = await _studio(db_session)
    project = await _project(db_session, studio)
    too_old = await _event(db_session, project, 31 * DAY)
    kept = await _event(db_session, project, 29 * DAY)
    storage = _Storage()

    announced = await retention_service.announce_due(db_session, now=NOW)
    notice = await _notice(db_session, studio.id, RetentionKind.EVENTS)
    assert notice is not None
    assert any(created.id == notice.id for created in announced)
    assert notice.cutoff == NOW - 30 * DAY
    assert notice.purge_after == NOW + 7 * DAY
    assert notice.purged_at is None

    again = await retention_service.announce_due(db_session, now=NOW + 2 * DAY)
    assert again == []
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(RetentionPurgeNoticeModel)
            .where(
                RetentionPurgeNoticeModel.studio_id == studio.id,
                RetentionPurgeNoticeModel.kind == RetentionKind.EVENTS.value,
            )
        )
        == 1
    )

    assert await retention_service.purge_announced(db_session, storage, now=NOW + 6 * DAY) == []
    assert await _event_count(db_session, project.id) == 2

    outcomes = await retention_service.purge_announced(db_session, storage, now=NOW + 7 * DAY)

    assert (studio.id, RetentionKind.EVENTS, 1) in [
        (o.studio_id, o.kind, o.rows_deleted) for o in outcomes
    ]
    remaining = (
        (await db_session.execute(select(EventModel.id).where(EventModel.project_id == project.id)))
        .scalars()
        .all()
    )
    assert list(remaining) == [kept.id]
    assert too_old.id not in remaining
    await db_session.refresh(notice)
    assert notice.purged_at == NOW + 7 * DAY


async def test_announcements_follow_the_plan_duration_free_versus_pro(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    free = await _studio(db_session, plan="free")
    pro = await _studio(db_session, plan="pro")
    free_project = await _project(db_session, free)
    pro_project = await _project(db_session, pro)
    await _event(db_session, free_project, 100 * DAY)
    await _event(db_session, pro_project, 100 * DAY)
    await _transfer(db_session, free, machine[0].owner_user_id, 20 * DAY)
    await _transfer(db_session, pro, machine[0].owner_user_id, 20 * DAY)

    await retention_service.announce_due(db_session, now=NOW)

    free_events = await _notice(db_session, free.id, RetentionKind.EVENTS)
    free_transfers = await _notice(db_session, free.id, RetentionKind.TRANSFERS)
    assert free_events is not None and free_events.cutoff == NOW - 30 * DAY
    assert free_transfers is not None and free_transfers.cutoff == NOW - 14 * DAY
    assert await _notice(db_session, pro.id, RetentionKind.EVENTS) is None
    assert await _notice(db_session, pro.id, RetentionKind.TRANSFERS) is None

    await _event(db_session, pro_project, 400 * DAY)
    await _transfer(db_session, pro, machine[0].owner_user_id, 100 * DAY)
    await retention_service.announce_due(db_session, now=NOW)

    pro_events = await _notice(db_session, pro.id, RetentionKind.EVENTS)
    pro_transfers = await _notice(db_session, pro.id, RetentionKind.TRANSFERS)
    assert pro_events is not None and pro_events.cutoff == NOW - 365 * DAY
    assert pro_transfers is not None and pro_transfers.cutoff == NOW - 90 * DAY


async def test_usage_rows_are_purged_by_the_notice_cutoff(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    studio = await _studio(db_session)
    project = await _project(db_session, studio)
    old = await _usage(db_session, project, machine[0], 40 * DAY)
    recent = await _usage(db_session, project, machine[0], 10 * DAY)
    assert old.id != recent.id

    await retention_service.announce_due(db_session, now=NOW)
    outcome = [
        item
        for item in await retention_service.purge_announced(
            db_session, _Storage(), now=NOW + 7 * DAY
        )
        if item.studio_id == studio.id and item.kind is RetentionKind.USAGE
    ]

    assert [(item.rows_deleted, item.objects_deleted) for item in outcome] == [(1, 0)]
    remaining = (
        (
            await db_session.execute(
                select(UsageLedgerEntryModel.id).where(
                    UsageLedgerEntryModel.project_id == project.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert list(remaining) == [recent.id]


async def test_unlimited_plan_duration_never_announces_or_purges(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    await _set_limit(db_session, "free", "event_retention_days", None)
    await _set_limit(db_session, "free", "timeline_retention_days", None)
    studio = await _studio(db_session)
    project = await _project(db_session, studio)
    await _event(db_session, project, 4000 * DAY)

    announced = await retention_service.announce_due(db_session, now=NOW)
    assert [notice for notice in announced if notice.studio_id == studio.id] == []
    outcomes = await retention_service.purge_announced(db_session, _Storage(), now=NOW + 30 * DAY)
    assert [outcome for outcome in outcomes if outcome.studio_id == studio.id] == []
    assert await _event_count(db_session, project.id) == 1


async def test_purge_journal_carries_counts_only(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    studio = await _studio(db_session)
    project = await _project(db_session, studio)
    await _event(db_session, project, 60 * DAY, payload={"title": "Secret event title"})
    await _transfer(db_session, studio, machine[0].owner_user_id, 40 * DAY)

    await retention_service.announce_due(db_session, now=NOW)
    await retention_service.purge_announced(db_session, _Storage(), now=NOW + 7 * DAY)

    columns = (
        (
            await db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'retention_purge_log' ORDER BY column_name"
                )
            )
        )
        .scalars()
        .all()
    )
    assert list(columns) == [
        "id",
        "kind",
        "objects_deleted",
        "purged_at",
        "rows_deleted",
        "studio_id",
    ]
    kinds = (await db_session.execute(select(RetentionPurgeLogModel.kind))).scalars().all()
    assert set(kinds) <= {kind.value for kind in RetentionKind}
    rows = (
        await db_session.execute(
            select(
                RetentionPurgeLogModel.kind,
                RetentionPurgeLogModel.rows_deleted,
                RetentionPurgeLogModel.objects_deleted,
            ).where(RetentionPurgeLogModel.studio_id == studio.id)
        )
    ).all()
    assert sorted(tuple(row) for row in rows) == [
        ("events", 1, 0),
        ("timeline", 0, 0),
        ("transfers", 1, 1),
    ]


async def test_purge_is_scoped_to_the_noticed_studio(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    noticed = await _studio(db_session)
    other = await _studio(db_session, plan="pro")
    noticed_project = await _project(db_session, noticed)
    other_project = await _project(db_session, other)
    await _event(db_session, noticed_project, 60 * DAY)
    await _event(db_session, other_project, 60 * DAY)

    await retention_service.announce_due(db_session, now=NOW)
    await retention_service.purge_announced(db_session, _Storage(), now=NOW + 7 * DAY)

    assert await _event_count(db_session, noticed_project.id) == 0
    assert await _event_count(db_session, other_project.id) == 1
    logged = (
        await db_session.execute(
            select(func.count())
            .select_from(RetentionPurgeLogModel)
            .where(RetentionPurgeLogModel.studio_id == other.id)
        )
    ).scalar()
    assert logged == 0


async def test_transfer_objects_go_before_their_rows_and_failures_keep_the_notice_open(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    studio = await _studio(db_session)
    transfer = await _transfer(db_session, studio, machine[0].owner_user_id, 40 * DAY)
    await retention_service.announce_due(db_session, now=NOW)
    storage = _Storage()

    failing = await retention_service.purge_announced(
        db_session, _Storage(fail=True), now=NOW + 7 * DAY
    )

    assert [item for item in failing if item.studio_id == studio.id] == []
    assert await db_session.get(TransferModel, transfer.id) is not None
    notice = await _notice(db_session, studio.id, RetentionKind.TRANSFERS)
    assert notice is not None and notice.purged_at is None

    outcomes = await retention_service.purge_announced(db_session, storage, now=NOW + 8 * DAY)

    assert storage.deleted == [transfer.object_key]
    studio_outcomes = [
        (o.kind, o.rows_deleted, o.objects_deleted) for o in outcomes if o.studio_id == studio.id
    ]
    assert studio_outcomes == [(RetentionKind.TRANSFERS, 1, 1)]
    assert await db_session.get(TransferModel, transfer.id) is None


async def test_retention_endpoint_lists_open_notices_for_members(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    studio = await _studio(db_session)
    db_session.add(
        StudioMembershipModel(studio_id=studio.id, user_id=machine[0].owner_user_id, role="member")
    )
    project = await _project(db_session, studio)
    await _event(db_session, project, 60 * DAY)
    await retention_service.announce_due(db_session, now=NOW)
    await db_session.flush()

    response = await client.get(
        f"/api/v1/studios/{studio.id}/retention", headers=_headers(machine[1], studio.id)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["studio_id"] == str(studio.id)
    assert body["export_url"] == f"/api/v1/studios/{studio.id}/exports"
    assert [notice["kind"] for notice in body["notices"]] == ["events", "timeline"]
    purge_after = datetime.fromisoformat(body["notices"][0]["purge_after"].replace("Z", "+00:00"))
    assert purge_after == NOW + 7 * DAY
    assert body["notices"][0]["exported_hint"] is False

    forbidden = await client.get(
        f"/api/v1/studios/{studio.id}/retention", headers=_headers(other_machine[1], studio.id)
    )
    assert forbidden.status_code == 403
