from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from studio_api.db.models.machine import MachineModel
from studio_api.db.models.project import ProjectModel
from studio_api.services import projects as projects_service
from studio_api.services.authz import load_principal
from studio_mcp.tools.vault import studio_vault_read, studio_vault_search, studio_vault_write

from tests.mcp.conftest import FakeContext


def _slug() -> str:
    return f"note-{uuid.uuid4().hex[:8]}"


async def _write(
    ctx: FakeContext,
    project: ProjectModel,
    *,
    slug: str | None = None,
    title: str = "A vault note",
    body: str = "Some content.",
    **kwargs: object,
) -> dict:
    return await studio_vault_write(
        "project",
        slug or _slug(),
        title,
        body,
        ctx,
        project_id=str(project.id),
        **kwargs,
    )


async def test_vault_search_returns_the_written_note(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    slug = _slug()
    await _write(auth_ctx, project, slug=slug, title="Pick a transport", body="SSE over WebSocket.")

    result = await studio_vault_search(auth_ctx, q="transport", project_id=str(project.id))

    assert "error_code" not in result
    assert any(item["note"]["slug"] == slug for item in result["items"])
    assert "body" not in result["items"][0]["note"]


async def test_vault_search_without_criteria_is_rejected(auth_ctx: FakeContext) -> None:
    result = await studio_vault_search(auth_ctx)
    assert result["error_code"] == "missing_search_criteria"


async def test_vault_search_rejects_out_of_contract_bounds(auth_ctx: FakeContext) -> None:
    result = await studio_vault_search(auth_ctx, q="vault", limit=999)
    assert result["error_code"] == "invalid_argument"

    unknown_type = await studio_vault_search(auth_ctx, q="vault", note_type=["nope"])
    assert unknown_type["error_code"] == "invalid_argument"


async def test_vault_write_creates_a_proposed_agent_note(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await _write(auth_ctx, project, summary="Short.", note_type="convention")

    assert created["status"] == "proposed"
    assert created["author_type"] == "agent"
    assert created["version"] == 1
    assert created["readable_id"] is None
    assert "body" not in created

    read = await studio_vault_read(created["id"], auth_ctx)
    assert read["note_type"] == "convention"
    assert read["summary"] == "Short."
    assert read["body_truncated"] is False


async def test_vault_write_idempotency_key_replay_allocates_no_second_note(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    """DEC-0027: a replayed creation returns the original note."""
    slug = _slug()
    first = await _write(auth_ctx, project, slug=slug, idempotency_key="mcp-vault-key-1")
    second = await _write(auth_ctx, project, slug=slug, idempotency_key="mcp-vault-key-1")

    assert second["id"] == first["id"]


async def test_vault_write_twice_on_the_same_slug_conflicts(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    slug = _slug()
    await _write(auth_ctx, project, slug=slug)
    conflict = await _write(auth_ctx, project, slug=slug)
    assert conflict["error_code"] == "vault_slug_conflict"


async def test_vault_write_update_bumps_the_version(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await _write(auth_ctx, project, body="v1")

    updated = await studio_vault_write(
        "project",
        created["slug"],
        "A vault note",
        "v2",
        auth_ctx,
        note_id=created["id"],
        expected_version=created["version"],
        change_summary="Rewrite the body.",
    )

    assert updated["version"] == 2
    assert updated["status"] == "proposed"
    assert updated["author_type"] == "agent"

    read = await studio_vault_read(created["id"], auth_ctx)
    assert read["body"] == "v2"
    assert read["version"] == 2


async def test_vault_write_update_with_a_stale_version_conflicts(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await _write(auth_ctx, project, body="v1")
    await studio_vault_write(
        "project",
        created["slug"],
        "A vault note",
        "v2",
        auth_ctx,
        note_id=created["id"],
        expected_version=1,
    )

    stale = await studio_vault_write(
        "project",
        created["slug"],
        "A vault note",
        "v3",
        auth_ctx,
        note_id=created["id"],
        expected_version=1,
    )

    assert stale["error_code"] == "version_conflict"
    assert stale["server_version"] == 2


async def test_vault_write_update_requires_the_expected_version(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await _write(auth_ctx, project)
    result = await studio_vault_write(
        "project",
        created["slug"],
        "A vault note",
        "v2",
        auth_ctx,
        note_id=created["id"],
    )
    assert result["error_code"] == "invalid_argument"


async def test_vault_read_truncates_a_long_body(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await _write(auth_ctx, project, body="x" * 500)

    result = await studio_vault_read(created["id"], auth_ctx, max_chars=100)

    assert result["body"] == "x" * 100
    assert result["body_truncated"] is True
    assert result["version"] == 1


async def test_vault_write_refuses_a_secret_in_the_body(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await _write(auth_ctx, project, body=f"ghp_{'A1b2' * 9}")

    assert result["error_code"] == "secret_detected"
    assert {"field": "body", "pattern": "github_token"} in result["details"]


async def test_vault_write_rejects_a_bad_slug(auth_ctx: FakeContext, project: ProjectModel) -> None:
    result = await studio_vault_write(
        "project", "Not A Slug", "t", "b", auth_ctx, project_id=str(project.id)
    )
    assert result["error_code"] == "invalid_argument"


@pytest.mark.isolation
async def test_vault_read_of_a_foreign_project_note_is_forbidden(
    db_session: AsyncSession,
    auth_ctx: FakeContext,
    other_auth_ctx: FakeContext,
    machine: tuple[MachineModel, str],
) -> None:
    """`isolation`: real project memberships, so the other developer is a
    genuine non-member of the note's project (DEC-0103)."""
    member = await load_principal(db_session, machine[0])
    owned = await projects_service.create_project(
        db_session, f"vault-{uuid.uuid4().hex[:8]}", "Owned", None, creator=member.user
    )
    created = await studio_vault_write(
        "project", "members-only", "Members only", "b", auth_ctx, project_id=str(owned.id)
    )
    assert "error_code" not in created

    read = await studio_vault_read(created["id"], other_auth_ctx)
    assert read["error_code"] == "forbidden"
    assert read["resource"] == "project"

    searched = await studio_vault_search(other_auth_ctx, q="Members", project_id=str(owned.id))
    assert searched["error_code"] == "forbidden"

    written = await studio_vault_write(
        "project", _slug(), "t", "b", other_auth_ctx, project_id=str(owned.id)
    )
    assert written["error_code"] == "forbidden"
