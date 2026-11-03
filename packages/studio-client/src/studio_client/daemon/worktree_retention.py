"""Retention of the task worktrees a launch creates: preview what nothing
else claims, then remove it under a confirmation bound to that preview.

`launch_prepare.ensure_task_worktree` creates one `<repo>-wt-<id8>` worktree
per accepted launch, and nothing ever reclaims one, so a long-running daemon
accumulates directories and `task/<id8>-<slug>` branches. This module is the
only place allowed to remove one, and it is split in two on purpose:
`plan_cleanup` reads git and writes nothing at all, `apply_cleanup` re-reads
the same state and refuses unless the caller's confirmation still matches it.
Verdicts and reasons are closed tokens so the daemon and the CLI never parse
prose, and a worktree that is not provably removable is kept, never forced.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from studio_client.daemon.launch_prepare import (
    WORKTREE_SUFFIX,
    GitRunner,
    _parse_worktrees,
    _same_path,
    run_git,
)

logger = logging.getLogger(__name__)

VERDICT_CANDIDATE = "candidate"
VERDICT_EXCLUDED = "excluded"

REASON_ACTIVE_SESSION = "active_session"
REASON_DIRTY = "dirty"
REASON_LOCKED = "locked"
REASON_MAIN_WORKTREE = "main_worktree"
REASON_UNMANAGED = "unmanaged"
REASON_UNPUSHED = "unpushed"

# Every reason an exclusion can carry, in the order they are always reported.
REASONS = (
    REASON_ACTIVE_SESSION,
    REASON_DIRTY,
    REASON_LOCKED,
    REASON_MAIN_WORKTREE,
    REASON_UNMANAGED,
    REASON_UNPUSHED,
)

_TASK_KEY = re.compile(r"^[0-9a-f]{8}$")


class RetentionError(RuntimeError):
    """A cleanup cannot be planned or applied. `reason` is a closed token
    (`git_unavailable`, `digest_mismatch`, `plan_stale`) the caller maps to a
    closed decision; the message is machine-facing and carries no secret."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CleanupEntry:
    """One worktree as git reports it, with the verdict retention gives it.
    `task_id_prefix` is the 8-hex prefix the path encodes, which is all the
    worktree name proves — the full task id never reaches the filesystem."""

    path: Path
    branch: str | None
    task_id_prefix: str | None
    verdict: str
    reasons: tuple[str, ...] = ()

    @property
    def removable(self) -> bool:
        return self.verdict == VERDICT_CANDIDATE


@dataclass(frozen=True)
class CleanupPlan:
    """A read-only verdict for every worktree of the repository. `digest`
    fingerprints it, so a confirmation proves the caller approved *this* plan
    and not one recomputed later over a different state."""

    repo_root: Path
    entries: tuple[CleanupEntry, ...]
    active_task_ids: tuple[UUID, ...]
    digest: str

    @property
    def candidates(self) -> tuple[CleanupEntry, ...]:
        return tuple(entry for entry in self.entries if entry.removable)


@dataclass(frozen=True)
class CleanupResult:
    """What an applied plan actually did. `refused` names the entries git
    itself declined (a worktree that became dirty, a branch that became
    unmerged) — never a deletion this module forced."""

    removed: tuple[Path, ...]
    deleted_branches: tuple[str, ...]
    refused: tuple[str, ...]


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _digest(entries: tuple[CleanupEntry, ...]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(
            f"{_normalized(entry.path)}|{entry.task_id_prefix or ''}|{entry.branch or ''}|"
            f"{entry.verdict}|{','.join(entry.reasons)}\n".encode()
        )
    return digest.hexdigest()


def _locked_paths(porcelain: str) -> set[str]:
    """Paths git reports as locked. `_parse_worktrees` keeps only the path and
    the branch of each block, and a locked worktree is never prunable, so the
    flag is read from the very same porcelain text."""
    locked: set[str] = set()
    current: str | None = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree ") :].strip()
        elif line.startswith("locked") and current is not None:
            locked.add(_normalized(Path(current)))
    return locked


def _managed_task_key(path: Path, root: Path) -> str | None:
    """The task a worktree belongs to, or None when the path is not the one
    `launch_prepare.worktree_path` would have created for this repository — an
    unmanaged worktree is reported and then never touched."""
    if not _same_path(path.parent, root.parent):
        return None
    prefix = f"{root.name}{WORKTREE_SUFFIX}"
    if not path.name.startswith(prefix):
        return None
    suffix = path.name[len(prefix) :]
    return suffix if _TASK_KEY.match(suffix) else None


def _is_dirty(runner: GitRunner, path: Path) -> bool:
    """Uncommitted or untracked content means work only this directory holds.
    A status git cannot run is never read as clean: the worktree is kept."""
    status = runner(["status", "--porcelain"], path)
    if status.returncode != 0:
        logger.warning("worktree retention: unreadable status, keeping the worktree")
        return True
    return bool(status.stdout.strip())


def _local_branches(runner: GitRunner, root: Path) -> list[str]:
    listed = runner(["for-each-ref", "--format=%(refname:short)", "refs/heads/"], root)
    if listed.returncode != 0:
        return []
    return [line.strip() for line in listed.stdout.splitlines() if line.strip()]


def _count(runner: GitRunner, args: list[str], cwd: Path) -> int | None:
    counted = runner(["rev-list", "--count", *args], cwd)
    if counted.returncode != 0:
        return None
    try:
        return int(counted.stdout.strip())
    except ValueError:
        return None


def _is_unpushed(runner: GitRunner, root: Path, path: Path, branch: str | None) -> bool:
    """A commit that no remote and no other local branch holds would be lost
    with the worktree. With an upstream, that is simply what the upstream
    lacks; without one, only the commits unique to this branch count — a task
    branch that never went past its base carries nothing to push."""
    rev = branch or "HEAD"
    upstream = runner(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{rev}@{{upstream}}"], path
    )
    if upstream.returncode == 0 and upstream.stdout.strip():
        ahead = _count(runner, [f"{upstream.stdout.strip()}..{rev}"], path)
    else:
        others = [other for other in _local_branches(runner, root) if other != branch]
        exclude: list[str] = []
        for other in others:
            exclude.extend(["--not", other])
        ahead = _count(runner, [rev, "--not", "--remotes", *exclude], root)
    if ahead is None:
        logger.warning("worktree retention: unreadable commit range, keeping the worktree")
        return True
    return ahead > 0


def _excluded(
    path: Path, branch: str | None, task_id_prefix: str | None, reasons: Iterable[str]
) -> CleanupEntry:
    return CleanupEntry(
        path=path,
        branch=branch,
        task_id_prefix=task_id_prefix,
        verdict=VERDICT_EXCLUDED,
        reasons=tuple(reason for reason in REASONS if reason in set(reasons)),
    )


def _classify(
    root: Path,
    path: Path,
    branch: str | None,
    *,
    is_main: bool,
    locked: bool,
    active: frozenset[str],
    runner: GitRunner,
) -> CleanupEntry:
    """The git worktree list always opens with the main worktree, which no
    cleanup may ever touch, whatever its name."""
    if is_main:
        return _excluded(path, branch, _managed_task_key(path, root), (REASON_MAIN_WORKTREE,))
    task_id_prefix = _managed_task_key(path, root)
    if task_id_prefix is None:
        return _excluded(path, branch, None, (REASON_UNMANAGED,))
    reasons = [
        REASON_ACTIVE_SESSION if task_id_prefix in active else "",
        REASON_LOCKED if locked else "",
        REASON_DIRTY if _is_dirty(runner, path) else "",
        REASON_UNPUSHED if _is_unpushed(runner, root, path, branch) else "",
    ]
    found = tuple(reason for reason in reasons if reason)
    if found:
        return _excluded(path, branch, task_id_prefix, found)
    return CleanupEntry(path, branch, task_id_prefix, VERDICT_CANDIDATE)


def plan_cleanup(
    repo_root: Path | str,
    *,
    active_task_ids: Iterable[UUID] = (),
    runner: GitRunner = run_git,
) -> CleanupPlan:
    """Read every worktree of the repository and decide what may be removed.
    Nothing is written and nothing is deleted: the verdict of each worktree
    comes from git itself, and a worktree that cannot be proven clean, pushed,
    unlocked and unclaimed is excluded with the reasons that prove it."""
    root = Path(repo_root).resolve()
    listed = runner(["worktree", "list", "--porcelain"], root)
    if listed.returncode != 0:
        raise RetentionError("git_unavailable", listed.stderr.strip() or "git worktree list failed")
    locked = _locked_paths(listed.stdout)
    task_ids = tuple(sorted({UUID(str(task_id)) for task_id in active_task_ids}))
    active = frozenset(task_id.hex[:8] for task_id in task_ids)
    entries = tuple(
        sorted(
            (
                _classify(
                    root,
                    entry.path,
                    entry.branch,
                    is_main=index == 0,
                    locked=_normalized(entry.path) in locked,
                    active=active,
                    runner=runner,
                )
                for index, entry in enumerate(_parse_worktrees(listed.stdout))
            ),
            key=lambda item: _normalized(item.path),
        )
    )
    return CleanupPlan(
        repo_root=root, entries=entries, active_task_ids=task_ids, digest=_digest(entries)
    )


def apply_cleanup(
    repo_root: Path | str,
    plan: CleanupPlan,
    *,
    confirm_digest: str,
    runner: GitRunner = run_git,
) -> CleanupResult:
    """Remove the worktrees the plan judged removable. The confirmation must
    be the digest of that very plan, and the plan is recomputed from git right
    here: a stale approval is refused instead of applied to a state nobody
    previewed. `git worktree remove` runs without `--force` and the branch
    goes with `git branch -d`, so a worktree that became dirty or unmerged
    since the preview survives."""
    if confirm_digest != plan.digest:
        raise RetentionError("digest_mismatch", "the confirmation does not match the plan")
    fresh = plan_cleanup(repo_root, active_task_ids=plan.active_task_ids, runner=runner)
    if fresh.digest != plan.digest:
        raise RetentionError("plan_stale", "the worktrees changed since the plan was computed")

    root = fresh.repo_root
    removed: list[Path] = []
    deleted: list[str] = []
    refused: list[str] = []
    for entry in fresh.candidates:
        outcome = runner(["worktree", "remove", str(entry.path)], root)
        if outcome.returncode != 0:
            refused.append(
                f"{entry.path}: {outcome.stderr.strip() or 'git worktree remove failed'}"
            )
            continue
        removed.append(entry.path)
        if entry.branch is None:
            continue
        pruned = runner(["branch", "-d", entry.branch], root)
        if pruned.returncode != 0:
            refused.append(f"{entry.branch}: {pruned.stderr.strip() or 'git branch -d failed'}")
        else:
            deleted.append(entry.branch)
    return CleanupResult(tuple(removed), tuple(deleted), tuple(refused))
