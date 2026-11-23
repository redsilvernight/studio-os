"""Export -> restore round trip of one studio (S5): counts, files and tenant isolation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.roadmap import RoadmapModel
from studio_api.db.models.studio import StudioMembershipModel, StudioModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.user import UserModel
from studio_api.services import projects as projects_service
from studio_api.services.studio_export import build_export_archive
from studio_api.services.studio_restore import (
    RestoreError,
    count_studio_rows,
    restore_studio_archive,
)

PAYLOAD = b"restore payload\n" * 8


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_object(self, object_key: str, payload: bytes, content_type: str) -> None:
        self.objects[object_key] = payload

    async def get_object(self, object_key: str) -> bytes:
        return self.objects[object_key]


async def _seed(session: AsyncSession, owner: UserModel, storage: MemoryStorage) -> StudioModel:
    studio = StudioModel(slug=f"src-{uuid.uuid4().hex[:8]}", name="Source")
    session.add(studio)
    await session.commit()
    session.add(StudioMembershipModel(studio_id=studio.id, user_id=owner.id, role="owner"))
    await session.commit()
    project = await projects_service.create_project(
        session, f"p-{uuid.uuid4().hex[:8]}", "P", None, creator=owner, studio_id=studio.id
    )
    task = TaskModel(project_id=project.id, title="T", status="created")
    session.add(task)
    await session.flush()
    session.add_all(
        [
            RoadmapModel(
                project_id=project.id,
                title="R",
                origin="manual",
                actor_type="user",
                actor_id=owner.id,
            ),
            DecisionModel(
                studio_id=studio.id,
                readable_id=f"DEC-{uuid.uuid4().hex[:8]}",
                project_id=project.id,
                task_id=task.id,
                title="D",
                body="b",
                proposed_by_type="user",
                proposed_by_id=owner.id,
            ),
            TransferModel(
                studio_id=studio.id,
                project_id=project.id,
                transfer_code=f"TRF-{uuid.uuid4().hex[:8].upper()}",
                sender_user_id=owner.id,
                category="temporary",
                filename="report.txt",
                object_key=f"studio/src/{uuid.uuid4().hex}/report.txt",
                content_type="text/plain",
                size_bytes=len(PAYLOAD),
                status="ready",
                created_at=datetime.now(UTC),
            ),
        ]
    )
    await session.commit()
    key = (
        await session.execute(
            select(TransferModel.object_key).where(TransferModel.studio_id == studio.id)
        )
    ).scalar_one()
    await storage.put_object(key, PAYLOAD, "text/plain")
    return studio


async def test_restore_round_trip(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    owner = await db_session.get(UserModel, machine[0].owner_user_id)
    assert owner is not None
    storage: Any = MemoryStorage()
    source = await _seed(db_session, owner, storage)
    before = await count_studio_rows(db_session, source.id)

    archive = await build_export_archive(
        db_session, storage, source, uuid.uuid4(), datetime.now(UTC)
    )
    result = await restore_studio_archive(db_session, storage, archive.payload, owner)
    await db_session.commit()

    assert result.studio.id != source.id
    assert result.studio.slug != source.slug
    assert await count_studio_rows(db_session, result.studio.id) == before
    assert await count_studio_rows(db_session, source.id) == before
    assert (result.files, result.skipped_files) == (1, 0)

    restored_key = (
        await db_session.execute(
            select(TransferModel.object_key).where(TransferModel.studio_id == result.studio.id)
        )
    ).scalar_one()
    assert storage.objects[restored_key] == PAYLOAD
    source_keys = (
        (
            await db_session.execute(
                select(TransferModel.object_key).where(TransferModel.studio_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    assert restored_key not in source_keys

    members = (
        await db_session.execute(
            select(StudioMembershipModel.user_id, StudioMembershipModel.role).where(
                StudioMembershipModel.studio_id == result.studio.id
            )
        )
    ).all()
    assert [(user_id, role) for user_id, role in members] == [(owner.id, "owner")]


async def test_restore_refuses_a_foreign_archive(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    owner = await db_session.get(UserModel, machine[0].owner_user_id)
    assert owner is not None
    with pytest.raises(RestoreError):
        await restore_studio_archive(db_session, MemoryStorage(), b"not a zip", owner)  # type: ignore[arg-type]
