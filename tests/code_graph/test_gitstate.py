from __future__ import annotations

from pathlib import Path

from studio_code_graph.gitstate import (
    ChangeSummary,
    files_digest,
    is_git_repository,
    read_repo_files,
    summarize_change,
)

from .support import APP_FILES, commit_all, git, init_repo, write

PY = (".py",)


def read(repo: Path, **kwargs: tuple[str, ...]) -> dict[str, str]:
    result = read_repo_files(repo, PY, **kwargs)
    assert result is not None
    return result.files


def test_lists_tracked_code_files_only(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", {**APP_FILES, "README.md": "docs\n", "data.json": "{}\n"})
    assert sorted(read(repo)) == ["src/main.py", "src/util.py"]


def test_uncommitted_edit_changes_the_digest(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", APP_FILES)
    before = files_digest(read(repo))
    write(repo, "src/util.py", "def other():\n    pass\n")
    assert files_digest(read(repo)) != before
    commit_all(repo)
    committed = files_digest(read(repo))
    write(repo, "src/util.py", "def other():\n    pass\n")
    assert files_digest(read(repo)) == committed


def test_touching_a_file_keeps_the_digest(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", APP_FILES)
    before = files_digest(read(repo))
    write(repo, "src/util.py", APP_FILES["src/util.py"])
    assert files_digest(read(repo)) == before


def test_untracked_and_ignored_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", {**APP_FILES, ".gitignore": "build/\n"})
    write(repo, "src/new.py", "x = 1\n")
    write(repo, "build/gen.py", "y = 1\n")
    assert sorted(read(repo)) == ["src/main.py", "src/new.py", "src/util.py"]


def test_deleted_file_disappears(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", APP_FILES)
    (repo / "src/util.py").unlink()
    assert sorted(read(repo)) == ["src/main.py"]


def test_rename_is_seen_as_rename(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", APP_FILES)
    before = read(repo)
    (repo / "src/util.py").rename(repo / "src/tools.py")
    after = read(repo)
    assert "src/util.py" not in after and "src/tools.py" in after
    assert summarize_change(before, after) == ChangeSummary(renamed=1)


def test_branch_switch_with_identical_code_keeps_the_digest(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", APP_FILES)
    main = files_digest(read(repo))
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "NOTES.md", "notes\n")
    commit_all(repo, "docs")
    assert files_digest(read(repo)) == main


def test_branch_switch_with_different_code_changes_the_digest(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", APP_FILES)
    main = files_digest(read(repo))
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "src/extra.py", "z = 1\n")
    commit_all(repo, "code")
    assert files_digest(read(repo)) != main
    git(repo, "checkout", "-q", "main")
    assert files_digest(read(repo)) == main


def test_include_and_exclude_globs(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", {**APP_FILES, "vendor/lib.py": "v = 1\n"})
    assert "vendor/lib.py" not in read(repo, exclude=("vendor/**",))
    assert list(read(repo, include=("vendor/**",))) == ["vendor/lib.py"]


def test_non_git_directory_is_not_content_addressed(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    write(plain, "a.py", "a = 1\n")
    assert not is_git_repository(plain)
    assert read_repo_files(plain, PY) is None


def test_symlinks_are_not_followed(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "r", APP_FILES)
    outside = tmp_path / "outside.py"
    outside.write_text("secret = 1\n", encoding="utf-8")
    try:
        (repo / "link.py").symlink_to(outside)
    except (OSError, NotImplementedError):
        return
    assert "link.py" not in read(repo)


def test_summarize_change_counts() -> None:
    before = {"a.py": "1", "b.py": "2", "c.py": "3", "d.py": "4"}
    after = {"a.py": "1", "b.py": "9", "e.py": "3", "f.py": "5"}
    summary = summarize_change(before, after)
    assert summary == ChangeSummary(added=1, modified=1, deleted=1, renamed=1)
    assert summary.total == 4 and summary.has_removals
    assert summarize_change(before, before) == ChangeSummary()
    assert not summarize_change({}, {"a.py": "1"}).has_removals
