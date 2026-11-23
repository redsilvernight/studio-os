"""Complete studio export (0051).

One export is a ZIP archive built by the server, dated, stored in the same
object storage as every other artifact, and downloaded through a short-lived
presigned URL. It carries every piece of studio data the API knows about plus
the studio's MinIO files, so an owner can leave with everything before deleting
the studio.

The archive is deliberately never gated by a plan limit or a transfer quota:
an export is a read-only recovery path (0051), refused to anyone but the
studio `owner`.
"""

from __future__ import annotations

import io
import json
import logging
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import sqlalchemy as sa
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.roadmap import RoadmapModel
from studio_api.db.models.studio import StudioMembershipModel, StudioModel, StudioRole
from studio_api.db.models.studio_export import StudioExportModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.user import UserModel
from studio_api.services.authz import Principal
from studio_api.settings import Settings
from studio_api.storage.provider import StorageProvider

logger = logging.getLogger(__name__)

EXPORT_SCHEMA = "studio.export/v1"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

# A single object is read into memory to be zipped: bound it so one huge
# transfer cannot exhaust the API process (the metadata still lists it).
MAX_ARCHIVED_FILE_BYTES = 2 * 1024**3


@dataclass(frozen=True)
class ExportArchive:
    """What `build_export_archive` produced, before it is stored."""

    payload: bytes
    object_key: str
    file_count: int
    skipped_files: int


def _json_value(value: Any) -> Any:
    """JSON-safe representation of a column value (UUID, datetime, JSONB,
    enum, bytes …) without leaking Python-only types into the archive."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _row_to_dict(row: Any) -> dict[str, Any]:
    mapper = sa.inspect(row).mapper
    return {attr.key: _json_value(getattr(row, attr.key)) for attr in mapper.column_attrs}


def _rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [_row_to_dict(row) for row in rows]


def _safe_archive_name(filename: str) -> str:
    return _SAFE_NAME.sub("_", filename)[:200] or "file"


def export_object_key(studio: StudioModel, export_id: uuid.UUID, now: datetime) -> str:
    """Storage layout of one dated archive: `studios/{studio}/exports/{id}/…`."""
    return f"studios/{studio.id}/exports/{export_id}/studio-{studio.slug}-{now:%Y%m%dT%H%M%SZ}.zip"


async def _collect_export_data(
    session: AsyncSession, studio: StudioModel, transfers: list[TransferModel]
) -> dict[str, Any]:
    project_ids = list(
        (await session.execute(select(ProjectModel.id).where(ProjectModel.studio_id == studio.id)))
        .scalars()
        .all()
    )
    projects = list(
        (
            await session.execute(
                select(ProjectModel)
                .where(ProjectModel.studio_id == studio.id)
                .order_by(ProjectModel.created_at, ProjectModel.id)
            )
        )
        .scalars()
        .all()
    )
    tasks = (
        list(
            (
                await session.execute(
                    select(TaskModel)
                    .where(TaskModel.project_id.in_(project_ids))
                    .order_by(TaskModel.created_at, TaskModel.id)
                )
            )
            .scalars()
            .all()
        )
        if project_ids
        else []
    )
    roadmaps = (
        list(
            (
                await session.execute(
                    select(RoadmapModel)
                    .where(RoadmapModel.project_id.in_(project_ids))
                    .order_by(RoadmapModel.created_at, RoadmapModel.id)
                )
            )
            .scalars()
            .all()
        )
        if project_ids
        else []
    )
    decisions = list(
        (
            await session.execute(
                select(DecisionModel)
                .where(DecisionModel.studio_id == studio.id)
                .order_by(DecisionModel.created_at, DecisionModel.id)
            )
        )
        .scalars()
        .all()
    )
    memberships = list(
        (
            await session.execute(
                select(StudioMembershipModel, UserModel)
                .join(UserModel, UserModel.id == StudioMembershipModel.user_id)
                .where(StudioMembershipModel.studio_id == studio.id)
                .order_by(StudioMembershipModel.created_at, StudioMembershipModel.user_id)
            )
        ).all()
    )
    members = [
        {
            "user_id": str(user.id),
            "display_name": user.display_name,
            "email": user.email,
            "role": membership.role,
            "granted_by_user_id": _json_value(membership.granted_by_user_id),
            "created_at": _json_value(membership.created_at),
        }
        for membership, user in memberships
    ]
    return {
        "schema": EXPORT_SCHEMA,
        "studio": _row_to_dict(studio),
        "projects": _rows(cast(list[Any], projects)),
        "tasks": _rows(cast(list[Any], tasks)),
        "decisions": _rows(cast(list[Any], decisions)),
        "roadmaps": _rows(cast(list[Any], roadmaps)),
        "members": members,
        "files": _rows(cast(list[Any], transfers)),
    }


async def build_export_archive(
    session: AsyncSession,
    storage: StorageProvider,
    studio: StudioModel,
    export_id: uuid.UUID,
    now: datetime,
) -> ExportArchive:
    """Read every studio row and every stored file, then zip them. Files that
    storage cannot return are counted and named in the JSON instead of failing
    the whole export (an export is the last chance to recover data)."""
    transfers = list(
        (
            await session.execute(
                select(TransferModel)
                .where(TransferModel.studio_id == studio.id)
                .order_by(TransferModel.created_at, TransferModel.id)
            )
        )
        .scalars()
        .all()
    )
    data = await _collect_export_data(session, studio, transfers)
    data["exported_at"] = _json_value(now)

    buffer = io.BytesIO()
    archived = 0
    skipped = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "studio-export.json", json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        )
        for transfer in transfers:
            if transfer.status == "deleted":
                continue
            if transfer.size_bytes > MAX_ARCHIVED_FILE_BYTES:
                skipped += 1
                archive.writestr(
                    f"files/{transfer.id}/SKIPPED.txt",
                    "Object exceeds the archive size cap; metadata only.\n",
                )
                continue
            try:
                payload = await storage.get_object(transfer.object_key)
            except (BotoCoreError, ClientError):
                skipped += 1
                archive.writestr(
                    f"files/{transfer.id}/MISSING.txt",
                    "Object could not be read from storage; metadata only.\n",
                )
                continue
            archive.writestr(
                f"files/{transfer.id}/{_safe_archive_name(transfer.filename)}", payload
            )
            archived += 1
    return ExportArchive(
        payload=buffer.getvalue(),
        object_key=export_object_key(studio, export_id, now),
        file_count=archived,
        skipped_files=skipped,
    )


def _owned_studio(
    studio: StudioModel | None, principal: Principal, studio_id: uuid.UUID
) -> StudioModel:
    """Owner-only gate shared by every lifecycle route. A studio of another
    tenant answers like a missing one (404, no existence oracle); an existing
    studio of the caller that is not owned answers `403 owner_only`."""
    if studio is None or studio.id != principal.studio_id or studio_id != principal.studio_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "not_found", "message": f"studio {studio_id} not found"},
        )
    if principal.studio_role is not StudioRole.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"error_code": "owner_only"})
    return studio


async def get_owned_studio(
    session: AsyncSession, principal: Principal, studio_id: uuid.UUID
) -> StudioModel:
    studio = await session.get(StudioModel, studio_id)
    return _owned_studio(studio, principal, studio_id)


async def create_export(
    session: AsyncSession,
    storage: StorageProvider,
    settings: Settings,
    principal: Principal,
    studio_id: uuid.UUID,
    now: datetime | None = None,
) -> StudioExportModel:
    """Build and store one archive. Never consults a plan or a quota: the
    export path must keep working on an over-quota, read-only studio."""
    studio = await get_owned_studio(session, principal, studio_id)
    created_at = now or datetime.now(UTC)
    export_id = uuid.uuid4()
    archive = await build_export_archive(session, storage, studio, export_id, created_at)
    logger.info(
        "studio %s export %s built (%s file(s) archived, %s skipped)",
        studio.id,
        export_id,
        archive.file_count,
        archive.skipped_files,
    )
    try:
        await storage.put_object(archive.object_key, archive.payload, "application/zip")
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "storage_unavailable",
                "resource": "studio_export",
                "action": "write",
            },
        ) from exc
    row = StudioExportModel(
        id=export_id,
        studio_id=studio.id,
        requested_by_user_id=principal.user.id,
        object_key=archive.object_key,
        created_at=created_at,
        expires_at=created_at + timedelta(days=settings.export_retention_days),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_export(
    session: AsyncSession, principal: Principal, studio_id: uuid.UUID, export_id: uuid.UUID
) -> StudioExportModel:
    await get_owned_studio(session, principal, studio_id)
    row = await session.scalar(
        select(StudioExportModel).where(
            StudioExportModel.id == export_id,
            StudioExportModel.studio_id == studio_id,
        )
    )
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "export_not_found", "message": "export not found"},
        )
    if row.expires_at <= datetime.now(UTC):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"error_code": "export_expired", "message": "export has expired"},
        )
    return row


def download_url(
    storage: StorageProvider, settings: Settings, export: StudioExportModel
) -> tuple[str, datetime]:
    """Short presigned link (never above 15 minutes, settings-bounded)."""
    ttl = settings.export_url_ttl_seconds
    return storage.presign_get(export.object_key, ttl_seconds=ttl), datetime.now(UTC) + timedelta(
        seconds=ttl
    )
