from __future__ import annotations

from pathlib import Path

import pytest
from studio_code_graph.paths import PathEscapeError
from studio_code_graph.store import (
    SNAPSHOT_FILE,
    IndexStore,
    RepoSnapshot,
    StoreCorruptError,
)
from studio_contracts.local.graph import NodeKind

from .support import NOW, WORKSPACE_ID
from .test_index import small_graph


def snapshot(repo_name: str = "app") -> RepoSnapshot:
    nodes, edges = small_graph()
    return RepoSnapshot(
        repo_name=repo_name,
        provider_id="fake",
        provider_version="1.0.0",
        built_at=NOW,
        fingerprint="f" * 64,
        content_addressed=True,
        files={"a.py": "abc"},
        languages=["python"],
        dropped={"unsafe_path": 1},
        nodes=nodes,
        edges=edges,
    )


def test_roundtrip(tmp_path: Path) -> None:
    store = IndexStore(tmp_path)
    original = snapshot()
    store.save(WORKSPACE_ID, "code", original)
    loaded = store.load(WORKSPACE_ID, "code", "app")
    assert loaded == original
    assert {node.kind for node in loaded.nodes} >= {NodeKind.FILE}


def test_missing_snapshot_is_none(tmp_path: Path) -> None:
    assert IndexStore(tmp_path).load(WORKSPACE_ID, "code", "app") is None


@pytest.mark.parametrize("content", ["", "{", '{"schema_version": 1}', "[]"])
def test_corrupt_snapshot_is_reported(tmp_path: Path, content: str) -> None:
    store = IndexStore(tmp_path)
    store.save(WORKSPACE_ID, "code", snapshot())
    (store.repo_dir(WORKSPACE_ID, "code", "app") / SNAPSHOT_FILE).write_text(content)
    with pytest.raises(StoreCorruptError):
        store.load(WORKSPACE_ID, "code", "app")


def test_snapshot_of_another_repo_is_corrupt(tmp_path: Path) -> None:
    store = IndexStore(tmp_path)
    store.save(WORKSPACE_ID, "code", snapshot("other"))
    target = store.repo_dir(WORKSPACE_ID, "code", "app")
    target.mkdir(parents=True)
    source = store.repo_dir(WORKSPACE_ID, "code", "other") / SNAPSHOT_FILE
    (target / SNAPSHOT_FILE).write_bytes(source.read_bytes())
    with pytest.raises(StoreCorruptError):
        store.load(WORKSPACE_ID, "code", "app")


def test_save_leaves_no_temporary_file_and_overwrites(tmp_path: Path) -> None:
    store = IndexStore(tmp_path)
    store.save(WORKSPACE_ID, "code", snapshot())
    store.save(WORKSPACE_ID, "code", snapshot())
    names = [path.name for path in store.repo_dir(WORKSPACE_ID, "code", "app").iterdir()]
    assert names == [SNAPSHOT_FILE]


def test_failed_save_keeps_the_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = IndexStore(tmp_path)
    store.save(WORKSPACE_ID, "code", snapshot())

    def boom(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        store.save(WORKSPACE_ID, "code", snapshot())
    monkeypatch.undo()
    assert store.load(WORKSPACE_ID, "code", "app") is not None
    assert [p.name for p in store.repo_dir(WORKSPACE_ID, "code", "app").iterdir()] == [
        SNAPSHOT_FILE
    ]


@pytest.mark.parametrize("name", ["../../../../x", "a/../../../../b"])
def test_directories_are_confined_to_the_cache_root(tmp_path: Path, name: str) -> None:
    store = IndexStore(tmp_path / "cache")
    with pytest.raises(PathEscapeError):
        store.repo_dir(WORKSPACE_ID, name, "app")
    with pytest.raises(PathEscapeError):
        store.repo_dir(WORKSPACE_ID, "code", name)


def test_discard_and_purge(tmp_path: Path) -> None:
    store = IndexStore(tmp_path)
    store.save(WORKSPACE_ID, "code", snapshot("a"))
    store.save(WORKSPACE_ID, "code", snapshot("b"))
    store.discard(WORKSPACE_ID, "code", "a")
    assert store.load(WORKSPACE_ID, "code", "a") is None
    assert store.load(WORKSPACE_ID, "code", "b") is not None
    store.purge_workspace(WORKSPACE_ID)
    assert not (tmp_path / str(WORKSPACE_ID)).exists()


def test_work_dir_is_beneath_the_repo_cache(tmp_path: Path) -> None:
    store = IndexStore(tmp_path)
    work = store.work_dir(WORKSPACE_ID, "code", "app")
    assert store.repo_dir(WORKSPACE_ID, "code", "app") in work.parents
