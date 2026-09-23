from __future__ import annotations

from pathlib import Path

from studio_client.knowledge.watch import VaultIndexWatcher
from studio_client.watchers.base import PollingWatcher
from studio_contracts.local.knowledge import KnowledgeReindexRequest, KnowledgeReindexResult
from studio_contracts.local.provider import IndexState

from tests.knowledge.conftest import build_provider
from tests.knowledge.factories import write


def test_watcher_reuses_the_daemon_polling_lifecycle(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path, indexed=False)
    watcher = VaultIndexWatcher(provider, interval_seconds=60.0)
    assert isinstance(watcher, PollingWatcher)
    assert watcher.stopped is False


async def test_first_poll_indexes_and_a_quiet_poll_does_nothing(
    tmp_path: Path, vault: Path
) -> None:
    provider = build_provider(vault, tmp_path, indexed=False)
    calls: list[KnowledgeReindexRequest] = []
    original = provider.reindex

    def counting(request: KnowledgeReindexRequest) -> KnowledgeReindexResult:
        calls.append(request)
        return original(request)

    provider.reindex = counting
    watcher = VaultIndexWatcher(provider, interval_seconds=0.01)
    await watcher.poll_once()
    assert len(calls) == 1
    assert watcher.index_state is IndexState.READY
    await watcher.poll_once()
    assert len(calls) == 1


async def test_a_change_triggers_a_reindex(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path, indexed=False)
    watcher = VaultIndexWatcher(provider, interval_seconds=0.01)
    await watcher.poll_once()
    write(vault / "global/late.md", "# Late\n\nkeyword platypus\n")
    await watcher.poll_once()
    hits, _ = provider.index.search("platypus", limit=5)
    assert [hit.relative_path for hit in hits] == ["global/late.md"]
    assert provider.status().state.value == "ready"


async def test_the_loop_stops_on_request(tmp_path: Path, vault: Path) -> None:
    provider = build_provider(vault, tmp_path)
    watcher = VaultIndexWatcher(provider, interval_seconds=60.0)
    watcher.request_stop()
    await watcher.run()
    assert watcher.stopped is True


async def test_a_missing_vault_is_refused_not_crashed(tmp_path: Path) -> None:
    provider = build_provider(tmp_path / "absent", tmp_path, indexed=False)
    watcher = VaultIndexWatcher(provider, interval_seconds=0.01)
    await watcher.poll_once()
    assert watcher.last_snapshot is None
