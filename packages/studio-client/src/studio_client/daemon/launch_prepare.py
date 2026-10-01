"""Preparation of an accepted remote launch (AIB R3): the daemon-owned
worktree for the task, then the machine-local AI configuration inside it.

The executor decides *whether* to honour a launch (`launch_policy`) and pulls
it (`launch_puller`); this module only prepares the ground before the harness
runs. Nothing here launches a process, talks to the network on its own, or
writes outside the task worktree: the worktree is created from the project's
watched repository using the `studio-git-flow` convention
(`<repo>-wt-<id8>` on `task/<id8>-<slug>`), and the AI configuration is
applied through injected configurators so a failure is reported with a closed
step name rather than a raw stack trace.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from studio_client.bootstrap import (
    load_manifest,
    manifest_path,
)
from studio_client.bootstrap import (
    sync as bootstrap_sync,
)

logger = logging.getLogger(__name__)

WORKTREE_SUFFIX = "-wt-"
DEFAULT_BASE_BRANCH = "dev"
SLUG_MAX_LENGTH = 40
SLUG_FALLBACK = "task"
STEP_BOOTSTRAP = "bootstrap"
STEP_IA_CONFIG = "ia_config"


class PreparationError(RuntimeError):
    """A launch cannot be prepared. `step` names the failed stage so the
    executor reports the closed `preparation_failed` reason; the message is
    machine-facing and never carries a secret."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


GitRunner = Callable[[Sequence[str], Path], GitResult]


def run_git(args: Sequence[str], cwd: Path) -> GitResult:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return GitResult(completed.returncode, completed.stdout, completed.stderr)


def task_slug(title: str | None, *, max_length: int = SLUG_MAX_LENGTH) -> str:
    """Kebab-case slug from a task title, ascii and bounded, so it is safe in
    a branch name. Falls back to `task` when nothing usable remains."""
    ascii_title = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug[:max_length].strip("-") or SLUG_FALLBACK


def worktree_path(repo_root: Path | str, task_id: UUID) -> Path:
    root = Path(repo_root)
    return root.parent / f"{root.name}{WORKTREE_SUFFIX}{task_id.hex[:8]}"


def task_branch_name(task_id: UUID, slug: str) -> str:
    return f"task/{task_id.hex[:8]}-{slug}"


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    created: bool
    base_ref: str | None = None


@dataclass(frozen=True)
class _WorktreeEntry:
    path: Path
    branch: str | None


def _parse_worktrees(porcelain: str) -> list[_WorktreeEntry]:
    entries: list[_WorktreeEntry] = []
    path: Path | None = None
    branch: str | None = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            if path is not None:
                entries.append(_WorktreeEntry(path, branch))
            path = Path(line[len("worktree ") :].strip())
            branch = None
        elif line.startswith("branch "):
            ref = line[len("branch ") :].strip()
            branch = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ref
    if path is not None:
        entries.append(_WorktreeEntry(path, branch))
    return entries


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _verify(runner: GitRunner, root: Path, ref: str) -> bool:
    return runner(["rev-parse", "--verify", "--quiet", ref], root).returncode == 0


def _has_origin(runner: GitRunner, root: Path) -> bool:
    result = runner(["remote"], root)
    return result.returncode == 0 and "origin" in result.stdout.split()


def ensure_task_worktree(
    repo_root: Path | str,
    task_id: UUID,
    slug: str,
    *,
    base: str = DEFAULT_BASE_BRANCH,
    fetch: bool = True,
    runner: GitRunner = run_git,
) -> Worktree:
    """Create or reuse the task worktree `<repo>-wt-<id8>` on
    `task/<id8>-<slug>`, based on the up-to-date `origin/<base>` when
    available. An existing worktree of the same branch is reused whatever its
    path (a harness-managed worktree is never renamed nor recreated); an
    occupied path or an unknown directory is refused rather than clobbered."""
    root = Path(repo_root).resolve()
    branch = task_branch_name(task_id, slug)
    target = worktree_path(root, task_id)

    listed = runner(["worktree", "list", "--porcelain"], root)
    if listed.returncode != 0:
        raise PreparationError("worktree", listed.stderr.strip() or "git worktree list failed")
    entries = _parse_worktrees(listed.stdout)
    for entry in entries:
        if entry.branch == branch:
            return Worktree(entry.path, branch, created=False)
    for entry in entries:
        if _same_path(entry.path, target):
            raise PreparationError(
                "worktree",
                f"{target} already holds worktree of {entry.branch or 'a detached head'}",
            )
    if target.exists():
        raise PreparationError("worktree", f"{target} exists but is not a managed worktree")

    if fetch and _has_origin(runner, root):
        fetched = runner(["fetch", "origin"], root)
        if fetched.returncode != 0:
            logger.warning("launch prepare: git fetch origin failed; using the local base")

    base_ref = f"origin/{base}" if _verify(runner, root, f"origin/{base}") else base
    if not _verify(runner, root, base_ref):
        raise PreparationError("worktree", f"base branch {base!r} not found")

    if _verify(runner, root, f"refs/heads/{branch}"):
        added = runner(["worktree", "add", str(target), branch], root)
    else:
        added = runner(["worktree", "add", "-b", branch, str(target), base_ref], root)
    if added.returncode != 0:
        raise PreparationError("worktree", added.stderr.strip() or "git worktree add failed")
    return Worktree(target, branch, created=True, base_ref=base_ref)


@dataclass(frozen=True)
class PreparationRequest:
    repo_root: Path
    project_id: UUID
    task_id: UUID
    task_title: str | None
    harness_id: str
    base_branch: str = DEFAULT_BASE_BRANCH


@dataclass(frozen=True)
class PreparedLaunch:
    worktree: Worktree
    steps: tuple[str, ...]


IaConfigurator = Callable[[Path, PreparationRequest], Sequence[str]]


def bootstrap_configurator(root: Path, request: PreparationRequest) -> Sequence[str]:
    """Apply the repo-local AI generator (P3) inside the worktree: managed
    projections and `AGENTS.md`/`CLAUDE.md` blocks from the committed
    `.agents/bootstrap.json` manifest. A repository without a manifest is a
    normal case (not yet bootstrapped) and is skipped, never forced."""
    if not manifest_path(root).is_file():
        logger.info("launch prepare: no bootstrap manifest, skipping")
        return ()
    manifest = load_manifest(root)
    _report, written = bootstrap_sync(root, manifest)
    logger.info("launch prepare: bootstrap wrote %d file(s)", len(written))
    return (STEP_BOOTSTRAP,)


class LaunchPreparer:
    """Prepares the worktree then runs each injected AI configurator in order.
    Default configuration is the repo-local bootstrap; skills sync and
    `harness.apply` are supplied by the daemon wiring (they need the API
    client and the workspace registry). Any failure becomes a
    `PreparationError`, so the executor never sees a partial success."""

    def __init__(
        self,
        *,
        configurators: Sequence[IaConfigurator] | None = None,
        base_branch: str = DEFAULT_BASE_BRANCH,
        fetch: bool = True,
        runner: GitRunner = run_git,
    ) -> None:
        self._configurators: tuple[IaConfigurator, ...] = (
            tuple(configurators) if configurators is not None else (bootstrap_configurator,)
        )
        self._base_branch = base_branch
        self._fetch = fetch
        self._runner = runner

    def prepare(self, request: PreparationRequest) -> PreparedLaunch:
        worktree = ensure_task_worktree(
            request.repo_root,
            request.task_id,
            task_slug(request.task_title),
            base=request.base_branch or self._base_branch,
            fetch=self._fetch,
            runner=self._runner,
        )
        steps: list[str] = []
        for configure in self._configurators:
            try:
                steps.extend(configure(worktree.path, request))
            except PreparationError:
                raise
            except Exception as exc:
                raise PreparationError(STEP_IA_CONFIG, str(exc)) from exc
        return PreparedLaunch(worktree, tuple(steps))
