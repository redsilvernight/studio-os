from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from studio_client.context.library import LibraryContextItem, LibraryContextProvider
from studio_client.skill_sync import apply_skill_sync, plan_skill_sync

from .conftest import World
from .install_helpers import RUNTIMES, install

pytestmark = pytest.mark.asyncio(loop_scope="session")

NATIVE_DIR_ENV = "STUDIO_NATIVE_DIR"
WITNESS_KEY = "zz-witness-2f"
WITNESS_TOKEN = os.environ.get("STUDIO_NATIVE_TOKEN", "AMBRE-7431-QUASAR")
RULE_TOKEN = os.environ.get("STUDIO_NATIVE_RULE_TOKEN", "CUIVRE-2958-ZEPHYR")


async def test_prepare_native_projects(world: World, rebuilt: object) -> None:
    """Install the real Library projections into one throwaway project per runtime."""
    root = os.environ.get(NATIVE_DIR_ENV)
    if not root:
        pytest.skip(f"{NATIVE_DIR_ENV} not set")
    witness = LibraryContextItem(
        library_kind="skill",
        stable_key=WITNESS_KEY,
        version=1,
        version_origin="active",
        scope="studio",
        title="native witness",
        text=(
            f"---\nname: {WITNESS_KEY}\ndescription: Returns the validation witness value. "
            f"Use when asked for the witness value of {WITNESS_KEY}.\n---\n"
            f"The witness value is {WITNESS_TOKEN}.\n"
        ),
        content_schema="studio.library.skill/v1",
        files=(),
    )
    for runtime in RUNTIMES:
        project = Path(root) / runtime
        rules = project / ".agents" / "rules"
        rules.mkdir(parents=True, exist_ok=True)
        (rules / "witness.md").write_text(
            "---\nname: witness\nstable_key: witness\napplies_to: []\n---\n\n"
            f"# Witness rule\n\nThe rule witness value is {RULE_TOKEN}.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        await install(world.owner, project, world.project_id)
        fetched = await LibraryContextProvider(world.owner.client).fetch(
            world.project_id, limit=100, kinds=("skill",)
        )
        items = [*fetched.items, witness]
        apply_skill_sync(plan_skill_sync(project, items, include_opencode=True, allow_project=True))
        done = subprocess.run(
            [str(Path(sys.executable).with_name("studio-client.exe")), "rules", "sync"],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr[-500:] or done.stdout[-500:]
