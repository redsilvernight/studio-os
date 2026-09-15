from __future__ import annotations

import base64
import hashlib

from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.transfers import (
    studio_create_transfer_metadata,
    studio_get_transfer,
    studio_get_transfers,
    studio_request_transfer_download,
)

from tests.mcp.conftest import FakeContext

_DUMMY_CONTENT_MD5 = base64.b64encode(hashlib.md5(b"report contents").digest()).decode()


async def test_create_transfer_metadata_returns_upload_url(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_create_transfer_metadata(
        "report.bin",
        "application/octet-stream",
        1024,
        "temporary",
        auth_ctx,
        project_id=str(project.id),
        content_md5=_DUMMY_CONTENT_MD5,
    )
    assert result["status"] == "created"
    assert result["upload"]["multipart"] is False
    assert result["upload"]["upload_url"]


async def test_create_transfer_metadata_rejects_missing_content_md5(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    """DEC-0025: the single-PUT path (small file) requires content_md5 even
    via MCP — studio_create_transfer_metadata must not silently skip the
    same validation the HTTP router enforces."""
    result = await studio_create_transfer_metadata(
        "report.bin",
        "application/octet-stream",
        1024,
        "temporary",
        auth_ctx,
        project_id=str(project.id),
    )
    assert result["error_code"] == "missing_content_md5"


async def test_create_transfer_metadata_rejects_unknown_category(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_create_transfer_metadata(
        "report.bin",
        "application/octet-stream",
        1024,
        "bogus",
        auth_ctx,
        project_id=str(project.id),
    )
    assert result["error_code"] == "invalid_argument"


async def test_create_transfer_metadata_rejects_over_quota_size(auth_ctx: FakeContext) -> None:
    result = await studio_create_transfer_metadata(
        "huge.bin", "application/octet-stream", 10**15, "temporary", auth_ctx
    )
    assert result["error_code"] == "transfer_too_large"


async def test_get_transfers_lists_created_transfer(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_transfer_metadata(
        "report.bin",
        "application/octet-stream",
        1024,
        "temporary",
        auth_ctx,
        project_id=str(project.id),
        content_md5=_DUMMY_CONTENT_MD5,
    )
    result = await studio_get_transfers(auth_ctx, project_id=str(project.id))
    assert any(t["id"] == created["id"] for t in result["transfers"])


async def test_get_transfer_rejects_unknown_id(auth_ctx: FakeContext) -> None:
    result = await studio_get_transfer("00000000-0000-0000-0000-000000000000", auth_ctx)
    assert result["error_code"] == "error"


async def test_request_transfer_download_returns_presigned_url(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_transfer_metadata(
        "report.bin",
        "application/octet-stream",
        1024,
        "temporary",
        auth_ctx,
        project_id=str(project.id),
        content_md5=_DUMMY_CONTENT_MD5,
    )
    result = await studio_request_transfer_download(created["id"], auth_ctx)
    assert result["download_url"]
    assert result["transfer_id"] == created["id"]
