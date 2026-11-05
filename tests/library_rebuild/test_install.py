from __future__ import annotations

from pathlib import Path

import library_import as li
import pytest
from studio_client.skill_sync import SkillSyncConflictError

from .conftest import World
from .install_helpers import RUNTIMES, install

pytestmark = pytest.mark.asyncio(loop_scope="session")

CORE_HOOKS = {"git-guard", "session-start", "stop-check"}
PERSONAL_HOOKS = 5


def _keys(layer: str, kind: str) -> set[str]:
    return {i.stable_key for i in li.load_plan(layer).items if i.kind == kind}


def _private() -> tuple[set[str], set[str]]:
    skills = _keys("personal", "skill") - _keys("core", "skill") - _keys("project", "skill")
    agents = _keys("personal", "agent") - _keys("core", "agent")
    return skills, agents


def _files(home: Path) -> dict[str, str]:
    return {
        p.relative_to(home).as_posix(): p.read_text(encoding="utf-8", errors="replace")
        for p in home.rglob("*")
        if p.is_file()
    }


def _agent_files(home: Path, runtime: str) -> set[str]:
    prefix = {"claude-code": ".claude/agents/", "codex": ".codex/agents/", "opencode": ".opencode/"}
    return {
        Path(name).stem
        for name in _files(home)
        if name.startswith(prefix[runtime])
        and "/agents/" in f"/{name}"
        or (runtime == "opencode" and name.startswith(".opencode/agent"))
    }


async def test_core_only_vanilla_user(world: World, rebuilt: object, tmp_path: Path) -> None:
    report = await install(world.outsider, tmp_path, world.outsider_project_id)
    assert set(report.skills) == _keys("core", "skill")
    assert not report.errors
    for runtime in RUNTIMES:
        assert set(report.agents[runtime]) == _keys("core", "agent")
        assert any(w.endswith("no_runtime_target") for w in report.warnings[runtime])
    assert set(report.hooks_needing_consent) == CORE_HOOKS
    assert report.hooks == []
    for name in (".claude/skills", ".agents/skills", ".config/opencode/skills"):
        assert len([p for p in (tmp_path / name).iterdir()]) == len(_keys("core", "skill"))

    private_skills, private_agents = _private()
    blob = "\n".join(_files(tmp_path).values())
    names = "\n".join(_files(tmp_path))
    for key in private_skills | private_agents:
        assert key not in names
    plan = li.load_plan("personal")
    for item in plan.items:
        if item.kind == "skill" and item.stable_key in private_skills:
            assert str(item.content["text"])[:80] not in blob


async def test_hook_consent_and_runtime_support(
    world: World, rebuilt: object, tmp_path: Path
) -> None:
    report = await install(
        world.outsider, tmp_path, world.outsider_project_id, consent_hooks=tuple(CORE_HOOKS)
    )
    assert set(report.hooks) == CORE_HOOKS
    assert (tmp_path / ".claude" / "settings.json").is_file()
    assert not [n for n in _files(tmp_path) if n.startswith(".codex/") and "hook" in n.lower()]


async def test_core_plus_personal_authorized_owner(
    world: World, rebuilt: object, tmp_path: Path
) -> None:
    report = await install(world.owner, tmp_path, None)
    private_skills, private_agents = _private()
    assert private_skills <= set(report.skills)
    for runtime in RUNTIMES:
        assert private_agents <= set(report.agents[runtime])
    other = tmp_path.parent / (tmp_path.name + "-vanilla")
    other.mkdir()
    await install(world.outsider, other, world.outsider_project_id)
    shadowed = _keys("personal", "skill") & _keys("core", "skill")
    assert shadowed
    for key in shadowed:
        rel = f".claude/skills/{key}/SKILL.md"
        assert (tmp_path / rel).read_text(encoding="utf-8") != (other / rel).read_text(
            encoding="utf-8"
        )


async def test_project_install_scoped_and_preserves_local(
    world: World, rebuilt: object, tmp_path: Path
) -> None:
    local = tmp_path / ".claude" / "skills" / "my-local" / "SKILL.md"
    local.parent.mkdir(parents=True)
    local.write_text("mine", encoding="utf-8")
    local_agent = tmp_path / ".claude" / "agents" / "my-agent.md"
    local_agent.parent.mkdir(parents=True)
    local_agent.write_text("mine", encoding="utf-8")
    report = await install(world.installer, tmp_path, world.project_id)
    project_only = _keys("project", "skill") - _keys("core", "skill")
    assert project_only
    assert not (project_only & set(report.skills))
    assert not any((tmp_path / ".claude" / "skills" / k).exists() for k in project_only)
    project_agents = _keys("project", "agent") - _keys("core", "agent")
    assert project_agents
    for runtime in RUNTIMES:
        assert project_agents <= set(report.agents[runtime])
    assert local.read_text(encoding="utf-8") == "mine"
    assert local_agent.read_text(encoding="utf-8") == "mine"

    vanilla = tmp_path.parent / (tmp_path.name + "-v")
    vanilla.mkdir()
    out = await install(world.outsider, vanilla, world.outsider_project_id)
    for runtime in RUNTIMES:
        assert not (project_agents & set(out.agents[runtime]))
    assert not any((vanilla / ".claude" / "agents" / f"{k}.md").exists() for k in project_agents)


async def test_locally_modified_skill_is_not_overwritten(
    world: World, rebuilt: object, tmp_path: Path
) -> None:
    await install(world.outsider, tmp_path, world.outsider_project_id)
    target = tmp_path / ".claude" / "skills" / "next" / "SKILL.md"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\nlocal edit", encoding="utf-8")
    from studio_client.skill_sync import apply_skill_sync, fetch_skill_projections, plan_skill_sync

    skills = await fetch_skill_projections(world.outsider.client, world.outsider_project_id)
    plan = plan_skill_sync(tmp_path, skills, include_opencode=True)
    assert plan.locally_modified
    with pytest.raises(SkillSyncConflictError):
        apply_skill_sync(plan)
    assert target.read_text(encoding="utf-8").endswith("local edit")
