"""Restore one studio from a `studio.export/v1` archive.

The archive is always restored into a brand-new studio (new id, new slug, the
caller as sole `owner`) and never over an existing one. Every primary key is
regenerated; references to rows that are not part of the archive (machines,
agents, builds, users other than the caller) are cleared rather than guessed.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from studio_api.db.models.decision import DecisionModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.roadmap import RoadmapModel
from studio_api.db.models.studio import StudioModel
from studio_api.db.models.task import TaskModel
from studio_api.db.models.transfer import TransferModel
from studio_api.db.models.user import UserModel
from studio_api.services import studios as studios_service
from studio_api.services.studio_export import EXPORT_SCHEMA, _safe_archive_name
from studio_api.services.transfers import _generate_transfer_code
from studio_api.storage.provider import StorageProvider, safe_object_key

_RESTORED_SUFFIX = " (restauré)"


class RestoreError(ValueError):
    """The archive is unreadable or not a studio export."""


@dataclass(frozen=True)
class RestoreResult:
    studio: StudioModel
    projects: int
    tasks: int
    roadmaps: int
    decisions: int
    files: int
    skipped_files: int


def _coerce(model: type[Any], row: dict[str, Any]) -> dict[str, Any]:
    """Archive JSON values back to column Python types, columns of `model` only."""
    values: dict[str, Any] = {}
    columns = model.__table__.columns
    for key, value in row.items():
        column = columns.get(key)
        if column is None or value is None:
            continue
        try:
            python_type = column.type.python_type
        except NotImplementedError:
            values[key] = value
            continue
        if python_type is uuid.UUID:
            values[key] = uuid.UUID(str(value))
        elif python_type is datetime:
            values[key] = datetime.fromisoformat(str(value))
        elif python_type is bytes:
            values[key] = bytes.fromhex(str(value))
        else:
            values[key] = value
    return values


def _load(payload: bytes) -> tuple[dict[str, Any], zipfile.ZipFile]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
        data = json.loads(archive.read("studio-export.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise RestoreError("archive illisible ou sans studio-export.json") from error
    if data.get("schema") != EXPORT_SCHEMA:
        raise RestoreError(f"schéma d'archive inconnu: {data.get('schema')!r}")
    return data, archive


async def restore_studio_archive(
    session: AsyncSession, storage: StorageProvider, payload: bytes, owner: UserModel
) -> RestoreResult:
    """Create a new studio from `payload`. The caller commits; on failure the
    caller rolls back (objects already written are left under their new keys)."""
    data, archive = _load(payload)
    with archive:
        studio = await studios_service.create_studio(
            session, owner, str(data["studio"]["name"]) + _RESTORED_SUFFIX
        )

        project_ids: dict[str, uuid.UUID] = {}
        project_slugs: dict[str, str] = {}
        for row in data["projects"]:
            new_id = uuid.uuid4()
            project_ids[row["id"]] = new_id
            project_slugs[row["id"]] = row["slug"]
            session.add(
                ProjectModel(**{**_coerce(ProjectModel, row), "id": new_id, "studio_id": studio.id})
            )
        await session.flush()

        task_ids: dict[str, uuid.UUID] = {}
        for row in data["tasks"]:
            new_id = uuid.uuid4()
            task_ids[row["id"]] = new_id
            session.add(
                TaskModel(
                    **{
                        **_coerce(TaskModel, row),
                        "id": new_id,
                        "project_id": project_ids[row["project_id"]],
                        "readable_id": None,
                        "claimed_by_machine_id": None,
                        "claimed_by_agent_id": None,
                    }
                )
            )
        for row in data["roadmaps"]:
            session.add(
                RoadmapModel(
                    **{
                        **_coerce(RoadmapModel, row),
                        "id": uuid.uuid4(),
                        "project_id": project_ids[row["project_id"]],
                        "agent_id": None,
                        "machine_id": None,
                    }
                )
            )
        await session.flush()

        for row in data["decisions"]:
            readable_id = (
                await session.execute(text("SELECT nextval('decisions_readable_id_seq')"))
            ).scalar_one()
            session.add(
                DecisionModel(
                    **{
                        **_coerce(DecisionModel, row),
                        "id": uuid.uuid4(),
                        "studio_id": studio.id,
                        "readable_id": f"DEC-{int(readable_id):04d}",
                        "project_id": project_ids.get(row["project_id"] or ""),
                        "task_id": task_ids.get(row["task_id"] or ""),
                    }
                )
            )
        await session.flush()

        files = skipped = 0
        for row in data["files"]:
            if row["status"] == "deleted":
                continue
            old_id = row["id"]
            member = f"files/{old_id}/{_safe_archive_name(row['filename'])}"
            try:
                content = archive.read(member)
            except KeyError:
                skipped += 1
                continue
            new_id = uuid.uuid4()
            slug = project_slugs.get(row["project_id"] or "", "restored")
            object_key = safe_object_key(slug, new_id, row["filename"])
            await storage.put_object(object_key, content, row["content_type"])
            session.add(
                TransferModel(
                    **{
                        **_coerce(TransferModel, row),
                        "id": new_id,
                        "studio_id": studio.id,
                        "transfer_code": _generate_transfer_code(),
                        "object_key": object_key,
                        "sender_user_id": owner.id,
                        "recipient_user_id": None,
                        "build_id": None,
                        "task_id": task_ids.get(row["task_id"] or ""),
                        "project_id": project_ids.get(row["project_id"] or ""),
                    }
                )
            )
            files += 1
        await session.flush()

    return RestoreResult(
        studio=studio,
        projects=len(project_ids),
        tasks=len(task_ids),
        roadmaps=len(data["roadmaps"]),
        decisions=len(data["decisions"]),
        files=files,
        skipped_files=skipped,
    )


async def count_studio_rows(session: AsyncSession, studio_id: uuid.UUID) -> dict[str, int]:
    """Row counts per exported table, for before/after comparison."""
    project_ids = sa.select(ProjectModel.id).where(ProjectModel.studio_id == studio_id)
    counts = {
        "projects": sa.select(sa.func.count())
        .select_from(ProjectModel)
        .where(ProjectModel.studio_id == studio_id),
        "tasks": sa.select(sa.func.count())
        .select_from(TaskModel)
        .where(TaskModel.project_id.in_(project_ids)),
        "roadmaps": sa.select(sa.func.count())
        .select_from(RoadmapModel)
        .where(RoadmapModel.project_id.in_(project_ids)),
        "decisions": sa.select(sa.func.count())
        .select_from(DecisionModel)
        .where(DecisionModel.studio_id == studio_id),
        "files": sa.select(sa.func.count())
        .select_from(TransferModel)
        .where(TransferModel.studio_id == studio_id, TransferModel.status != "deleted"),
    }
    return {
        name: int((await session.execute(query)).scalar_one()) for name, query in counts.items()
    }
