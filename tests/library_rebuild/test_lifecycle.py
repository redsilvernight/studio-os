from __future__ import annotations

import uuid
from pathlib import Path

import library_import as li
import pytest
from studio_client.publish import PublishError
from studio_client.skill_sync import apply_skill_sync, fetch_skill_projections, plan_skill_sync
from studio_contracts.library import (
    LibraryActivate,
    LibraryKind,
    LibraryResource,
    LibraryResourceCreate,
    LibraryScope,
    LibraryVersionCreate,
)

from .conftest import Actor, World

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _content(text: str) -> dict[str, object]:
    return {"content_schema": "studio.library.skill/v1", "text": text}


async def _sync(actor: Actor, home: Path, project_id: uuid.UUID) -> tuple[int, int, int]:
    skills = await fetch_skill_projections(actor.client, project_id)
    plan = plan_skill_sync(home, skills, include_opencode=True)
    result = apply_skill_sync(plan)
    return len(result.written), len(result.removed), len(plan.retired)


async def _deprecate(actor: Actor, resource: LibraryResource) -> None:
    current = await actor.client.get_library_resource(resource.id)
    await actor.client._request(
        "POST",
        f"/api/v1/library/{resource.id}/deprecate",
        json={"expected_resource_version": current.version},
        extra_headers={"Idempotency-Key": str(uuid.uuid4())},
        idempotent=True,
    )


async def _activate(actor: Actor, resource: LibraryResource, version: int) -> None:
    current = await actor.client.get_library_resource(resource.id)
    await actor.client.activate_library_version(
        resource.id,
        LibraryActivate(version=version, expected_resource_version=current.version),
        idempotency_key=str(uuid.uuid4()),
    )


async def test_update_idempotence_rollback_uninstall(
    world: World, rebuilt: object, tmp_path: Path
) -> None:
    key = f"synthetic-{uuid.uuid4().hex[:6]}"
    admin = world.admin
    resource = await admin.client.create_library_resource(
        LibraryResourceCreate(
            kind=LibraryKind.SKILL,
            stable_key=key,
            scope=LibraryScope.STUDIO,
            title="synthetic",
            content=_content("version one"),
        ),
        idempotency_key=str(uuid.uuid4()),
    )
    await _activate(admin, resource, 1)
    home = tmp_path
    pid = world.outsider_project_id
    skill = home / ".claude" / "skills" / key / "SKILL.md"

    first = await _sync(world.outsider, home, pid)
    assert first[0] > 0 and "version one" in skill.read_text(encoding="utf-8")
    assert await _sync(world.outsider, home, pid) == (0, 0, 0)

    await admin.client.create_library_version(
        resource.id,
        LibraryVersionCreate(title="synthetic", content=_content("version two")),
        idempotency_key=str(uuid.uuid4()),
    )
    await _activate(admin, resource, 2)
    assert (await _sync(world.outsider, home, pid))[0] > 0
    assert "version two" in skill.read_text(encoding="utf-8")
    assert await _sync(world.outsider, home, pid) == (0, 0, 0)

    await _activate(admin, resource, 1)
    await _sync(world.outsider, home, pid)
    assert "version one" in skill.read_text(encoding="utf-8")

    await _deprecate(admin, resource)
    written, removed, retired = await _sync(world.outsider, home, pid)
    assert removed >= 1 and retired >= 1
    assert not skill.exists()
    assert await _sync(world.outsider, home, pid) == (0, 0, 0)


async def test_partial_failure_then_resume(world: World, rebuilt: object) -> None:
    plan = li.load_plan("personal")
    items = plan.items[:4]
    key = f"resume-{uuid.uuid4().hex[:6]}"
    renamed = [
        i.__class__(**{**i.__dict__, "stable_key": f"{key}-{n}"}) for n, i in enumerate(items)
    ]
    broken = renamed[2].__class__(**{**renamed[2].__dict__, "content": {"content_schema": "bad"}})
    flawed = li.LayerPlan("personal", [renamed[0], renamed[1], broken, renamed[3]], [])
    with pytest.raises(Exception):  # noqa: B017
        await li.import_plan(world.owner.client, flawed)
    present = {
        r.stable_key
        for r in await world.owner.client.list_library_resources(scope="user", limit=100)
        if r.stable_key.startswith(key)
    }
    assert present == {f"{key}-0", f"{key}-1"}

    fixed = li.LayerPlan("personal", renamed, [])
    results = await li.import_plan(world.owner.client, fixed)
    assert [r.action for r in results] == ["unchanged", "unchanged", "created", "created"]
    again = await li.import_plan(world.owner.client, fixed)
    assert {r.action for r in again} == {"unchanged"}


async def test_project_layer_refuses_wrong_project_argument(world: World, rebuilt: object) -> None:
    with pytest.raises(PublishError):
        await li.import_plan(world.installer.client, li.load_plan("project"))
    with pytest.raises(PublishError):
        await li.import_plan(world.admin.client, li.load_plan("core"), project_id=world.project_id)


async def test_tampered_package_refused(tmp_path: Path) -> None:
    import json
    import shutil

    root = tmp_path / "repo"
    shutil.copytree(
        li.ROOT / "library",
        root / "library",
        ignore=shutil.ignore_patterns("personal", "project"),
    )
    shutil.copytree(li.ROOT / ".agents", root / ".agents")
    assert len(li.load_plan("core", root).items) == 42
    manifest = json.loads(
        (root / "library" / "packages" / "core" / "manifest.json").read_text("utf-8")
    )
    victim = root / manifest["entries"][0]["files"][0]["path"]
    victim.write_text(victim.read_text("utf-8") + " tampered", encoding="utf-8")
    with pytest.raises(li.ImportErrorReport):
        li.load_plan("core", root)
