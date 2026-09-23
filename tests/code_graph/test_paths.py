from __future__ import annotations

from pathlib import Path

import pytest
from studio_code_graph.paths import (
    PathEscapeError,
    confine,
    glob_match,
    is_selected,
    normalize_repo_relative,
    same_location,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("src/a.py", "src/a.py"),
        ("src\\a.py", "src/a.py"),
        ("./src//a.py", "src/a.py"),
        ("", None),
        ("   ", None),
        (".", None),
        ("../outside.py", None),
        ("src/../../outside.py", None),
        ("src/a#b.py", None),
    ],
)
def test_normalize_relative(tmp_path: Path, raw: str, expected: str | None) -> None:
    assert normalize_repo_relative(raw, tmp_path) == expected


def test_normalize_absolute_inside_and_outside(tmp_path: Path) -> None:
    inside = tmp_path / "src" / "a.py"
    inside.parent.mkdir()
    inside.write_text("", encoding="utf-8")
    assert normalize_repo_relative(str(inside), tmp_path) == "src/a.py"
    outside = tmp_path.parent / "elsewhere.py"
    assert normalize_repo_relative(str(outside), tmp_path) is None
    assert normalize_repo_relative("/etc/passwd", tmp_path) is None


def test_confine_accepts_children_and_root(tmp_path: Path) -> None:
    assert confine(tmp_path, "a", "b") == tmp_path.resolve() / "a" / "b"
    assert confine(tmp_path) == tmp_path.resolve()


@pytest.mark.parametrize("parts", [("..",), ("a", "..", "..", "x"), ("../sibling",)])
def test_confine_refuses_escapes(tmp_path: Path, parts: tuple[str, ...]) -> None:
    with pytest.raises(PathEscapeError):
        confine(tmp_path, *parts)


def test_confine_refuses_symlink_escape(tmp_path: Path) -> None:
    target = tmp_path.parent / "target_dir"
    target.mkdir(exist_ok=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(PathEscapeError):
        confine(tmp_path, "link", "x")


def test_same_location_ignores_spelling(tmp_path: Path) -> None:
    assert same_location(tmp_path / "a" / "..", tmp_path)
    assert not same_location(tmp_path, tmp_path / "other")


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("*.py", "a.py", True),
        ("*.py", "src/a.py", False),
        ("**/*.py", "a.py", True),
        ("**/*.py", "src/deep/a.py", True),
        ("src/**", "src/a/b.py", True),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/a/b.py", False),
        ("a?.py", "ab.py", True),
        ("a?.py", "a/.py", False),
        ("a.py", "aXpy", False),
    ],
)
def test_glob_match(pattern: str, path: str, expected: bool) -> None:
    assert glob_match(pattern, path) is expected


def test_is_selected_exclude_wins_over_include() -> None:
    assert is_selected("src/a.py", (), ())
    assert is_selected("src/a.py", ("src/**",), ())
    assert not is_selected("src/a.py", ("lib/**",), ())
    assert not is_selected("src/a.py", ("src/**",), ("**/a.py",))
