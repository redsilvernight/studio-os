"""Local, bounded, identifiable backups of the files a harness apply replaces.

Backups hold the user's own configuration, so they stay in the daemon's private
data directory: never in the workspace, never sent to a server, never logged.
Each applied plan gets one directory `<workspace>/<adapter>/<rollback_id>/`
with a manifest and one `.bak` per replaced file. Only the newest
`RETENTION_PER_ADAPTER` are kept per workspace and adapter.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from studio_client.harness.fsafe import MAX_CONFIG_BYTES, FsError, atomic_write, sha256_hex

RETENTION_PER_ADAPTER = 10
ROLLBACK_ID_PATTERN = re.compile(r"^rb-[0-9a-f]{32}$")
_ADAPTER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_MANIFEST = "manifest.json"
_APPLIED = "applied"
_ROLLED_BACK = "rolled_back"
_PENDING = "pending"
_FAILED = "failed"


@dataclass(frozen=True)
class BackupEntry:
    change_id: str
    target: str
    kind: str
    before_hash: str | None
    after_hash: str | None
    backup_file: str | None


@dataclass
class BackupRecord:
    rollback_id: str
    workspace_id: UUID
    adapter_id: str
    created_at: str
    status: str
    entries: list[BackupEntry] = field(default_factory=list)


class BackupError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BackupStore:
    def __init__(self, root: Path, *, retention: int = RETENTION_PER_ADAPTER) -> None:
        self._root = root
        self._retention = retention

    def _adapter_dir(self, workspace_id: UUID, adapter_id: str) -> Path:
        if _ADAPTER_PATTERN.match(adapter_id) is None:
            raise BackupError("invalid_adapter")
        return self._root / str(workspace_id) / adapter_id

    def begin(
        self,
        rollback_id: str,
        workspace_id: UUID,
        adapter_id: str,
        entries: list[tuple[str, str, str, bytes | None, str | None]],
    ) -> BackupRecord:
        """Copy every original before anything is written. `entries` are
        (change_id, target, kind, original_bytes | None, after_hash). Raises
        BackupError when a backup cannot be made: the apply then never starts."""
        if ROLLBACK_ID_PATTERN.match(rollback_id) is None:
            raise BackupError("invalid_rollback_id")
        directory = self._adapter_dir(workspace_id, adapter_id) / rollback_id
        record = BackupRecord(
            rollback_id=rollback_id,
            workspace_id=workspace_id,
            adapter_id=adapter_id,
            created_at=datetime.now(UTC).isoformat(),
            status=_PENDING,
        )
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            for index, (change_id, target, kind, original, after_hash) in enumerate(entries):
                backup_file: str | None = None
                if original is not None:
                    if len(original) > MAX_CONFIG_BYTES:
                        raise BackupError("too_large")
                    backup_file = f"{index}.bak"
                    (directory / backup_file).write_bytes(original)
                record.entries.append(
                    BackupEntry(
                        change_id=change_id,
                        target=target,
                        kind=kind,
                        before_hash=None if original is None else sha256_hex(original),
                        after_hash=after_hash,
                        backup_file=backup_file,
                    )
                )
            self._save(directory, record)
        except BackupError:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        except OSError as error:
            shutil.rmtree(directory, ignore_errors=True)
            raise BackupError("backup_failed") from error
        return record

    def _save(self, directory: Path, record: BackupRecord) -> None:
        body: dict[str, Any] = {
            "rollback_id": record.rollback_id,
            "workspace_id": str(record.workspace_id),
            "adapter_id": record.adapter_id,
            "created_at": record.created_at,
            "status": record.status,
            "entries": [entry.__dict__ for entry in record.entries],
        }
        try:
            atomic_write(directory / _MANIFEST, json.dumps(body, indent=2).encode("utf-8"))
        except FsError as error:
            raise BackupError("backup_failed") from error

    def mark(self, record: BackupRecord, status: str) -> None:
        record.status = status
        self._save(
            self._adapter_dir(record.workspace_id, record.adapter_id) / record.rollback_id, record
        )

    def mark_applied(self, record: BackupRecord) -> None:
        self.mark(record, _APPLIED)
        self._prune(record.workspace_id, record.adapter_id)

    def mark_failed(self, record: BackupRecord) -> None:
        with contextlib.suppress(BackupError):
            self.mark(record, _FAILED)

    def mark_rolled_back(self, record: BackupRecord) -> None:
        self.mark(record, _ROLLED_BACK)

    def is_applied(self, record: BackupRecord) -> bool:
        return record.status == _APPLIED

    def is_rolled_back(self, record: BackupRecord) -> bool:
        return record.status == _ROLLED_BACK

    def _load(self, directory: Path) -> BackupRecord | None:
        try:
            body = json.loads((directory / _MANIFEST).read_text(encoding="utf-8"))
            return BackupRecord(
                rollback_id=str(body["rollback_id"]),
                workspace_id=UUID(body["workspace_id"]),
                adapter_id=str(body["adapter_id"]),
                created_at=str(body["created_at"]),
                status=str(body["status"]),
                entries=[BackupEntry(**entry) for entry in body["entries"]],
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def find(self, rollback_id: str) -> BackupRecord | None:
        if ROLLBACK_ID_PATTERN.match(rollback_id) is None or not self._root.is_dir():
            return None
        for workspace_dir in self._root.iterdir():
            for adapter_dir in workspace_dir.iterdir() if workspace_dir.is_dir() else ():
                candidate = adapter_dir / rollback_id
                if candidate.is_dir():
                    record = self._load(candidate)
                    if (
                        record is not None
                        and record.rollback_id == rollback_id
                        and str(record.workspace_id) == workspace_dir.name
                    ):
                        return record
        return None

    def latest_applied(self, workspace_id: UUID, adapter_id: str) -> BackupRecord | None:
        records = [
            record
            for record in self._records(workspace_id, adapter_id)
            if record.status == _APPLIED
        ]
        return max(records, key=lambda record: record.created_at) if records else None

    def _records(self, workspace_id: UUID, adapter_id: str) -> list[BackupRecord]:
        directory = self._adapter_dir(workspace_id, adapter_id)
        if not directory.is_dir():
            return []
        found = []
        for child in directory.iterdir():
            record = self._load(child) if child.is_dir() else None
            if record is not None:
                found.append(record)
        return found

    def read_backup(self, record: BackupRecord, entry: BackupEntry) -> bytes:
        """The saved original, verified against the hash recorded at backup time."""
        if entry.backup_file is None or "/" in entry.backup_file or "\\" in entry.backup_file:
            raise BackupError("backup_missing")
        path = self._adapter_dir(record.workspace_id, record.adapter_id) / record.rollback_id
        try:
            data = (path / entry.backup_file).read_bytes()
        except OSError as error:
            raise BackupError("backup_missing") from error
        if sha256_hex(data) != entry.before_hash:
            raise BackupError("backup_corrupt")
        return data

    def _prune(self, workspace_id: UUID, adapter_id: str) -> None:
        records = sorted(
            self._records(workspace_id, adapter_id), key=lambda record: record.created_at
        )
        for stale in records[: max(0, len(records) - self._retention)]:
            shutil.rmtree(
                self._adapter_dir(workspace_id, adapter_id) / stale.rollback_id,
                ignore_errors=True,
            )
