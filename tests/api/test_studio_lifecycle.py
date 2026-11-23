"""Studio export and deletion lifecycle (0051).

Real PostgreSQL and MinIO: the export archive is built by reading the studio's
stored files, and the purge must remove every row the studio owns as well as its
objects. Marked `infra("minio")`; skipped when either service is down.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from botocore.exceptions import ClientError
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.roadmap import RoadmapModel
from studio_api.db.models.studio import (
    INTERNAL_STUDIO_ID,
    PENDING_DELETION_STATUS,
    StudioMembershipModel,
    StudioModel,
)
from studio_api.db.models.studio_export import StudioExportModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.user import UserModel
from studio_api.services import projects as projects_service
from studio_api.services import studio_deletion as deletion_service
from studio_api.settings import get_settings
from studio_api.storage.provider import get_storage

pytestmark = pytest.mark.infra("minio")

REPORT_PAYLOAD = b"studio export payload\n" * 20


def _headers(token: str, studio_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Studio-Id": str(studio_id)}


async def _user_of(session: AsyncSession, machine_owner_id: uuid.UUID) -> UserModel:
    user = await session.get(UserModel, machine_owner_id)
    assert user is not None
    return user


async def _new_studio(session: AsyncSession, prefix: str) -> StudioModel:
    studio = StudioModel(slug=f"{prefix}-{uuid.uuid4().hex[:8]}", name=prefix.title())
    session.add(studio)
    await session.commit()
    await session.refresh(studio)
    return studio


async def _grant(session: AsyncSession, studio: StudioModel, user: UserModel, role: str) -> None:
    session.add(StudioMembershipModel(studio_id=studio.id, user_id=user.id, role=role))
    await session.commit()


async def _seed_project_data(
    session: AsyncSession, studio: StudioModel, owner: UserModel
) -> tuple[ProjectModel, TaskModel, RoadmapModel, DecisionModel]:
    project = await projects_service.create_project(
        session,
        f"proj-{uuid.uuid4().hex[:8]}",
        "Export Project",
        None,
        creator=owner,
        studio_id=studio.id,
    )
    task = TaskModel(project_id=project.id, title="Exported task", status="created")
    session.add(task)
    roadmap = RoadmapModel(
        project_id=project.id,
        title="Exported roadmap",
        origin="manual",
        actor_type="user",
        actor_id=owner.id,
    )
    decision = DecisionModel(
        studio_id=studio.id,
        readable_id=f"DEC-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        title="Exported decision",
        body="Decision body",
        proposed_by_type="user",
        proposed_by_id=owner.id,
    )
    session.add_all([roadmap, decision])
    await session.commit()
    await session.refresh(task)
    await session.refresh(roadmap)
    await session.refresh(decision)
    return project, task, roadmap, decision


async def _seed_transfer(
    session: AsyncSession,
    studio: StudioModel,
    sender: UserModel,
    filename: str = "report.txt",
) -> tuple[TransferModel, str]:
    object_key = f"studio/test/{uuid.uuid4().hex}/{filename}"
    transfer = TransferModel(
        studio_id=studio.id,
        transfer_code=f"TRF-{uuid.uuid4().hex[:8].upper()}",
        sender_user_id=sender.id,
        category="temporary",
        filename=filename,
        object_key=object_key,
        content_type="text/plain",
        size_bytes=len(REPORT_PAYLOAD),
        status="ready",
        created_at=datetime.now(UTC),
    )
    session.add(transfer)
    await session.commit()
    await session.refresh(transfer)
    await get_storage().put_object(object_key, REPORT_PAYLOAD, "text/plain")
    return transfer, object_key


def _zip_json(payload: bytes) -> tuple[dict[str, Any], zipfile.ZipFile]:
    archive = zipfile.ZipFile(io.BytesIO(payload))
    raw = archive.read("studio-export.json")
    return json.loads(raw), archive


async def test_export_contains_every_studio_data_and_file(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    machine_model, token = machine
    owner = await _user_of(db_session, machine_model.owner_user_id)
    other_model, other_token = other_machine
    other = await _user_of(db_session, other_model.owner_user_id)
    studio = await _new_studio(db_session, "alpha")
    await _grant(db_session, studio, owner, "owner")
    await _grant(db_session, studio, other, "member")
    project, task, roadmap, decision = await _seed_project_data(db_session, studio, owner)
    transfer, object_key = await _seed_transfer(db_session, studio, owner)
    export_object: str | None = None
    try:
        response = await client.post(
            f"/api/v1/studios/{studio.id}/exports", headers=_headers(token, studio.id)
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["studio_id"] == str(studio.id)
        assert {"id", "studio_id", "created_at", "expires_at"} == set(body)

        row = await db_session.get(StudioExportModel, uuid.UUID(body["id"]))
        assert row is not None
        export_object = row.object_key
        assert row.object_key.startswith(f"studios/{studio.id}/exports/{row.id}/")
        assert row.expires_at - row.created_at == timedelta(
            days=get_settings().export_retention_days
        )

        link = await client.get(
            f"/api/v1/studios/{studio.id}/exports/{row.id}",
            headers=_headers(token, studio.id),
        )
        assert link.status_code == 200, link.text
        payload = link.json()
        assert set(payload) == {"download_url", "expires_at"}
        link_expiry = datetime.fromisoformat(payload["expires_at"])
        assert link_expiry <= datetime.now(UTC) + timedelta(minutes=15, seconds=5)

        async with httpx.AsyncClient() as downloader:
            archived = await downloader.get(payload["download_url"])
        assert archived.status_code == 200
        data, archive = _zip_json(archived.content)
        try:
            assert data["schema"] == "studio.export/v1"
            assert data["studio"]["slug"] == studio.slug
            assert [p["slug"] for p in data["projects"]] == [project.slug]
            assert [t["title"] for t in data["tasks"]] == [task.title]
            assert [r["title"] for r in data["roadmaps"]] == [roadmap.title]
            assert [d["title"] for d in data["decisions"]] == [decision.title]
            member_roles = {m["email"]: m["role"] for m in data["members"]}
            assert member_roles[owner.email] == "owner"
            assert member_roles[other.email] == "member"
            file_metadata = data["files"][0]
            assert file_metadata["object_key"] == object_key
            archived_file = archive.read(f"files/{transfer.id}/report.txt")
            assert archived_file == REPORT_PAYLOAD
        finally:
            archive.close()

        # Non-owner (member): owner-only, on both export routes.
        refused = await client.post(
            f"/api/v1/studios/{studio.id}/exports", headers=_headers(other_token, studio.id)
        )
        assert refused.status_code == 403
        assert refused.json()["detail"]["error_code"] == "owner_only"
        foreign = await client.get(
            f"/api/v1/studios/{studio.id}/exports/{row.id}",
            headers=_headers(other_token, studio.id),
        )
        assert foreign.status_code == 403
    finally:
        if export_object is not None:
            await get_storage().delete_object(export_object)
        await get_storage().delete_object(object_key)


async def test_deletion_grace_window_and_cancellation(
    client: AsyncClient,
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
) -> None:
    machine_model, token = machine
    owner = await _user_of(db_session, machine_model.owner_user_id)
    studio = await _new_studio(db_session, "beta")
    await _grant(db_session, studio, owner, "owner")
    headers = _headers(token, studio.id)

    wrong = await client.post(
        f"/api/v1/studios/{studio.id}/deletion",
        headers=headers,
        json={"confirmation": "not-the-slug"},
    )
    assert wrong.status_code == 409
    assert wrong.json()["detail"]["error_code"] == "invalid_confirmation"

    requested = await client.post(
        f"/api/v1/studios/{studio.id}/deletion",
        headers=headers,
        json={"confirmation": studio.slug},
    )
    assert requested.status_code == 200, requested.text
    body = requested.json()
    assert set(body) == {"deletion_requested_at", "deletion_scheduled_at"}
    requested_at = datetime.fromisoformat(body["deletion_requested_at"])
    scheduled_at = datetime.fromisoformat(body["deletion_scheduled_at"])
    assert scheduled_at - requested_at == timedelta(days=get_settings().deletion_grace_days)

    await db_session.refresh(studio)
    assert studio.status == PENDING_DELETION_STATUS
    assert studio.deletion_scheduled_at is not None

    # The studio detail reports the purge date (N7 reads it after a reload).
    detail = await client.get(f"/api/v1/studios/{studio.id}", headers=headers)
    assert datetime.fromisoformat(detail.json()["deletion_scheduled_at"]) == scheduled_at

    # Read-only: a write is refused with 409, a second request keeps the
    # original schedule, and an export still works during the grace window.
    refused_write = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"slug": f"blocked-{uuid.uuid4().hex[:8]}", "name": "Blocked"},
    )
    assert refused_write.status_code == 409
    assert refused_write.json()["detail"]["error_code"] == "studio_pending_deletion"
    again = await client.post(
        f"/api/v1/studios/{studio.id}/deletion",
        headers=headers,
        json={"confirmation": studio.slug},
    )
    assert again.status_code == 200
    assert datetime.fromisoformat(again.json()["deletion_scheduled_at"]) == scheduled_at
    export = await client.post(f"/api/v1/studios/{studio.id}/exports", headers=headers)
    assert export.status_code == 201, export.text
    row = await db_session.get(StudioExportModel, uuid.UUID(export.json()["id"]))
    assert row is not None
    try:
        cancelled = await client.delete(f"/api/v1/studios/{studio.id}/deletion", headers=headers)
        assert cancelled.status_code == 204
        await db_session.refresh(studio)
        assert studio.status == "active"
        assert studio.deletion_requested_at is None
        assert studio.deletion_scheduled_at is None
        # Idempotent: nothing scheduled, still 204.
        assert (
            await client.delete(f"/api/v1/studios/{studio.id}/deletion", headers=headers)
        ).status_code == 204
        created = await client.post(
            "/api/v1/projects",
            headers=headers,
            json={"slug": f"allowed-{uuid.uuid4().hex[:8]}", "name": "Allowed"},
        )
        assert created.status_code == 201, created.text
    finally:
        await get_storage().delete_object(row.object_key)


async def test_purge_removes_only_the_due_studio(
    db_session: AsyncSession,
    machine: tuple[MachineModel, str],
    other_machine: tuple[MachineModel, str],
) -> None:
    machine_model, _ = machine
    other_model, _ = other_machine
    owner = await _user_of(db_session, machine_model.owner_user_id)
    other = await _user_of(db_session, other_model.owner_user_id)
    doomed = await _new_studio(db_session, "doomed")
    kept = await _new_studio(db_session, "kept")
    await _grant(db_session, doomed, owner, "owner")
    await _grant(db_session, kept, other, "owner")
    doomed_project, doomed_task, _, _ = await _seed_project_data(db_session, doomed, owner)
    kept_project, kept_task, _, _ = await _seed_project_data(db_session, kept, other)
    doomed_transfer, doomed_key = await _seed_transfer(db_session, doomed, owner)
    kept_transfer, kept_key = await _seed_transfer(db_session, kept, other)
    # `expire_all` below invalidates loaded ORM instances: keep the ids the
    # assertions need (attribute access after expiration would lazily load).
    doomed_id, kept_id = doomed.id, kept.id
    doomed_project_id, doomed_task_id = doomed_project.id, doomed_task.id
    kept_project_id, kept_task_id = kept_project.id, kept_task.id
    kept_transfer_id = kept_transfer.id
    storage = get_storage()
    export_key = f"studios/{doomed_id}/exports/{uuid.uuid4()}/archive.zip"
    await storage.put_object(export_key, b"archive", "application/zip")
    db_session.add(
        StudioExportModel(
            studio_id=doomed.id,
            requested_by_user_id=owner.id,
            object_key=export_key,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    # Due in the past for the doomed studio; the internal studio is scheduled
    # by hand to prove the purge never selects it.
    now = datetime.now(UTC)
    doomed.deletion_requested_at = now - timedelta(days=8)
    doomed.deletion_scheduled_at = now - timedelta(days=1)
    doomed.status = PENDING_DELETION_STATUS
    internal = await db_session.get(StudioModel, INTERNAL_STUDIO_ID)
    assert internal is not None
    internal.deletion_requested_at = now - timedelta(days=8)
    internal.deletion_scheduled_at = now - timedelta(days=1)
    await db_session.commit()

    results = await deletion_service.purge_due_studios(db_session, storage, get_settings(), now=now)
    db_session.expire_all()

    assert [result.studio_id for result in results] == [doomed_id]
    assert await db_session.get(StudioModel, doomed_id) is None
    assert (
        await db_session.scalar(select(ProjectModel.id).where(ProjectModel.studio_id == doomed_id))
        is None
    )
    assert (
        await db_session.scalar(
            select(TaskModel.id).where(TaskModel.project_id == doomed_project_id)
        )
        is None
    )
    assert await db_session.get(TaskModel, doomed_task_id) is None
    assert (
        await db_session.scalar(
            select(TransferModel.id).where(TransferModel.studio_id == doomed_id)
        )
        is None
    )
    assert (
        await db_session.scalar(
            select(StudioMembershipModel.user_id).where(
                StudioMembershipModel.studio_id == doomed_id
            )
        )
        is None
    )
    assert (
        await db_session.scalar(
            select(StudioExportModel.id).where(StudioExportModel.studio_id == doomed_id)
        )
        is None
    )

    # Other studio and the internal studio are untouched.
    assert await db_session.get(StudioModel, kept_id) is not None
    assert await db_session.get(ProjectModel, kept_project_id) is not None
    assert await db_session.get(TaskModel, kept_task_id) is not None
    assert await db_session.get(TransferModel, kept_transfer_id) is not None
    assert await db_session.get(StudioModel, INTERNAL_STUDIO_ID) is not None
    assert (await storage.head_object(kept_key))["ContentLength"] == len(REPORT_PAYLOAD)

    # Doomed storage is gone (file + export archive), kept file remains.
    with pytest.raises(ClientError):
        await storage.head_object(doomed_key)
    with pytest.raises(ClientError):
        await storage.head_object(export_key)
    await storage.delete_object(kept_key)


async def test_purge_ignores_a_studio_still_in_its_grace_window(
    db_session: AsyncSession, machine: tuple[MachineModel, str]
) -> None:
    machine_model, _ = machine
    owner = await _user_of(db_session, machine_model.owner_user_id)
    studio = await _new_studio(db_session, "waiting")
    await _grant(db_session, studio, owner, "owner")
    now = datetime.now(UTC)
    studio.deletion_requested_at = now
    studio.deletion_scheduled_at = now + timedelta(days=1)
    studio.status = PENDING_DELETION_STATUS
    await db_session.commit()

    results = await deletion_service.purge_due_studios(
        db_session, get_storage(), get_settings(), now=now
    )
    assert results == []
    assert await db_session.get(StudioModel, studio.id) is not None
