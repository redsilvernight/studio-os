"""Filesystem primitives every harness edit goes through.

Confinement (a target is a fixed relative path under one workspace root, with no
symlink or reparse point on the way), bounded reads, and atomic replacement.
Nothing here knows about a vendor or a file format.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_CONFIG_BYTES = 1024 * 1024
_UTF8_BOM = b"\xef\xbb\xbf"
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class FsError(Exception):
    """A filesystem refusal. `reason` is a stable machine-readable token; the
    message never carries a path."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_link_like(info: os.stat_result) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def resolve_target(root: Path, relative: str) -> Path:
    """The absolute path of `relative` under `root`, refusing anything that could
    escape or redirect: absolute or dotted segments, and any symlink / reparse
    point among the existing components (root included)."""
    if not relative or relative.startswith(("/", "\\")) or ":" in relative:
        raise FsError("unsafe_path", "the target is not a plain relative path")
    parts = relative.split("/")
    if any(part in ("", ".", "..") or "\\" in part for part in parts):
        raise FsError("unsafe_path", "the target is not a plain relative path")
    try:
        root_info = os.lstat(root)
    except OSError as error:
        raise FsError("workspace_inaccessible", "the workspace root is not accessible") from error
    if not stat.S_ISDIR(root_info.st_mode) or _is_link_like(root_info):
        raise FsError("unsafe_path", "the workspace root is not a plain directory")
    current = root
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as error:
            raise FsError("permission_denied", "a target component is not accessible") from error
        if _is_link_like(info):
            raise FsError("symlink", "the target crosses a symbolic link")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise FsError("unsafe_path", "a target component is not a directory")
    target = root.joinpath(*parts)
    try:
        real_root = root.resolve(strict=True)
        real_parent = target.parent.resolve(strict=False)
    except OSError as error:
        raise FsError("unsafe_path", "the target cannot be resolved") from error
    if real_root != real_parent and real_root not in real_parent.parents:
        raise FsError("unsafe_path", "the target resolves outside the workspace")
    return target


@dataclass(frozen=True)
class Document:
    """A file as found on disk: raw bytes, the text without its BOM, and the
    hash of the raw bytes (the identity every later comparison uses)."""

    raw: bytes
    text: str
    bom: bool

    @property
    def sha256(self) -> str:
        return sha256_hex(self.raw)


def encode_text(text: str, *, bom: bool) -> bytes:
    data = text.encode("utf-8")
    return _UTF8_BOM + data if bom else data


def read_document(path: Path, *, max_bytes: int = MAX_CONFIG_BYTES) -> Document | None:
    """None when the file does not exist. Raises FsError for anything that is
    not a small regular UTF-8 file. `max_bytes` widens the bound only for a
    file the editor reads but never rewrites itself."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise FsError("permission_denied", "the file is not accessible") from error
    if _is_link_like(info):
        raise FsError("symlink", "the file is a symbolic link")
    if not stat.S_ISREG(info.st_mode):
        raise FsError("not_regular", "the target is not a regular file")
    if info.st_size > max_bytes:
        raise FsError("too_large", "the file exceeds the size the editor accepts")
    try:
        with open(path, "rb") as handle:
            raw = handle.read(max_bytes + 1)
    except PermissionError as error:
        raise FsError("permission_denied", "the file cannot be read") from error
    except OSError as error:
        raise FsError("io_error", "the file could not be read") from error
    if len(raw) > max_bytes:
        raise FsError("too_large", "the file exceeds the size the editor accepts")
    bom = raw.startswith(_UTF8_BOM)
    try:
        text = (raw[len(_UTF8_BOM) :] if bom else raw).decode("utf-8")
    except UnicodeDecodeError as error:
        raise FsError("not_utf8", "the file is not valid UTF-8") from error
    return Document(raw=raw, text=text, bom=bom)


def is_writable(path: Path) -> bool:
    """Whether an atomic replacement of `path` (or its creation) can succeed."""
    if path.exists():
        return os.access(path, os.W_OK) and os.access(path.parent, os.W_OK)
    return os.access(path.parent, os.W_OK)


def atomic_write(path: Path, data: bytes) -> None:
    """Write next to `path`, flush to disk, then replace in one step: readers see
    the old file or the new one, never a partial one. A failure leaves the
    original untouched and no temporary file behind."""
    if len(data) > MAX_CONFIG_BYTES:
        raise FsError("too_large", "the result exceeds the size the editor accepts")
    temp = path.with_name(f".{path.name}.studio-{secrets.token_hex(6)}.tmp")
    try:
        with open(temp, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            with contextlib.suppress(OSError):
                shutil.copymode(path, temp)
        os.replace(temp, path)
    except PermissionError as error:
        raise FsError("permission_denied", "the file cannot be written") from error
    except OSError as error:
        raise FsError("io_error", "the file could not be written") from error
    finally:
        with contextlib.suppress(OSError):
            temp.unlink()


def remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except PermissionError as error:
        raise FsError("permission_denied", "the file cannot be removed") from error
    except OSError as error:
        raise FsError("io_error", "the file could not be removed") from error
