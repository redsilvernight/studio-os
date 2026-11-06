from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import text
from studio_client.context.library import LibraryContextItem, LibraryContextProvider
from studio_client.skill_sync import apply_skill_sync, plan_skill_sync, plan_skill_uninstall

from .conftest import Actor, World

pytestmark = pytest.mark.asyncio(loop_scope="session")

MULTI = {"studio-task": "studio", "graphify": "project", "workstation-setup": "user"}


async def _skills(actor: Actor, world: World, scope: str) -> dict[str, LibraryContextItem]:
    fetched = await LibraryContextProvider(actor.client).fetch(
        world.project_id, limit=100, kinds=("skill",)
    )
    return {i.stable_key: i for i in fetched.items if i.scope == scope}


def _sync(home: Path, items: dict[str, LibraryContextItem]) -> None:
    plan = plan_skill_sync(home, list(items.values()), include_opencode=True, allow_project=True)
    apply_skill_sync(plan)


def _digest(home: Path, keys: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for base in (".agents/skills", ".claude/skills", ".config/opencode/skills"):
        for key in keys:
            root = home / base / key
            for path in sorted(root.rglob("*")) if root.exists() else []:
                if path.is_file():
                    rel = path.relative_to(home).as_posix()
                    out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


async def _db_state(world: World) -> tuple[object, ...]:
    async with world.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "select (select count(*) from library_resources), "
                "(select count(*) from library_resource_versions), "
                "(select count(*) from library_project_locks), "
                "(select count(*) from library_resources where status <> 'active')"
            )
        )
        return tuple(rows.one())


async def test_core_project_personal_install_uninstall_reinstall(
    world: World, rebuilt: object, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    core = await _skills(world.owner, world, "studio")
    project = await _skills(world.owner, world, "project")
    personal = await _skills(world.owner, world, "user")
    assert {"studio-task"} <= core.keys()
    assert "graphify" in project and "workstation-setup" in personal
    personal_only = set(personal) - set(core)
    core_only = set(core) - set(personal)
    state_before = await _db_state(world)
    locks_before = await world.owner.client.list_library_locks(project_id=world.project_id)

    everything = {**core, **project, **personal}
    _sync(home, everything)
    for key, items in (
        ("studio-task", core),
        ("graphify", project),
        ("workstation-setup", personal),
    ):
        for rel, body in items[key].files:
            for base in (".agents", ".claude", ".config/opencode"):
                assert (home / base / "skills" / key / rel).read_text("utf-8") == body

    unmanaged_skill = home / ".claude/skills/my-own/SKILL.md"
    unmanaged_skill.parent.mkdir(parents=True)
    unmanaged_skill.write_text("local", encoding="utf-8")
    unmanaged_aux = home / ".claude/skills/graphify/local-notes.txt"
    unmanaged_aux.write_text("notes", encoding="utf-8")

    core_digest = _digest(home, core_only)
    apply_skill_sync(plan_skill_uninstall(home, sorted(personal)))
    skills_dir = home / ".claude/skills"
    assert not [k for k in personal_only if (skills_dir / k).exists()]
    assert not (home / ".claude/skills/workstation-setup/SKILL.md").exists()
    assert _digest(home, core_only) == core_digest
    assert unmanaged_skill.read_text("utf-8") == "local"
    assert unmanaged_aux.read_text("utf-8") == "notes"

    _sync(home, everything)
    for rel, body in personal["workstation-setup"].files:
        assert (home / ".claude/skills/workstation-setup" / rel).read_text("utf-8") == body

    project_digest = {
        k: v for k, v in _digest(home, {"graphify"}).items() if not k.endswith("local-notes.txt")
    }
    apply_skill_sync(plan_skill_uninstall(home, ["graphify"]))
    assert not (home / ".claude/skills/graphify/SKILL.md").exists()
    assert not (home / ".claude/skills/graphify/references").exists()
    assert unmanaged_aux.read_text("utf-8") == "notes"
    assert _digest(home, core_only) == core_digest
    assert project_digest and unmanaged_skill.read_text("utf-8") == "local"

    _sync(home, everything)
    unmanaged_aux.unlink()
    assert _digest(home, {"graphify"}) == project_digest

    assert await _db_state(world) == state_before
    locks = await world.owner.client.list_library_locks(project_id=world.project_id)
    assert [lock.id for lock in locks] == [lock.id for lock in locks_before]
