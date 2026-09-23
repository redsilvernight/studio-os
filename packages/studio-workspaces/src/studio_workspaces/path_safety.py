from __future__ import annotations

import ntpath
import os
import re
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError
from studio_contracts.local.common import GlobPattern

_GLOB_ADAPTER = TypeAdapter(GlobPattern)

_DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_DRIVE_ROOT = re.compile(r"^[A-Za-z]:[\\/]*$")
_DRIVE_RELATIVE = re.compile(r"^[A-Za-z]:(?![\\/])")
_UNC = re.compile(r"^(\\\\|\?\?\\|//)")
_EXTGLOB_OPENERS = ("@(", "*(", "+(", "?(", "!(")


@dataclass(frozen=True)
class PathVerdict:
    ok: bool
    reason: str
    normalized: str | None = None


def _has_dot_segment(value: str) -> bool:
    return any(part in (".", "..") for part in re.split(r"[\\/]", value))


def classify_local_path(raw: str) -> PathVerdict:
    if not raw or len(raw) > 1024 or "\x00" in raw:
        return PathVerdict(False, "empty, too long or contains NUL")
    if _DRIVE_RELATIVE.match(raw):
        return PathVerdict(False, "drive-relative paths are not absolute (e.g. 'D:folder')")
    is_abs = bool(_DRIVE_ABSOLUTE.match(raw) or raw.startswith("/") or _UNC.match(raw))
    if not is_abs:
        return PathVerdict(False, "path must be absolute")
    if _UNC.match(raw):
        return PathVerdict(False, "network (UNC) paths cannot be workspace roots")
    if _DRIVE_ROOT.match(raw) or raw.strip("/\\") == "":
        return PathVerdict(False, "a filesystem or drive root cannot be a workspace root")
    if _has_dot_segment(raw):
        return PathVerdict(False, "path must be canonical (no '.' or '..' segment)")
    normalized = os.path.normpath(raw)
    if _has_dot_segment(normalized):
        return PathVerdict(False, "path must be canonical (no '.' or '..' segment)")
    return PathVerdict(True, "ok", normalized)


def _is_link(path: str) -> bool:
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    try:
        return bool(isjunction(path)) if isjunction is not None else False
    except OSError:
        return False


def check_readable(path: str) -> PathVerdict:
    verdict = classify_local_path(path)
    if not verdict.ok:
        return verdict
    try:
        if _is_link(path):
            return PathVerdict(False, "workspace roots cannot be a symlink or junction")
        if not os.path.exists(path):
            return PathVerdict(False, "path does not exist (moved or deleted)")
        if not os.path.isdir(path):
            return PathVerdict(False, "path is not a directory")
        if not os.access(path, os.R_OK | os.X_OK):
            return PathVerdict(False, "permission denied")
    except OSError:
        return PathVerdict(False, "path is inaccessible")
    return PathVerdict(True, "ok", verdict.normalized)


def _extglob_group_has_separator(pattern: str, start: int) -> bool:
    depth = 0
    i = start
    while i < len(pattern):
        ch = pattern[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return False
        elif depth >= 1 and ch == "/":
            return True
        i += 1
    return False


def _extglob_group_has_dotdot(pattern: str, start: int) -> bool:
    depth = 0
    i = start
    while i < len(pattern):
        ch = pattern[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                segment = pattern[start:i]
                parts = re.split(r"[|/]", segment)
                return any(part in (".", "..") for part in parts)
        i += 1
    return False


def check_p5_glob(pattern: str) -> PathVerdict:
    try:
        _GLOB_ADAPTER.validate_python(pattern)
    except ValidationError:
        return PathVerdict(False, "glob rejected by the P1 dialect")
    if "." in pattern.split("/"):
        return PathVerdict(False, "glob must not contain '.' segments")
    for opener in _EXTGLOB_OPENERS:
        idx = pattern.find(opener)
        while idx != -1:
            group_start = idx + len(opener) - 1
            if _extglob_group_has_separator(pattern, group_start):
                return PathVerdict(
                    False,
                    f"extglob group {opener!r} must not span directories",
                )
            if _extglob_group_has_dotdot(pattern, group_start):
                return PathVerdict(
                    False,
                    f"extglob group {opener!r} must not contain '.' or '..'",
                )
            idx = pattern.find(opener, idx + 1)
    return PathVerdict(True, "ok", pattern)


def workspace_binding_key(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path))
