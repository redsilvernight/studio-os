"""The set of harness adapters a Desktop knows. Adding a harness is writing a
HarnessAdapter and registering it here — nothing else changes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from studio_client.harness.base import Detection, HarnessAdapter, HarnessContext
from studio_client.harness.claude_code import ClaudeCodeAdapter
from studio_client.harness.opencode import OpenCodeAdapter


class HarnessRegistry:
    def __init__(self, adapters: list[HarnessAdapter] | None = None) -> None:
        self._adapters: dict[str, HarnessAdapter] = {}
        for adapter in default_adapters() if adapters is None else adapters:
            self.register(adapter)

    def register(self, adapter: HarnessAdapter) -> None:
        if adapter.adapter_id in self._adapters:
            raise ValueError("an adapter with this id is already registered")
        self._adapters[adapter.adapter_id] = adapter

    def adapters(self) -> list[HarnessAdapter]:
        return list(self._adapters.values())

    def get(self, adapter_id: str) -> HarnessAdapter | None:
        return self._adapters.get(adapter_id)

    def detect_all(self, ctx: HarnessContext) -> list[tuple[HarnessAdapter, Detection]]:
        adapters = self.adapters()
        if not adapters:
            return []
        with ThreadPoolExecutor(max_workers=len(adapters)) as pool:
            detections = list(pool.map(lambda adapter: adapter.detect(ctx), adapters))
        return list(zip(adapters, detections, strict=True))


def default_adapters() -> list[HarnessAdapter]:
    return [ClaudeCodeAdapter(), OpenCodeAdapter()]
