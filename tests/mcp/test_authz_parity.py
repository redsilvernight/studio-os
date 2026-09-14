from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.agent import AgentModel
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.db.models.transfer import TransferModel
from studio_api.services import provisioning as provisioning_service
from studio_mcp.tools.ai_work import studio_log_ai_work
from studio_mcp.tools.claims import studio_claim_resource, studio_release_resource
from studio_mcp.tools.decisions import studio_add_decision
from studio_mcp.tools.sessions import studio_end_session, studio_start_session
from studio_mcp.tools.tasks import studio_claim_task, studio_create_task, studio_release_task
from studio_mcp.tools.transfers import (
    studio_create_transfer_metadata,
    studio_get_transfer,
    studio_get_transfers,
    studio_request_transfer_download,
)

from tests.mcp.conftest import FakeContext

# Same authorization gates as tests/api/test_authz.py, exercised through the
# MCP tool layer instead of HTTP — proves parity (TECH/04 Autorisation,
# DEC-0036): both call the same `studio_api.services.*` functions with a
# `Principal`, so the outcome must match regardless of transport.


async def test_readonly_cannot_create_task_via_mcp(
    readonly_auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_create_task(str(project.id), "t", readonly_auth_ctx)
    assert result["error_code"] == "forbidden"


async def test_readonly_cannot_claim_resource_via_mcp(
    readonly_auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_claim_resource(
        str(project.id), "src/foo.py", "file", 60, readonly_auth_ctx
    )
    assert result["error_code"] == "forbidden"


async def test_readonly_cannot_add_decision_via_mcp(readonly_auth_ctx: FakeContext) -> None:
    result = await studio_add_decision("t", "b", readonly_auth_ctx)
    assert result["error_code"] == "forbidden"


async def test_task_release_by_non_owning_machine_forbidden_via_mcp(
    auth_ctx: FakeContext, other_auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_create_task(str(project.id), "t", auth_ctx)
    await studio_claim_task(created["id"], auth_ctx)

    forbidden = await studio_release_task(created["id"], other_auth_ctx)
    assert forbidden["error_code"] == "forbidden"

    allowed = await studio_release_task(created["id"], auth_ctx)
    assert allowed.get("error_code") is None
    assert allowed["claimed_by_machine_id"] is None


async def test_claim_release_by_non_owning_machine_forbidden_via_mcp(
    auth_ctx: FakeContext, other_auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_claim_resource(str(project.id), "src/bar.py", "file", 60, auth_ctx)

    forbidden = await studio_release_resource(created["id"], other_auth_ctx)
    assert forbidden["error_code"] == "forbidden"

    allowed = await studio_release_resource(created["id"], auth_ctx)
    assert allowed.get("error_code") is None
    assert allowed["status"] == "released"


async def test_session_end_by_non_owning_machine_forbidden_via_mcp(
    auth_ctx: FakeContext, other_auth_ctx: FakeContext, project: ProjectModel
) -> None:
    task = await studio_create_task(str(project.id), "t", auth_ctx)
    session = await studio_start_session(task["id"], auth_ctx)

    forbidden = await studio_end_session(session["id"], other_auth_ctx)
    assert forbidden["error_code"] == "forbidden"

    allowed = await studio_end_session(session["id"], auth_ctx)
    assert allowed.get("error_code") is None
    assert allowed["ended_at"] is not None


async def test_ai_work_patch_by_non_owning_machine_forbidden_via_mcp(
    auth_ctx: FakeContext, other_auth_ctx: FakeContext, project: ProjectModel, agent: AgentModel
) -> None:
    agent_id = str(agent.id)
    created = await studio_log_ai_work(str(project.id), "s", agent_id, auth_ctx)

    forbidden = await studio_log_ai_work(
        str(project.id), "hijacked", agent_id, other_auth_ctx, ai_work_id=created["id"]
    )
    assert forbidden["error_code"] == "forbidden"

    allowed = await studio_log_ai_work(
        str(project.id), "updated", agent_id, auth_ctx, ai_work_id=created["id"]
    )
    assert allowed.get("error_code") is None
    assert allowed["summary"] == "updated"


async def test_readonly_cannot_create_transfer_via_mcp(readonly_auth_ctx: FakeContext) -> None:
    result = await studio_create_transfer_metadata(
        "f.bin", "application/octet-stream", 10, "temporary", readonly_auth_ctx
    )
    assert result["error_code"] == "forbidden"


async def test_broadcast_transfer_readable_by_any_user_via_mcp(
    auth_ctx: FakeContext, other_auth_ctx: FakeContext
) -> None:
    """`studio_create_transfer_metadata` has no `recipient_user_id` parameter
    — every MCP-created transfer is a broadcast (`recipient_user_id=None`),
    per `TECH/07_MCP_CONTRACT.md`'s existing tool surface — so this is the
    one transfer-visibility case actually reachable via MCP; a scoped
    sender/recipient/third-party matrix is exercised over HTTP instead
    (tests/api/test_authz.py), where `POST /transfers` accepts it."""
    content_md5 = base64.b64encode(hashlib.md5(b"payload").digest()).decode()
    created = await studio_create_transfer_metadata(
        "build.zip", "application/zip", 10, "build", auth_ctx, content_md5=content_md5
    )

    readable = await studio_get_transfer(created["id"], other_auth_ctx)
    assert readable.get("error_code") is None

    listing = await studio_get_transfers(other_auth_ctx)
    assert any(t["id"] == created["id"] for t in listing["transfers"])


async def test_transfer_download_url_forbidden_for_third_party_via_mcp(
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    machine: tuple[MachineModel, str],
    db_session: AsyncSession,
) -> None:
    """`studio_create_transfer_metadata` cannot set `recipient_user_id`, so a
    scoped (non-broadcast) transfer is inserted directly here to exercise
    the sender/recipient/third-party matrix — same DB row shape
    `services.transfers.create_transfer` produces, just without going
    through the tool that doesn't expose the field."""
    recipient = await provisioning_service.create_user(
        db_session, "Recipient", f"{uuid.uuid4()}@example.test", "developer"
    )
    transfer_id = uuid.uuid4()
    db_session.add(
        TransferModel(
            id=transfer_id,
            transfer_code=f"TRF-{transfer_id.hex[:8].upper()}",
            sender_user_id=machine[0].owner_user_id,
            recipient_user_id=recipient.id,
            category="temporary",
            filename="f.bin",
            object_key=f"studio/unscoped/test/{transfer_id}/f.bin",
            content_type="application/octet-stream",
            size_bytes=10,
            status="created",
            created_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    forbidden = await studio_request_transfer_download(str(transfer_id), other_auth_ctx)
    assert forbidden["error_code"] == "forbidden"

    allowed = await studio_request_transfer_download(str(transfer_id), auth_ctx)
    assert allowed.get("error_code") is None
    assert allowed["download_url"]
