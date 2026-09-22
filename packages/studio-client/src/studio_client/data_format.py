"""On-disk format of the daemon data directory (`format.json`).

The installer replaces binaries only; user data survives an upgrade. This marker
lets a newer build recognise data written by an older one (and migrate it) and
lets an older build refuse data written by a newer one instead of corrupting it.

Kept in step with `SUPPORTED_DATA_FORMAT` in `desktop/src-tauri/src/diagnostics.rs`.

Rules:
- no marker: pre-marker data is format 1 by definition; it is stamped, not rewritten;
- marker newer than this build, or unreadable: fail closed, nothing is touched;
- marker older: run the registered migrations one step at a time, after a backup
  of the small state files; a failing step leaves the marker at the last good step.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

DATA_FORMAT_VERSION = 1
FORMAT_FILE = "format.json"
BACKUPS_DIR = "backups"
# Small state files worth copying before a migration. Vaults, workspaces and
# repositories live elsewhere and are never touched.
_BACKED_UP = ("config.toml", "state.db", "outbox.db")

Migration = Callable[[Path], None]
# `MIGRATIONS[n]` upgrades data from format n to n + 1. Empty while 1 is current.
MIGRATIONS: dict[int, Migration] = {}


class DataFormatError(RuntimeError):
    """The data directory cannot be used by this build; nothing was modified."""


def _read_marker(data_root: Path) -> int | None:
    path = data_root / FORMAT_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DataFormatError(f"{FORMAT_FILE} is unreadable") from exc
    try:
        value = json.loads(text).get("format")
    except (ValueError, AttributeError) as exc:
        raise DataFormatError(f"{FORMAT_FILE} is not valid") from exc
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise DataFormatError(f"{FORMAT_FILE} carries no valid format number")
    return value


def _write_marker(data_root: Path, version: int) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    tmp = data_root / f"{FORMAT_FILE}.tmp"
    tmp.write_text(json.dumps({"format": version}) + "\n", encoding="utf-8")
    os.replace(tmp, data_root / FORMAT_FILE)


def _backup(data_root: Path, from_version: int) -> Path | None:
    present = [name for name in _BACKED_UP if (data_root / name).is_file()]
    if not present:
        return None
    target = data_root / BACKUPS_DIR / f"format-{from_version}-{int(time.time())}"
    target.mkdir(parents=True, exist_ok=True)
    for name in present:
        shutil.copy2(data_root / name, target / name)
    return target


def ensure_data_format(
    data_root: Path,
    *,
    current: int = DATA_FORMAT_VERSION,
    migrations: dict[int, Migration] | None = None,
) -> int:
    """Return the format the data is at after this call, or raise `DataFormatError`."""
    steps = MIGRATIONS if migrations is None else migrations
    found = _read_marker(data_root)
    if found is None:
        _write_marker(data_root, current)
        return current
    if found > current:
        raise DataFormatError(
            f"data format {found} was written by a newer Studio OS "
            f"(this build supports up to {current})"
        )
    if found == current:
        return current
    missing = [n for n in range(found, current) if n not in steps]
    if missing:
        raise DataFormatError(f"no migration from data format {missing[0]}")
    _backup(data_root, found)
    version = found
    while version < current:
        try:
            steps[version](data_root)
        except Exception as exc:
            raise DataFormatError(f"migration from data format {version} failed") from exc
        version += 1
        _write_marker(data_root, version)
    return version
