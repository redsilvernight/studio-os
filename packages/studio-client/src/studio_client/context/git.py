from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitSnapshot:
    """Bounded Git context for a Context Package (DEC-0057)."""

    branch: str
    head: str
    dirty: bool
    recent_commits: list[str]


async def read_git_snapshot(
    repo_path: Path | None, *, commits_limit: int = 10
) -> GitSnapshot | None:
    """Read a bounded Git snapshot; return `None` when no repo is configured
    or Git is unavailable. Never raises — failures degrade to `None`."""
    if repo_path is None:
        return None
    try:
        return await _run_git_snapshot(repo_path, commits_limit=commits_limit)
    except (TimeoutError, OSError, subprocess.SubprocessError):
        return None


async def _run_git_snapshot(repo_path: Path, *, commits_limit: int) -> GitSnapshot | None:
    cwd = str(repo_path)
    branch = await _git_stdout(["git", "branch", "--show-current"], cwd)
    if branch is None:
        return None
    head = await _git_stdout(["git", "rev-parse", "HEAD"], cwd) or ""
    status = await _git_stdout(["git", "status", "--porcelain"], cwd)
    dirty = bool(status and status.strip())
    log = await _git_stdout(
        ["git", "log", f"-{commits_limit}", "--oneline", "--no-decorate"],
        cwd,
    )
    recent_commits = [line.strip() for line in (log or "").splitlines() if line.strip()]
    return GitSnapshot(
        branch=branch.strip() or "HEAD",
        head=head.strip(),
        dirty=dirty,
        recent_commits=recent_commits[:commits_limit],
    )


async def _git_stdout(cmd: list[str], cwd: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode != 0:
            return None
        return stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return None
