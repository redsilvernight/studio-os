from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from studio_contracts.local.graph import GraphEdge, GraphNode

from studio_code_graph.paths import confine

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_FILE = "snapshot.json"
PROVIDER_WORK_DIR = "provider-work"
_MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024


class StoreCorruptError(Exception):
    pass


class RepoSnapshot(BaseModel):
    """Derived, rebuildable index of one repository in the common graph schema.
    Nothing provider-specific is stored besides the provider id and version."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    repo_name: str
    provider_id: str
    provider_version: str | None
    built_at: datetime
    fingerprint: str
    content_addressed: bool
    files: dict[str, str]
    languages: list[str]
    dropped: dict[str, int]
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class IndexStore:
    """On-disk cache of repo snapshots, addressed only by workspace id, the
    configured index directory name and the repo name, always beneath the
    daemon's cache root."""

    def __init__(self, cache_root: Path) -> None:
        self._cache_root = cache_root

    def repo_dir(self, workspace_id: UUID, directory_name: str, repo_name: str) -> Path:
        return confine(self._cache_root, str(workspace_id), directory_name, repo_name)

    def work_dir(self, workspace_id: UUID, directory_name: str, repo_name: str) -> Path:
        return confine(
            self._cache_root, str(workspace_id), directory_name, repo_name, PROVIDER_WORK_DIR
        )

    def load(self, workspace_id: UUID, directory_name: str, repo_name: str) -> RepoSnapshot | None:
        path = self.repo_dir(workspace_id, directory_name, repo_name) / SNAPSHOT_FILE
        if not path.is_file():
            return None
        try:
            if path.stat().st_size > _MAX_SNAPSHOT_BYTES:
                raise StoreCorruptError("snapshot exceeds the size bound")
            snapshot = RepoSnapshot.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as error:
            raise StoreCorruptError("snapshot is unreadable") from error
        if snapshot.schema_version != SNAPSHOT_SCHEMA_VERSION or snapshot.repo_name != repo_name:
            raise StoreCorruptError("snapshot does not match this repository")
        return snapshot

    def save(self, workspace_id: UUID, directory_name: str, snapshot: RepoSnapshot) -> None:
        directory = self.repo_dir(workspace_id, directory_name, snapshot.repo_name)
        directory.mkdir(parents=True, exist_ok=True)
        payload = snapshot.model_dump_json()
        handle, temp_name = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temp_name, directory / SNAPSHOT_FILE)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            raise

    def discard(self, workspace_id: UUID, directory_name: str, repo_name: str) -> None:
        shutil.rmtree(self.repo_dir(workspace_id, directory_name, repo_name), ignore_errors=True)

    def purge_workspace(self, workspace_id: UUID) -> None:
        shutil.rmtree(confine(self._cache_root, str(workspace_id)), ignore_errors=True)
