"""PC5 dead-code guard: vulture passes on the repository and fails on a planted dead function."""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest

from scripts import deadcode_check

REPO = deadcode_check.REPO
DEAD = "\n\ndef pc5_planted_dead_function() -> int:\n    return 42\n"


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    shutil.copy2(REPO / "pyproject.toml", tmp_path / "pyproject.toml")
    paths = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["vulture"][
        "paths"
    ]
    for rel in paths:
        src = REPO / rel
        dst = tmp_path / rel
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return tmp_path


def test_guard_passes_on_repository() -> None:
    assert deadcode_check.check_python(REPO)


def test_guard_passes_on_untouched_copy(repo_copy: Path) -> None:
    assert deadcode_check.check_python(repo_copy)


def test_guard_fails_on_planted_dead_function(
    repo_copy: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    module = repo_copy / "services/mcp/src/studio_mcp/errors.py"
    module.write_text(module.read_text(encoding="utf-8") + DEAD, encoding="utf-8")

    assert not deadcode_check.check_python(repo_copy)
    assert "unused function 'pc5_planted_dead_function'" in capfd.readouterr().out
