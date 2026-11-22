"Backup retention of a purged studio (pure filesystem, no database)."
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from studio_api.services import studio_deletion as deletion_service


def test_backups_older_than_the_retention_are_removed_but_the_newest_stays(
    tmp_path: Any,
) -> None:
    now = datetime(2026, 12, 1, tzinfo=UTC)
    for name in ("20260101T020000Z", "20261015T020000Z", "20261125T020000Z", "notes"):
        (tmp_path / name).mkdir()
    removed = deletion_service.purge_expired_backups(str(tmp_path), 30, now)
    assert sorted(removed) == ["20260101T020000Z", "20261015T020000Z"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["20261125T020000Z", "notes"]
    # all stale: the newest is still kept as the only restore point
    (tmp_path / "20261125T020000Z").rename(tmp_path / "20260201T020000Z")
    assert deletion_service.purge_expired_backups(str(tmp_path), 30, now) == []
    assert (tmp_path / "20260201T020000Z").is_dir()
    assert deletion_service.purge_expired_backups(str(tmp_path / "absent"), 30, now) == []
