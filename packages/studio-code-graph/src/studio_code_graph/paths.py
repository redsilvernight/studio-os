from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath

from pydantic import TypeAdapter, ValidationError
from studio_contracts.local.common import RelativePath

_RELATIVE_PATH = TypeAdapter(RelativePath)


class PathEscapeError(ValueError):
    pass


def normalize_repo_relative(raw: str, repo_root: Path) -> str | None:
    """A provider-reported path as a contract-valid POSIX path strictly inside
    `repo_root`, or None when it is empty, escapes the root or is not representable."""
    text = raw.strip()
    if not text:
        return None
    candidate = text.replace("\\", "/")
    if PureWindowsPath(text).is_absolute() or PurePosixPath(candidate).is_absolute():
        try:
            candidate = Path(text).resolve().relative_to(repo_root.resolve()).as_posix()
        except (ValueError, OSError):
            return None
    parts = [part for part in candidate.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return None
    candidate = "/".join(parts)
    try:
        return _RELATIVE_PATH.validate_python(candidate)
    except ValidationError:
        return None


def confine(root: Path, *parts: str) -> Path:
    """`root / parts`, refused unless it resolves inside `root` (symlink- and
    `..`-safe)."""
    base = root.resolve()
    target = base.joinpath(*parts).resolve()
    if target != base and base not in target.parents:
        raise PathEscapeError("path escapes its root")
    return target


def same_location(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


@lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_match(pattern: str, relative_path: str) -> bool:
    """POSIX-style glob over a repo-relative path: `*` and `?` stay inside a
    segment, `**` crosses segments."""
    return _glob_regex(pattern).match(relative_path) is not None


def is_selected(relative_path: str, include: tuple[str, ...], exclude: tuple[str, ...]) -> bool:
    if any(glob_match(pattern, relative_path) for pattern in exclude):
        return False
    if not include:
        return True
    return any(glob_match(pattern, relative_path) for pattern in include)
