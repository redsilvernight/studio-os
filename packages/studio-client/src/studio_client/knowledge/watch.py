from __future__ import annotations

import asyncio
from collections.abc import Callable

from studio_contracts.local.knowledge import KnowledgeReindexMode, KnowledgeReindexRequest
from studio_contracts.local.provider import IndexState

from studio_client.knowledge.index import IndexSnapshot
from studio_client.knowledge.provider import VaultKnowledgeProvider
from studio_client.knowledge.vault import vault_fingerprint
from studio_client.watchers.base import PollingWatcher, SleepFn

DEFAULT_VAULT_POLL_SECONDS = 30.0


class VaultIndexWatcher(PollingWatcher):
    """Keeps the derived index in step with the vault.

    It reuses the daemon's existing polling lifecycle (`PollingWatcher`) instead
    of starting a second global filesystem surveillance: one bounded poll
    compares the cheap vault fingerprint, and only a real change triggers an
    incremental reindex. A missing or unreadable vault simply refuses the
    reindex and is retried on the next poll — never a crash, never a silent
    deletion of the index."""

    def __init__(
        self,
        provider: VaultKnowledgeProvider,
        *,
        interval_seconds: float = DEFAULT_VAULT_POLL_SECONDS,
        sleep: SleepFn | None = None,
        fingerprint: Callable[[], str] | None = None,
        full_on_first_poll: bool = True,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds, sleep=sleep)
        self._provider = provider
        self._fingerprint = fingerprint or self._default_fingerprint
        self._full_on_first_poll = full_on_first_poll
        self._last: str | None = None
        self._last_snapshot: IndexSnapshot | None = None

    def _default_fingerprint(self) -> str:
        return vault_fingerprint(self._provider.vault_root)

    @property
    def last_snapshot(self) -> IndexSnapshot | None:
        return self._last_snapshot

    @property
    def index_state(self) -> IndexState | None:
        return None if self._last_snapshot is None else self._last_snapshot.state

    async def poll_once(self) -> None:
        fingerprint = await asyncio.to_thread(self._fingerprint)
        if fingerprint == self._last:
            return
        mode = (
            KnowledgeReindexMode.FULL_REBUILD
            if self._last is None and self._full_on_first_poll
            else KnowledgeReindexMode.INCREMENTAL
        )
        result = await asyncio.to_thread(
            self._provider.reindex,
            KnowledgeReindexRequest(workspace_id=self._provider.workspace_id, mode=mode),
        )
        if not result.accepted:
            return
        self._last = fingerprint
        self._last_snapshot = await asyncio.to_thread(
            self._provider.index.snapshot, self._provider.vault_root
        )
