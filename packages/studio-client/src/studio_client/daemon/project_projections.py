from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from studio_contracts.bootstrap import BootstrapFileState
from studio_contracts.local.project_projections import (
    PendingProjectionFile,
    PendingProjectionUpdate,
    ProjectProjectionsApplyResult,
    ProjectProjectionsStatus,
)

from studio_client import bootstrap
from studio_client.adapters import list_adapters
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.projection_source import ProjectionBundle, fetch_projection_bundle
from studio_client.tokens import TokenStore

PENDING_FILE_NAME = "project-projections-pending.json"
GITIGNORE_NAME = ".gitignore"
GITIGNORE_BEGIN = "# BEGIN studio-os generated projections"
GITIGNORE_END = "# END studio-os generated projections"
_PENDING_STATES = {
    BootstrapFileState.ABSENT: "absent",
    BootstrapFileState.OBSOLETE: "obsolete",
    BootstrapFileState.MODIFIED: "modified",
}


@dataclass(frozen=True)
class RepoTarget:
    workspace_id: UUID
    project_id: UUID
    repo_path: Path


def repo_targets(workspaces: Iterable[object]) -> list[RepoTarget]:
    """First repository of each workspace; workspaces without one are skipped."""
    targets: list[RepoTarget] = []
    for watch in workspaces:
        paths = watch.plan.repo_paths  # type: ignore[attr-defined]
        if paths:
            targets.append(
                RepoTarget(
                    workspace_id=watch.workspace_id,  # type: ignore[attr-defined]
                    project_id=watch.project_id,  # type: ignore[attr-defined]
                    repo_path=Path(paths[0]),
                )
            )
    return targets


def project_projections_status(data_root: Path) -> ProjectProjectionsStatus:
    try:
        payload = json.loads((data_root / PENDING_FILE_NAME).read_text(encoding="utf-8"))
        return ProjectProjectionsStatus.model_validate(payload)
    except (OSError, UnicodeDecodeError, ValueError):
        return ProjectProjectionsStatus()


def mark_project_updates_pending(
    config: ClientConfig,
    token_store: TokenStore,
    targets: Sequence[RepoTarget],
    data_root: Path,
) -> bool:
    """Plan every followed repository against the Library without writing
    anything and persist the repositories that differ. Returns whether any
    update is pending."""
    bundles: dict[UUID, ProjectionBundle] = {}
    updates: list[PendingProjectionUpdate] = []
    for target in targets:
        if target.project_id not in bundles:
            bundles[target.project_id] = _fetch_bundle(config, token_store, target.project_id)
        _, _, files = _plan(target, bundles[target.project_id])
        if files:
            updates.append(
                PendingProjectionUpdate(
                    workspace_id=target.workspace_id,
                    project_id=target.project_id,
                    files=files,
                    checked_at=datetime.now(UTC),
                )
            )
    _save(data_root, ProjectProjectionsStatus(updates=updates))
    return bool(updates)


def apply_project_update(
    config: ClientConfig,
    token_store: TokenStore,
    targets: Sequence[RepoTarget],
    data_root: Path,
    workspace_id: UUID,
) -> ProjectProjectionsApplyResult:
    """Write the pending projections of one repository, after the caller's
    confirmation, then ignore exactly the generated files in git."""
    target = next((item for item in targets if item.workspace_id == workspace_id), None)
    if target is None:
        raise ValueError("unknown workspace repository")
    bundle = _fetch_bundle(config, token_store, target.project_id)
    manifest, planned, _ = _plan(target, bundle)
    report = bootstrap.observe(target.repo_path, manifest, planned=planned)
    written = bootstrap.apply_files(
        target.repo_path, manifest, report, planned=planned, confirm=True
    )
    ignored = write_gitignore_block(target.repo_path, planned)
    remaining = [
        update
        for update in project_projections_status(data_root).updates
        if update.workspace_id != workspace_id
    ]
    _save(data_root, ProjectProjectionsStatus(updates=remaining))
    return ProjectProjectionsApplyResult(
        workspace_id=workspace_id, written=written, ignored=ignored
    )


def write_gitignore_block(repo_root: Path, planned: Sequence[bootstrap.PlannedFile]) -> list[str]:
    """Maintain one managed block of `.gitignore` listing the generated
    whole-file projections. `AGENTS.md`, `CLAUDE.md` and every other file are
    never listed, and text outside the markers is preserved byte for byte."""
    paths = sorted(item.path for item in planned if not item.block and not item.incompatible)
    target = repo_root / GITIGNORE_NAME
    existing = target.read_bytes().decode("utf-8") if target.is_file() else ""
    block = "\n".join([GITIGNORE_BEGIN, *(f"/{path}" for path in paths), GITIGNORE_END]) + "\n"
    begin = existing.find(GITIGNORE_BEGIN)
    end = existing.find(GITIGNORE_END, begin) if begin != -1 else -1
    if begin != -1 and end != -1:
        tail = existing[end + len(GITIGNORE_END) :].removeprefix("\n")
        updated = existing[:begin] + block + tail
    else:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        updated = existing + separator + block
    if updated != existing:
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
    return paths


def _plan(
    target: RepoTarget, bundle: ProjectionBundle
) -> tuple[object, list[bootstrap.PlannedFile], list[PendingProjectionFile]]:
    repo = target.repo_path
    if (repo / bootstrap.MANIFEST_RELATIVE_PATH).is_file():
        manifest = bootstrap.load_manifest(repo)
    else:
        manifest = bootstrap.make_manifest(
            "library-projection", "Library projection", list(list_adapters())
        )
    planned = bootstrap.plan_files(repo, manifest, bundle)
    report = bootstrap.observe(repo, manifest, planned=planned)
    files = [
        PendingProjectionFile(path=item.path, state=_PENDING_STATES[item.state])
        for item in report.files
        if item.state in _PENDING_STATES
    ]
    return manifest, planned, files


def _fetch_bundle(
    config: ClientConfig, token_store: TokenStore, project_id: UUID
) -> ProjectionBundle:
    async def fetch() -> ProjectionBundle:
        async with StudioApiClient(config, token_store) as client:
            return await fetch_projection_bundle(client, project_id)

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, fetch()).result()


def _save(data_root: Path, status: ProjectProjectionsStatus) -> None:
    path = data_root / PENDING_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(status.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


__all__ = [
    "RepoTarget",
    "apply_project_update",
    "mark_project_updates_pending",
    "project_projections_status",
    "repo_targets",
    "write_gitignore_block",
]
