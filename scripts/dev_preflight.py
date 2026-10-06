"""Read-only preflight: is local ``dev`` identical to ``origin/dev``?

An audit or a release gate that runs on a stale (or unpublished) ``dev`` validates
a state nobody else has. This module compares the local branch to its remote
counterpart and says so loudly. It never mutates the worktree: no checkout,
reset, merge, pull or rebase. The only write it may perform is the standard
``git fetch`` (remote-tracking ref + FETCH_HEAD), and only when allowed.

Statuses (``PreflightResult.status``):

  aligned    local == remote, remote freshly verified          -> promotable, exit 0
  behind     local is missing remote commits (right > 0)       -> exit 1
  ahead      local has unpushed commits (left > 0)             -> exit 1
  diverged   both sides have commits the other lacks           -> exit 1
  offline    remote state could not be verified (fetch denied/failed, or
             --offline). The comparison against the *cached* remote-tracking ref
             is reported for information only; the result is NOT promotable -> exit 3
  error      missing local branch / remote ref / not a git repo -> exit 2

``left`` counts commits only in local, ``right`` commits only in the remote
(``git rev-list --left-right --count local...remote``).

Every result carries the exact SHAs and the remote reference, so reports and
gates can record them (``record()``).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_DIVERGED = 1
EXIT_ERROR = 2
EXIT_OFFLINE = 3

OFFLINE_ENV = "STUDIO_PREFLIGHT_OFFLINE"
FETCH_TIMEOUT_S = 30


@dataclass
class PreflightResult:
    status: str
    promotable: bool
    remote_verified: bool
    branch: str
    remote_ref: str
    local_sha: str | None
    remote_sha: str | None
    head_sha: str | None
    left: int | None
    right: int | None
    fetch: str  # "ok" | "skipped (...)" | "failed (...)"
    message: str

    @property
    def exit_code(self) -> int:
        return {
            "aligned": EXIT_OK,
            "offline": EXIT_OFFLINE,
            "error": EXIT_ERROR,
        }.get(self.status, EXIT_DIVERGED)


def _git(root: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    return subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def _rev(root: Path, ref: str) -> str | None:
    proc = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def _short(sha: str | None) -> str:
    return sha[:12] if sha else "?"


def _fetch(root: Path, remote: str, branch: str) -> str:
    try:
        proc = _git(root, "fetch", "--quiet", "--no-tags", remote, branch, timeout=FETCH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"failed (timeout after {FETCH_TIMEOUT_S}s)"
    if proc.returncode != 0:
        reason = (proc.stderr.strip().splitlines() or ["git fetch failed"])[-1]
        return f"failed ({reason})"
    return "ok"


def run_preflight(
    root: Path,
    *,
    branch: str = "dev",
    remote: str = "origin",
    allow_fetch: bool = True,
) -> PreflightResult:
    """Compare ``branch`` to ``remote/branch``. Never touches the worktree."""
    remote_ref = f"{remote}/{branch}"
    local_ref = f"refs/heads/{branch}"

    def result(status: str, message: str, **kw: Any) -> PreflightResult:
        base: dict[str, Any] = {
            "status": status,
            "promotable": False,
            "remote_verified": False,
            "branch": branch,
            "remote_ref": remote_ref,
            "local_sha": None,
            "remote_sha": None,
            "head_sha": None,
            "left": None,
            "right": None,
            "fetch": "skipped",
            "message": message,
        }
        base.update(kw)
        return PreflightResult(**base)

    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0:
        return result("error", f"not a git repository: {root}")

    head_sha = _rev(root, "HEAD")
    local_sha = _rev(root, local_ref)
    if local_sha is None:
        return result("error", f"local branch '{branch}' not found", head_sha=head_sha)

    if os.environ.get(OFFLINE_ENV):
        allow_fetch = False
        fetch = f"skipped ({OFFLINE_ENV} set)"
    elif not allow_fetch:
        fetch = "skipped (fetch not allowed)"
    else:
        fetch = _fetch(root, remote, branch)
    verified = fetch == "ok"

    remote_sha = _rev(root, f"refs/remotes/{remote_ref}")
    common = {
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "head_sha": head_sha,
        "fetch": fetch,
    }
    if remote_sha is None:
        status = "offline" if not verified else "error"
        return result(
            status,
            f"remote ref {remote_ref} not found locally (fetch: {fetch}); "
            "remote state cannot be verified -- NOT promotable",
            **common,
        )

    counts = _git(root, "rev-list", "--left-right", "--count", f"{local_sha}...{remote_sha}")
    if counts.returncode != 0:
        return result("error", f"rev-list failed: {counts.stderr.strip()}", **common)
    left, right = (int(n) for n in counts.stdout.split())
    common.update(left=left, right=right)

    if left == 0 and right == 0:
        shape, detail = "aligned", f"{branch} == {remote_ref} at {_short(local_sha)}"
    elif left == 0:
        shape = "behind"
        detail = (
            f"{branch} is BEHIND {remote_ref}: left={left} right={right}; "
            f"target {remote_ref} = {remote_sha}. Update {branch} explicitly "
            "(e.g. git merge --ff-only) -- the preflight does not do it"
        )
    elif right == 0:
        shape = "ahead"
        detail = (
            f"{branch} is AHEAD of {remote_ref}: left={left} right={right}; "
            f"target {remote_ref} = {remote_sha}; unpushed local commits are not a published state"
        )
    else:
        shape = "diverged"
        detail = (
            f"{branch} DIVERGED from {remote_ref}: left={left} right={right}; "
            f"target {remote_ref} = {remote_sha}"
        )

    if not verified:
        return result(
            "offline",
            f"remote state NOT verified (fetch: {fetch}); cached {detail}. "
            "Result is NOT promotable",
            **common,
        )
    return result(
        shape,
        detail,
        promotable=shape == "aligned",
        remote_verified=True,
        **common,
    )


def record(result: PreflightResult) -> dict[str, Any]:
    """Stable dict to embed in any audit/gate report (exact SHAs + remote ref)."""
    return asdict(result)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--branch", default="dev")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--offline", action="store_true", help="never fetch (result not promotable)")
    ap.add_argument("--json", action="store_true", help="print the record as JSON")
    args = ap.parse_args(argv)

    res = run_preflight(
        args.root, branch=args.branch, remote=args.remote, allow_fetch=not args.offline
    )
    if args.json:
        print(json.dumps(record(res), ensure_ascii=False))
    else:
        print(f"dev-preflight [{res.status}] {res.message}")
        print(
            f"  local={res.local_sha} remote={res.remote_sha} ref={res.remote_ref} "
            f"HEAD={res.head_sha} fetch={res.fetch} promotable={res.promotable}"
        )
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
