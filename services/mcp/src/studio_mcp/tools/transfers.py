from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.transfer import TransferModel
from studio_api.services import projects as projects_service
from studio_api.services import transfers as transfers_service
from studio_api.services.authz import Principal
from studio_api.settings import get_settings
from studio_api.storage.provider import get_storage
from studio_contracts.transfers import TransferCategory, TransferCreate

from studio_mcp.errors import run_tool
from studio_mcp.util import parse_uuid


def _compact_transfer(transfer: TransferModel) -> dict[str, Any]:
    return {
        "id": str(transfer.id),
        "transfer_code": transfer.transfer_code,
        "project_id": str(transfer.project_id) if transfer.project_id else None,
        "task_id": str(transfer.task_id) if transfer.task_id else None,
        "category": transfer.category,
        "filename": transfer.filename,
        "content_type": transfer.content_type,
        "size_bytes": transfer.size_bytes,
        "status": transfer.status,
        "expires_at": transfer.expires_at.isoformat() if transfer.expires_at else None,
        "created_at": transfer.created_at.isoformat(),
    }


async def studio_get_transfers(ctx: Context, project_id: str | None = None) -> dict[str, Any]:
    """List transfers (metadata only), optionally filtered by project_id (UUID string)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        transfers = await transfers_service.list_transfers(
            session, principal, project_id=parsed_project_id
        )
        return {"transfers": [_compact_transfer(t) for t in transfers]}

    return await run_tool(ctx, _handler)


async def studio_get_transfer(transfer_id: str, ctx: Context) -> dict[str, Any]:
    """Get one transfer's metadata by id (UUID string)."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(transfer_id, "transfer_id")
        if isinstance(parsed, dict):
            return parsed
        transfer = await transfers_service.get_transfer(session, principal, parsed)
        return _compact_transfer(transfer)

    return await run_tool(ctx, _handler)


async def studio_create_transfer_metadata(
    filename: str,
    content_type: str,
    size_bytes: int,
    category: str,
    ctx: Context,
    project_id: str | None = None,
    task_id: str | None = None,
    content_md5: str | None = None,
) -> dict[str, Any]:
    """Create a transfer record and return metadata plus a pre-signed upload
    URL — never the file bytes themselves. The client uploads directly to
    MinIO/S3 with the returned URL (.claude/rules/storage-transfers.md).
    `content_md5` (base64 RFC 1864 MD5 of the whole file) is required for a
    small file (single-PUT path, DEC-0025) — the call fails with
    `missing_content_md5` otherwise. Not needed for a large file, which
    returns multipart part URLs instead."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        try:
            parsed_category = TransferCategory(category)
        except ValueError:
            return {"error_code": "invalid_argument", "message": f"unknown category: {category!r}"}
        parsed_project_id = None
        if project_id is not None:
            parsed = parse_uuid(project_id, "project_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_project_id = parsed
        parsed_task_id = None
        if task_id is not None:
            parsed = parse_uuid(task_id, "task_id")
            if isinstance(parsed, dict):
                return parsed
            parsed_task_id = parsed

        transfers_service.authorize_create(principal, parsed_project_id)
        if parsed_project_id is None:
            project_slug = "unscoped"
        else:
            project = await projects_service.get_project(session, principal, parsed_project_id)
            project_slug = project.slug

        settings = get_settings()
        transfer = await transfers_service.create_transfer(
            session,
            principal,
            settings,
            TransferCreate(
                project_id=parsed_project_id,
                task_id=parsed_task_id,
                category=parsed_category,
                filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
            ),
            project_slug,
        )
        storage = get_storage()
        upload = await transfers_service.initiate_upload(
            session, principal, storage, settings, transfer, content_md5
        )
        return {**_compact_transfer(transfer), "upload": upload.model_dump(mode="json")}

    return await run_tool(ctx, _handler)


async def studio_request_transfer_download(transfer_id: str, ctx: Context) -> dict[str, Any]:
    """Get a short-lived pre-signed download URL for a transfer — never the
    file bytes through this tool."""

    async def _handler(session: AsyncSession, principal: Principal) -> dict[str, Any]:
        parsed = parse_uuid(transfer_id, "transfer_id")
        if isinstance(parsed, dict):
            return parsed
        transfer = await transfers_service.get_transfer(session, principal, parsed)
        settings = get_settings()
        storage = get_storage()
        url, expires_at = transfers_service.get_download_url(storage, settings, transfer)
        return {
            "transfer_id": str(transfer.id),
            "download_url": url,
            "expires_at": expires_at.isoformat(),
        }

    return await run_tool(ctx, _handler)
