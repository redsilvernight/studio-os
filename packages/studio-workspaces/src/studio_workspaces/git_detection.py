from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum


class GitStatus(StrEnum):
    VALID = "valid"
    NOT_A_REPO = "not_a_repo"
    INVALID_REPO = "invalid_repo"
    GIT_ABSENT = "git_absent"
    INACCESSIBLE = "inaccessible"


@dataclass(frozen=True)
class GitRepoInfo:
    status: GitStatus
    probe_path: str
    repo_root: str | None = None
    branch: str | None = None
    detached: bool = False
    commit: str | None = None
    remote: str | None = None


Runner = Callable[..., "CompletedLike"]


@dataclass(frozen=True)
class CompletedLike:
    returncode: int
    stdout: str
    stderr: str


def _default_runner(cmd: Sequence[str], timeout: float) -> CompletedLike:
    try:
        completed = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(str(exc)) from exc
    return CompletedLike(completed.returncode, completed.stdout, completed.stderr)


def _git_text(result: CompletedLike) -> str | None:
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _find_git() -> str | None:
    """`git` from an absolute `PATH` entry only: never the working directory, which
    Windows would search first (a repository could shadow git with its own binary)."""
    cwd = os.path.normcase(os.path.abspath(os.getcwd()))
    suffixes = [""]
    if os.name == "nt":
        suffixes = [
            ext.lower() for ext in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if ext
        ]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue
        if os.path.normcase(os.path.abspath(entry)) == cwd:
            continue
        for suffix in suffixes:
            candidate = os.path.join(entry, "git" + suffix)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def detect_git(
    path: str,
    *,
    runner: Runner = _default_runner,
    timeout: float = 10.0,
    git_exe: str | None = None,
) -> GitRepoInfo:
    try:
        if not os.path.exists(path):
            return GitRepoInfo(GitStatus.INACCESSIBLE, path)
        if not os.access(path, os.R_OK | os.X_OK):
            return GitRepoInfo(GitStatus.INACCESSIBLE, path)
    except OSError:
        return GitRepoInfo(GitStatus.INACCESSIBLE, path)
    exe = git_exe if git_exe is not None else _find_git()
    if exe is None:
        return GitRepoInfo(GitStatus.GIT_ABSENT, path)
    try:
        toplevel = runner(
            [exe, "-C", path, "rev-parse", "--show-toplevel"],
            timeout,
        )
    except (OSError, TimeoutError):
        return GitRepoInfo(GitStatus.INVALID_REPO, path)
    root = _git_text(toplevel)
    if root is None:
        dot_git = os.path.join(path, ".git")
        try:
            broken = os.path.exists(dot_git)
        except OSError:
            return GitRepoInfo(GitStatus.INACCESSIBLE, path)
        if broken:
            return GitRepoInfo(GitStatus.INVALID_REPO, path)
        return GitRepoInfo(GitStatus.NOT_A_REPO, path)
    try:
        head_ref = runner([exe, "-C", path, "rev-parse", "--abbrev-ref", "HEAD"], timeout)
        head_sha = runner([exe, "-C", path, "rev-parse", "HEAD"], timeout)
        origin = runner([exe, "-C", path, "remote", "get-url", "origin"], timeout)
    except (OSError, TimeoutError):
        return GitRepoInfo(GitStatus.INVALID_REPO, path, repo_root=root)
    ref = _git_text(head_ref)
    sha = _git_text(head_sha)
    if ref is None or sha is None:
        return GitRepoInfo(GitStatus.INVALID_REPO, path, repo_root=root)
    detached = ref == "HEAD"
    return GitRepoInfo(
        status=GitStatus.VALID,
        probe_path=path,
        repo_root=root,
        branch=None if detached else ref,
        detached=detached,
        commit=sha,
        remote=_git_text(origin),
    )
