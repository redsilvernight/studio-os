"""The data-format marker: stamp, migrate with backup, fail closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from studio_client.data_format import (
    DATA_FORMAT_VERSION,
    DataFormatError,
    ensure_data_format,
)


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    return None


def _marker(root: Path) -> int:
    return json.loads((root / "format.json").read_text(encoding="utf-8"))["format"]


def test_fresh_or_pre_marker_data_is_stamped_not_rewritten(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("keep = 1\n", encoding="utf-8")
    assert ensure_data_format(tmp_path) == DATA_FORMAT_VERSION
    assert _marker(tmp_path) == DATA_FORMAT_VERSION
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == "keep = 1\n"
    assert not (tmp_path / "backups").exists()


def test_current_data_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "format.json").write_text('{"format": 1}', encoding="utf-8")
    assert ensure_data_format(tmp_path) == 1


def test_newer_data_is_refused_and_untouched(tmp_path: Path) -> None:
    (tmp_path / "format.json").write_text('{"format": 9}', encoding="utf-8")
    with pytest.raises(DataFormatError, match="newer"):
        ensure_data_format(tmp_path)
    assert _marker(tmp_path) == 9


@pytest.mark.parametrize(
    "content", ["not json", "[]", '{"format": "1"}', '{"format": 0}', '{"format": true}', "{}"]
)
def test_unreadable_marker_fails_closed(tmp_path: Path, content: str) -> None:
    (tmp_path / "format.json").write_text(content, encoding="utf-8")
    with pytest.raises(DataFormatError):
        ensure_data_format(tmp_path)
    assert (tmp_path / "format.json").read_text(encoding="utf-8") == content


def test_older_data_is_backed_up_then_migrated_step_by_step(tmp_path: Path) -> None:
    (tmp_path / "format.json").write_text('{"format": 1}', encoding="utf-8")
    (tmp_path / "config.toml").write_text("old = true\n", encoding="utf-8")
    seen: list[int] = []

    def one_to_two(root: Path) -> None:
        seen.append(1)
        (root / "config.toml").write_text("new = true\n", encoding="utf-8")

    def two_to_three(root: Path) -> None:
        seen.append(2)

    assert ensure_data_format(tmp_path, current=3, migrations={1: one_to_two, 2: two_to_three}) == 3
    assert seen == [1, 2]
    assert _marker(tmp_path) == 3
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "config.toml").read_text(encoding="utf-8") == "old = true\n"


def test_a_failing_step_keeps_the_last_good_marker(tmp_path: Path) -> None:
    (tmp_path / "format.json").write_text('{"format": 1}', encoding="utf-8")

    def boom(root: Path) -> None:
        raise OSError("disk")

    with pytest.raises(DataFormatError, match="failed"):
        ensure_data_format(tmp_path, current=2, migrations={1: boom})
    assert _marker(tmp_path) == 1


def test_a_missing_migration_fails_before_any_change(tmp_path: Path) -> None:
    (tmp_path / "format.json").write_text('{"format": 1}', encoding="utf-8")
    (tmp_path / "config.toml").write_text("x\n", encoding="utf-8")
    with pytest.raises(DataFormatError, match="no migration"):
        ensure_data_format(tmp_path, current=3, migrations={2: lambda _root: None})
    assert not (tmp_path / "backups").exists()
    assert _marker(tmp_path) == 1
