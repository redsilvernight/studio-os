from __future__ import annotations

from studio_api.db.models.project import ProjectModel
from studio_mcp.tools.claims import (
    studio_claim_resource,
    studio_claim_resources,
    studio_get_resource_claims,
    studio_release_resource,
)
from studio_mcp.tools.events import studio_get_recent_changes

from tests.mcp.conftest import FakeContext


async def test_claim_resource_sets_active_status(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_claim_resource(
        str(project.id), "scenes/level_01.tscn", "file", 600, auth_ctx
    )
    assert result["status"] == "active"


async def test_claim_resource_rejects_unknown_resource_type(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_claim_resource(
        str(project.id), "scenes/level_01.tscn", "bogus", 600, auth_ctx
    )
    assert result["error_code"] == "invalid_argument"


async def test_overlapping_claim_emits_conflict_event(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    await studio_claim_resource(str(project.id), "assets/sprite.png", "file", 600, auth_ctx)
    await studio_claim_resource(str(project.id), "assets/sprite.png", "file", 600, auth_ctx)

    changes = await studio_get_recent_changes(auth_ctx, project_id=str(project.id))
    conflicts = [e for e in changes["events"] if e["event_type"] == "resource.conflict"]
    assert len(conflicts) == 1


async def test_claim_resources_claims_every_path(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    paths = ["a/one.py", "b/two.py", "c/three.py"]
    result = await studio_claim_resources(str(project.id), paths, "file", 600, auth_ctx)
    assert [c["resource_path"] for c in result["claims"]] == paths
    assert all(c["status"] == "active" for c in result["claims"])
    assert result["conflicts"] == []


async def test_claim_resources_rejects_empty_paths(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_claim_resources(str(project.id), [], "file", 600, auth_ctx)
    assert result["error_code"] == "invalid_argument"


async def test_claim_resources_rejects_too_many_paths(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    paths = [f"src/f{i}.py" for i in range(51)]
    result = await studio_claim_resources(str(project.id), paths, "file", 600, auth_ctx)
    assert result["error_code"] == "invalid_argument"


async def test_claim_resources_rejects_unknown_resource_type(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    result = await studio_claim_resources(str(project.id), ["a.py"], "bogus", 600, auth_ctx)
    assert result["error_code"] == "invalid_argument"


async def test_claim_resources_reports_conflict_and_emits_one_event(
    auth_ctx: FakeContext, other_auth_ctx: FakeContext, project: ProjectModel
) -> None:
    await studio_claim_resource(str(project.id), "shared/core.py", "file", 600, other_auth_ctx)

    result = await studio_claim_resources(
        str(project.id), ["shared/core.py", "own/new.py"], "file", 600, auth_ctx
    )
    assert len(result["claims"]) == 2
    assert [c["resource_path"] for c in result["conflicts"]] == ["shared/core.py"]

    changes = await studio_get_recent_changes(auth_ctx, project_id=str(project.id))
    conflicts = [e for e in changes["events"] if e["event_type"] == "resource.conflict"]
    assert len(conflicts) == 1


async def test_claim_resources_idempotency_key_replay_creates_no_duplicate(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    """DEC-0027: a replayed batch call returns the original claims and never
    creates a second set."""
    paths = ["scenes/a.tscn", "scenes/b.tscn"]
    first = await studio_claim_resources(
        str(project.id), paths, "file", 600, auth_ctx, idempotency_key="mcp-batch-1"
    )
    second = await studio_claim_resources(
        str(project.id), paths, "file", 600, auth_ctx, idempotency_key="mcp-batch-1"
    )
    assert [c["id"] for c in second["claims"]] == [c["id"] for c in first["claims"]]

    listing = await studio_get_resource_claims(str(project.id), auth_ctx)
    for path in paths:
        matches = [c for c in listing["claims"] if c["resource_path"] == path]
        assert len(matches) == 1


async def test_get_resource_claims_lists_claim(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_claim_resource(str(project.id), "docs/design.md", "file", 600, auth_ctx)
    result = await studio_get_resource_claims(str(project.id), auth_ctx)
    assert any(c["id"] == created["id"] for c in result["claims"])


async def test_release_resource_marks_released(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    created = await studio_claim_resource(str(project.id), "docs/plan.md", "file", 600, auth_ctx)
    released = await studio_release_resource(created["id"], auth_ctx)
    assert released["status"] == "released"


async def test_release_resource_rejects_unknown_claim(auth_ctx: FakeContext) -> None:
    result = await studio_release_resource("00000000-0000-0000-0000-000000000000", auth_ctx)
    assert result["error_code"] == "error"


async def test_claim_resource_idempotency_key_replay_creates_no_duplicate(
    auth_ctx: FakeContext, project: ProjectModel
) -> None:
    """DEC-0027: a replayed studio_claim_resource call must not create a
    second claim, and must not re-emit resource.conflict on the replay."""
    first = await studio_claim_resource(
        str(project.id),
        "scenes/retry.tscn",
        "file",
        600,
        auth_ctx,
        idempotency_key="mcp-claim-key-1",
    )
    second = await studio_claim_resource(
        str(project.id),
        "scenes/retry.tscn",
        "file",
        600,
        auth_ctx,
        idempotency_key="mcp-claim-key-1",
    )
    assert second["id"] == first["id"]

    listing = await studio_get_resource_claims(str(project.id), auth_ctx)
    matches = [c for c in listing["claims"] if c["resource_path"] == "scenes/retry.tscn"]
    assert len(matches) == 1

    changes = await studio_get_recent_changes(auth_ctx, project_id=str(project.id))
    conflicts = [e for e in changes["events"] if e["event_type"] == "resource.conflict"]
    assert conflicts == []
