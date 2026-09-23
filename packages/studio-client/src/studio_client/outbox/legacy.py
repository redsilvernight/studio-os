from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from studio_client.config import default_config_path
from studio_client.outbox.store import connect_read_only, default_outbox_path

_QUEUE_TABLES = (
    "pending_events",
    "pending_mutations",
    "pending_markers",
    "dead_letter",
    "multipart_uploads",
)
_SIDECAR_SUFFIXES = ("-wal", "-shm")
QUARANTINE_DIRNAME = "quarantine"
DISCARD_CONFIRMATION = "discard-legacy-outbox"


class LegacyOutboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class LegacyOutboxReport:
    path: Path
    exists: bool
    counts: dict[str, int]

    @property
    def has_queued_work(self) -> bool:
        return any(count > 0 for count in self.counts.values())


def quarantine_dir() -> Path:
    return default_config_path().with_name("outbox") / QUARANTINE_DIRNAME


def inspect_legacy_outbox(path: Path | None = None) -> LegacyOutboxReport:
    target = path or default_outbox_path()
    if not target.exists():
        return LegacyOutboxReport(target, False, {})
    conn = connect_read_only(target)
    try:
        existing = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in _QUEUE_TABLES
            if table in existing
        }
    except sqlite3.DatabaseError as exc:
        raise LegacyOutboxError("the legacy outbox cannot be read") from exc
    finally:
        conn.close()
    return LegacyOutboxReport(target, True, counts)


def _siblings(path: Path) -> list[Path]:
    return [path, *(path.with_name(path.name + suffix) for suffix in _SIDECAR_SUFFIXES)]


def quarantine_legacy_outbox(
    path: Path | None = None, *, destination_dir: Path | None = None
) -> Path:
    target = path or default_outbox_path()
    if not target.exists():
        raise LegacyOutboxError("there is no legacy outbox")
    folder = destination_dir or quarantine_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = folder / f"legacy-{stamp}.sqlite3"
    for source in _siblings(target):
        if source.exists():
            shutil.move(
                str(source),
                str(destination.with_name(destination.name + source.name[len(target.name) :])),
            )
    return destination


def export_legacy_outbox(destination: Path, path: Path | None = None) -> Path:
    target = path or default_outbox_path()
    if not target.exists():
        raise LegacyOutboxError("there is no legacy outbox")
    if destination.exists():
        raise LegacyOutboxError("the export destination already exists")
    conn = connect_read_only(target)
    try:
        existing = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        dump = {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in _QUEUE_TABLES
            if table in existing
        }
    except sqlite3.DatabaseError as exc:
        raise LegacyOutboxError("the legacy outbox cannot be read") from exc
    finally:
        conn.close()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(dump, indent=2, default=str) + "\n", encoding="utf-8")
    return destination


def discard_legacy_outbox(confirmation: str, path: Path | None = None) -> None:
    if confirmation != DISCARD_CONFIRMATION:
        raise LegacyOutboxError("discarding the legacy outbox requires the explicit confirmation")
    target = path or default_outbox_path()
    if not target.exists():
        raise LegacyOutboxError("there is no legacy outbox")
    for source in _siblings(target):
        source.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="studio-client outbox legacy",
        description=(
            "Review an outbox created before identity-partitioned outboxes. It has no "
            "server/profile/machine identity, so it is never replayed or adopted "
            "automatically: keep it aside, export it, or explicitly discard it."
        ),
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status", help="Show what the legacy outbox still holds.")
    actions.add_parser("quarantine", help="Move it aside, unreplayed and retained.")
    export = actions.add_parser(
        "export", help="Write its rows to a JSON file, leaving it in place."
    )
    export.add_argument("destination", type=Path)
    discard = actions.add_parser("discard", help="Permanently delete it.")
    discard.add_argument("--confirm", required=True, help=f"Must be {DISCARD_CONFIRMATION!r}.")
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            report = inspect_legacy_outbox()
            print(
                json.dumps(
                    {"path": str(report.path), "exists": report.exists, "counts": report.counts}
                )
            )
        elif args.action == "quarantine":
            print(quarantine_legacy_outbox())
        elif args.action == "export":
            print(export_legacy_outbox(args.destination))
        else:
            discard_legacy_outbox(args.confirm)
            print("discarded")
    except LegacyOutboxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
