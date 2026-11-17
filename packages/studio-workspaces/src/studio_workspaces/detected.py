from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from studio_contracts.local.identity import ProfileRef

from studio_workspaces.path_safety import workspace_binding_key

DETECTED_REPOSITORIES_FILE = "detected-repositories.json"
DETECTED_REPOSITORIES_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DetectedRepository:
    """A Git repository seen on this machine that no workspace follows yet:
    the identity P3-detected needs to offer a one-gesture link, with no path
    outside the main checkout and no credential."""

    profile_id: str
    server_origin: str
    root: str
    remotes: tuple[str, ...]
    repository_key: str | None
    reason: str
    last_seen_at: str


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _path(registry_dir: Path) -> Path:
    return registry_dir / DETECTED_REPOSITORIES_FILE


def _parse(entry: object) -> DetectedRepository | None:
    if not isinstance(entry, dict):
        return None
    data = cast(dict[str, object], entry)
    profile_id = data.get("profile_id")
    server_origin = data.get("server_origin")
    root = data.get("root")
    last_seen_at = data.get("last_seen_at")
    reason = data.get("reason")
    if not isinstance(profile_id, str) or not profile_id:
        return None
    if not isinstance(server_origin, str) or not server_origin:
        return None
    if not isinstance(root, str) or not root:
        return None
    if not isinstance(last_seen_at, str) or not isinstance(reason, str):
        return None
    raw_remotes = data.get("remotes")
    remotes = (
        tuple(item for item in raw_remotes if isinstance(item, str))
        if isinstance(raw_remotes, list)
        else ()
    )
    key = data.get("repository_key")
    return DetectedRepository(
        profile_id=profile_id,
        server_origin=server_origin,
        root=root,
        remotes=remotes,
        repository_key=key if isinstance(key, str) else None,
        reason=reason,
        last_seen_at=last_seen_at,
    )


def read_detected_repositories(registry_dir: Path) -> list[DetectedRepository]:
    """Every recorded entry, tolerating a missing or unreadable file: this
    registry is an observability list, never a source of truth for a
    workspace."""
    try:
        data = json.loads(_path(registry_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    entries = data.get("repositories")
    if not isinstance(entries, list):
        return []
    parsed = (_parse(entry) for entry in entries)
    return [entry for entry in parsed if entry is not None]


def list_detected_repositories(registry_dir: Path, profile: ProfileRef) -> list[DetectedRepository]:
    """Entries of the active server origin only, most recently seen first."""
    mine = [
        entry
        for entry in read_detected_repositories(registry_dir)
        if entry.profile_id == profile.profile_id
        and entry.server_origin.rstrip("/").lower() == profile.server_origin.rstrip("/").lower()
    ]
    return sorted(mine, key=lambda entry: entry.last_seen_at, reverse=True)


def _write(registry_dir: Path, entries: Sequence[DetectedRepository]) -> None:
    path = _path(registry_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": DETECTED_REPOSITORIES_SCHEMA_VERSION,
        "repositories": [
            {
                "profile_id": entry.profile_id,
                "server_origin": entry.server_origin,
                "root": entry.root,
                "remotes": list(entry.remotes),
                "repository_key": entry.repository_key,
                "reason": entry.reason,
                "last_seen_at": entry.last_seen_at,
            }
            for entry in entries
        ],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def record_detected_repository(
    registry_dir: Path,
    profile: ProfileRef,
    root: str,
    remotes: Sequence[str],
    repository_key: str | None,
    reason: str,
    *,
    now: Callable[[], datetime] = _utc_now,
) -> DetectedRepository:
    """Upserts one unresolved repository for this profile, keeping the same
    entry when it is seen again."""
    stamp = now().astimezone(UTC).isoformat()
    candidate = DetectedRepository(
        profile_id=profile.profile_id,
        server_origin=profile.server_origin,
        root=root,
        remotes=tuple(dict.fromkeys(remotes)),
        repository_key=repository_key,
        reason=reason,
        last_seen_at=stamp,
    )
    wanted = workspace_binding_key(root)
    kept: list[DetectedRepository] = []
    for entry in read_detected_repositories(registry_dir):
        if (
            entry.profile_id == candidate.profile_id
            and entry.server_origin.rstrip("/").lower()
            == candidate.server_origin.rstrip("/").lower()
            and workspace_binding_key(entry.root) == wanted
        ):
            continue
        kept.append(entry)
    kept.append(candidate)
    _write(registry_dir, kept)
    return candidate


def forget_detected_repository(registry_dir: Path, profile: ProfileRef, root: str) -> bool:
    """Drops an entry once the repository is followed by a workspace."""
    wanted = workspace_binding_key(root)
    kept: list[DetectedRepository] = []
    removed = False
    for entry in read_detected_repositories(registry_dir):
        same_origin = (
            entry.profile_id == profile.profile_id
            and entry.server_origin.rstrip("/").lower() == profile.server_origin.rstrip("/").lower()
        )
        if same_origin and workspace_binding_key(entry.root) == wanted:
            removed = True
            continue
        kept.append(entry)
    if removed:
        _write(registry_dir, kept)
    return removed
