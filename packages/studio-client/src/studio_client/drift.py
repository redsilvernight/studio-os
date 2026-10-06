"""Shared drift taxonomy for managed Library projections (AIB P5).

Single source of truth for the four states first introduced by
``skill_sync``: ``current``, ``missing``, ``outdated`` and
``locally_modified``. ``skill_sync`` and ``adapters check`` both classify
through :func:`classify_state` so rules, agents, workflows and managed
blocks reuse the same detector instead of growing a second one.

Manifest support is additive: schema v1 (``{"skills": [...]}``) keeps
being read and written by ``skill_sync`` unchanged; schema v2
(``{"items": [{"kind": ..., "stable_key": ..., ...}]}``) carries every
managed kind. Readers accept both.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

SyncState = Literal["current", "missing", "outdated", "locally_modified"]

DriftKind = Literal["skill", "rule", "agent", "workflow", "block"]

_MANIFEST_SCHEMA_V1 = 1
MANIFEST_SCHEMA_VERSION = 2


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_state(
    current: str | None,
    desired: str,
    managed_hash: str | None,
) -> SyncState:
    if current is None:
        return "missing"
    if current == desired:
        return "current"
    if managed_hash is not None and hash_text(current) == managed_hash:
        return "outdated"
    return "locally_modified"


def load_managed_hashes(manifest_path: Path) -> dict[tuple[str, str], str]:
    """Read managed hashes keyed by ``(kind, stable_key)``.

    Accepts schema v1 (skills only) and schema v2 (multi-kind ``items``).
    Returns an empty mapping when the file is absent or invalid.
    """
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    hashes: dict[tuple[str, str], str] = {}
    rows = payload.get("items")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            kind = row.get("kind")
            key = row.get("stable_key")
            digest = row.get("sha256")
            if isinstance(kind, str) and isinstance(key, str) and isinstance(digest, str):
                hashes[(kind, key)] = digest
        return hashes
    if payload.get("schema_version") != _MANIFEST_SCHEMA_V1:
        return {}
    rows = payload.get("skills")
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get("stable_key")
        digest = row.get("sha256")
        if isinstance(key, str) and isinstance(digest, str):
            hashes[("skill", key)] = digest
    return hashes


def dump_manifest_v2(entries: list[dict[str, object]]) -> str:
    ordered = sorted(entries, key=lambda row: (str(row.get("kind")), str(row.get("stable_key"))))
    payload = {"schema_version": MANIFEST_SCHEMA_VERSION, "items": ordered}
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
