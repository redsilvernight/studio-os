from __future__ import annotations

import os
from pathlib import Path

import pytest
from studio_workspaces.path_safety import check_p5_glob, check_readable, classify_local_path


def test_drive_root_is_refused() -> None:
    for raw in ("C:\\", "C:/", "D:", "D:\\", "/"):
        assert not classify_local_path(raw).ok, raw


def test_unc_is_refused() -> None:
    for raw in ("\\\\srv\\share", "//srv/share", "\\\\?\\C:\\Work"):
        assert not classify_local_path(raw).ok, raw


def test_relative_and_drive_relative_are_refused() -> None:
    for raw in ("demo", "Work/demo", "./demo", "D:relative", "d:folder/file"):
        assert not classify_local_path(raw).ok, raw


def test_parent_traversal_is_refused() -> None:
    for raw in ("C:/Work/../Secret", "C:\\Work\\..\\Secret", "/home/user/../root"):
        assert not classify_local_path(raw).ok, raw


def test_dot_segments_are_refused() -> None:
    assert not classify_local_path("C:/Work/./demo").ok
    assert not classify_local_path("/home/user/./demo").ok


def test_canonical_absolute_is_accepted() -> None:
    verdict = classify_local_path("C:/Work/demo-game")
    assert verdict.ok and verdict.normalized is not None


def test_disappeared_path_is_reported() -> None:
    verdict = check_readable("C:/Work/definitely-not-here-9f3c")
    assert not verdict.ok
    assert "exist" in verdict.reason


def test_file_is_not_a_workspace_root(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("data", encoding="utf-8")
    verdict = check_readable(str(target))
    assert not verdict.ok
    assert "directory" in verdict.reason


def test_symlink_root_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setattr(os.path, "islink", lambda _p: True)
    verdict = check_readable(str(real))
    assert not verdict.ok
    assert "symlink" in verdict.reason or "junction" in verdict.reason


def test_junction_root_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setattr(os.path, "islink", lambda _p: False)
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is None:
        return
    monkeypatch.setattr(os.path, "isjunction", lambda _p: True)
    verdict = check_readable(str(real))
    assert not verdict.ok
    assert "junction" in verdict.reason


def test_permission_denied_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "locked"
    target.mkdir()
    real_access = os.access
    monkeypatch.setattr(
        os, "access", lambda p, m: False if str(p) == str(target) else real_access(p, m)
    )
    verdict = check_readable(str(target))
    assert not verdict.ok
    assert "permission" in verdict.reason


def test_plain_globs_are_accepted() -> None:
    assert check_p5_glob("**/*.md").ok
    assert check_p5_glob("docs/@(a|b).md").ok
    assert check_p5_glob("**/!(*.tmp)").ok


def test_extglob_spanning_directories_is_refused() -> None:
    assert not check_p5_glob("@(a/b|c)").ok
    assert not check_p5_glob("@(a|../b)").ok
    assert not check_p5_glob("+(x|y/z)").ok


def test_extglob_with_dotdot_is_refused() -> None:
    assert not check_p5_glob("@(a|..)").ok


def test_glob_dot_segment_is_refused() -> None:
    assert not check_p5_glob("a/./b").ok


def test_p1_glob_violations_stay_rejected() -> None:
    assert not check_p5_glob("../escape").ok
    assert not check_p5_glob("C:/absolute").ok
    assert not check_p5_glob("a{b,c}").ok


def test_windows_env_forms_are_not_absolute() -> None:
    assert not classify_local_path("%USERPROFILE%/game").ok
    assert not classify_local_path("~/game").ok


def test_existing_tmp_dir_is_readable(tmp_path: Path) -> None:
    verdict = check_readable(str(tmp_path))
    assert verdict.ok or "permission" in verdict.reason
    assert os.path.isdir(str(tmp_path))
