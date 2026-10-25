from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from studio_client.bootstrap import (
    BackupEntry,
    BackupJournal,
    BootstrapError,
    _label,
    _safe_target,
    _write_journal,
    backup_file,
    backup_root_for,
    list_backups,
    rollback,
)

_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,199}\Z")
_MANIFESTS = {
    ".studio-os/library-skills-manifest.json",
    ".studio-os/library-definitions-manifest.json",
}


def _managed_path(relative: str) -> bool:
    if relative in _MANIFESTS:
        return True
    parts = relative.split("/")
    key: str | None = None
    if (
        len(parts) == 4
        and parts[0] in {".agents", ".claude"}
        and parts[1] == "skills"
        and parts[3] == "SKILL.md"
    ):
        key = parts[2]
    elif (
        len(parts) == 5
        and parts[:3] == [".config", "opencode", "skills"]
        and parts[4] == "SKILL.md"
    ):
        key = parts[3]
    elif (
        len(parts) == 3
        and (parts[0], parts[1])
        in {
            (".agents", "rules"),
            (".agents", "definitions"),
            (".claude", "rules"),
            (".claude", "agents"),
        }
        and parts[2].endswith(".md")
    ):
        key = parts[2][:-3]
    return key is not None and _KEY.fullmatch(key) is not None and ".." not in key


@dataclass(frozen=True)
class ProjectionBackup:
    home: Path
    directory: Path
    entries: list[BackupEntry]


def prepare_projection_backup(
    home: Path, desired: Mapping[Path, str | None]
) -> ProjectionBackup | None:
    root = home.resolve()
    directory = backup_root_for(root)
    directory = directory.with_name(f"library-{directory.name}-{uuid4().hex[:8]}")
    entries: list[BackupEntry] = []
    for path, text in sorted(desired.items(), key=lambda item: str(item[0])):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            raise BootstrapError("projection target outside home") from None
        if not _managed_path(relative):
            raise BootstrapError("refusing to back up a non-projection target")
        target = _safe_target(root, relative)
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current == text:
            continue
        saved = backup_file(root, relative, directory) if current is not None else None
        entries.append(
            BackupEntry(
                path=relative,
                action="created" if current is None else "replaced",
                backup=saved.relative_to(directory).as_posix() if saved else None,
                after_label=_label(text) if text is not None else "absent",
            )
        )
    return ProjectionBackup(root, directory, entries) if entries else None


def commit_projection_backup(backup: ProjectionBackup | None) -> None:
    if backup is not None:
        _write_journal(backup.home, backup.directory, backup.entries)


def list_projection_backups(home: Path) -> list[BackupJournal]:
    return [
        journal
        for journal in list_backups(home.resolve())
        if journal.directory.name.startswith("library-")
    ]


def restore_projection_backup(home: Path, backup_id: str | None = None) -> list[str]:
    root = home.resolve()
    candidates = [
        journal
        for journal in list_projection_backups(root)
        if (backup_id is None and journal.status == "applied")
        or journal.directory.name == backup_id
    ]
    if not candidates:
        raise BootstrapError("no matching library projection backup")
    journal = candidates[0]
    if any(not _managed_path(entry.path) for entry in journal.entries):
        raise BootstrapError("refusing to restore a non-projection target")
    return rollback(root, backup_id=journal.directory.name)
