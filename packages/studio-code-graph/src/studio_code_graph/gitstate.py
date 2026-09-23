from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from studio_code_graph.paths import is_selected, normalize_repo_relative

_GIT_TIMEOUT_SECONDS = 60
_SKIPPED_MODES = frozenset({"120000", "160000"})
"""Symlinks and submodules are never followed (workspace watchers never follow
symlinks either)."""


@dataclass(frozen=True)
class RepoFiles:
    """Content identity of the code-relevant files of one repository:
    repo-relative POSIX path -> Git blob id. Content-addressed, so a branch
    switch that leaves the code identical, or a touched-but-unchanged file,
    yields the same digest."""

    files: dict[str, str]

    @property
    def digest(self) -> str:
        return files_digest(self.files)


@dataclass(frozen=True)
class ChangeSummary:
    added: int = 0
    modified: int = 0
    deleted: int = 0
    renamed: int = 0

    @property
    def total(self) -> int:
        return self.added + self.modified + self.deleted + self.renamed

    @property
    def has_removals(self) -> bool:
        return self.deleted > 0 or self.renamed > 0


def files_digest(files: dict[str, str]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(files):
        hasher.update(f"{path}\x00{files[path]}\n".encode())
    return hasher.hexdigest()


def summarize_change(before: dict[str, str], after: dict[str, str]) -> ChangeSummary:
    """Classify the difference between two file maps. A rename is a removed path
    and an added path sharing one blob id; nothing is guessed beyond that."""
    removed = {path: blob for path, blob in before.items() if path not in after}
    added = {path: blob for path, blob in after.items() if path not in before}
    modified = sum(1 for path in after if path in before and before[path] != after[path])
    removed_by_blob: dict[str, int] = {}
    for blob in removed.values():
        removed_by_blob[blob] = removed_by_blob.get(blob, 0) + 1
    renamed = 0
    for blob in added.values():
        if removed_by_blob.get(blob, 0) > 0:
            removed_by_blob[blob] -= 1
            renamed += 1
    return ChangeSummary(
        added=len(added) - renamed,
        modified=modified,
        deleted=len(removed) - renamed,
        renamed=renamed,
    )


def _git(repo_root: Path, *args: str, stdin: bytes | None = None) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            check=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            input=stdin,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout


def is_git_repository(repo_root: Path) -> bool:
    return (repo_root / ".git").exists()


def _relevant(
    raw_path: str,
    repo_root: Path,
    extensions: frozenset[str],
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> str | None:
    if os.path.splitext(raw_path)[1].lower() not in extensions:
        return None
    path = normalize_repo_relative(raw_path, repo_root)
    if path is None or not is_selected(path, include, exclude):
        return None
    return path


def _hash_working_files(repo_root: Path, paths: list[str]) -> dict[str, str] | None:
    hashable = [path for path in paths if "\n" not in path]
    if not hashable:
        return {}
    payload = "\n".join(hashable).encode() + b"\n"
    out = _git(repo_root, "hash-object", "--stdin-paths", stdin=payload)
    if out is None:
        return None
    blobs = out.decode("ascii", errors="replace").split()
    if len(blobs) != len(hashable):
        return None
    return dict(zip(hashable, blobs, strict=True))


def read_repo_files(
    repo_root: Path,
    extensions: Iterable[str],
    include: tuple[str, ...] = (),
    exclude: tuple[str, ...] = (),
) -> RepoFiles | None:
    """Code-relevant files of the working tree, or None when `repo_root` is not
    a readable Git repository (staleness is then unknowable, never guessed).
    Tracked blobs come from the index, then modified and untracked files are
    hashed from disk, so uncommitted edits, deletions and renames are seen."""
    if not is_git_repository(repo_root):
        return None
    wanted = frozenset(ext.lower() for ext in extensions)
    staged = _git(repo_root, "ls-files", "-s", "-z")
    changed = _git(repo_root, "ls-files", "-m", "-o", "--exclude-standard", "-z")
    if staged is None or changed is None:
        return None
    files: dict[str, str] = {}
    for entry in staged.decode("utf-8", errors="replace").split("\0"):
        meta, _, raw_path = entry.partition("\t")
        fields = meta.split()
        if len(fields) != 3 or fields[0] in _SKIPPED_MODES:
            continue
        path = _relevant(raw_path, repo_root, wanted, include, exclude)
        if path is not None:
            files[path] = fields[1]
    to_hash: list[str] = []
    for raw_path in changed.decode("utf-8", errors="replace").split("\0"):
        path = _relevant(raw_path, repo_root, wanted, include, exclude) if raw_path else None
        if path is None:
            continue
        absolute = repo_root / path
        if absolute.is_symlink() or not absolute.is_file():
            files.pop(path, None)
        else:
            to_hash.append(path)
    hashed = _hash_working_files(repo_root, to_hash)
    if hashed is None:
        return None
    files.update(hashed)
    return RepoFiles(files)
