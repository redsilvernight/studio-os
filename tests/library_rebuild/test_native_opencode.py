from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from studio_client.context.library import LibraryContextItem
from studio_client.skill_sync import apply_skill_sync, plan_skill_sync

from .conftest import World
from .install_helpers import install

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _opencode(args: list[str], home: Path, cwd: Path) -> str:
    exe = shutil.which("opencode")
    if exe is None:
        pytest.skip("opencode CLI not installed")
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_STATE_HOME": str(home / "state"),
    }
    done = subprocess.run(
        [exe, *args],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-500:]
    return done.stdout


def _json(stdout: str) -> object:
    start = min(i for i in (stdout.find("["), stdout.find("{")) if i >= 0)
    return json.loads(stdout[start:])


async def test_opencode_discovers_installed_skills_and_agents(
    world: World, rebuilt: object, tmp_path: Path
) -> None:
    """OpenCode resolves a real Bun home that env variables cannot redirect, so a same-named
    global skill can shadow a project one. The skill proof therefore uses a unique key."""

    home, project = tmp_path / "home", tmp_path / "project"
    project.mkdir()
    report = await install(world.owner, project, world.project_id)
    key = f"probe-{uuid.uuid4().hex[:6]}"
    files = {"references/a.md": "A", "scripts/deep/run.ps1": "echo probe"}
    probe = LibraryContextItem(
        library_kind="skill",
        stable_key=key,
        version=1,
        version_origin="active",
        scope="studio",
        title="native probe",
        text="probe body",
        content_schema="studio.library.skill/v1",
        files=tuple(files.items()),
    )
    apply_skill_sync(plan_skill_sync(project, [probe]))

    skills = {s["name"]: s for s in _json(_opencode(["debug", "skill"], home, project))}  # type: ignore[union-attr]
    assert key in skills, sorted(skills)
    location = Path(skills[key]["location"]).resolve()
    assert location.is_relative_to(project.resolve())
    for rel, body in files.items():
        assert (location.parent / rel).read_text("utf-8") == body

    agents = _opencode(["agent", "list"], home, project)
    assert report.agents["opencode"]
    for agent in report.agents["opencode"]:
        assert agent in agents, agent
