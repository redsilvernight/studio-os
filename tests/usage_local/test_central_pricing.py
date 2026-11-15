"""Central price lists on the daemon side (DEC-0362): fetch, cache, fallback."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from studio_client.errors import TransportError
from studio_client.usage.local import CentralPriceTables
from studio_client.usage.local.base import BilledTokens
from studio_client.usage.local.pricing import BUNDLED_PRICE_TABLE, table_from_price_list
from studio_contracts.usage import UsagePriceList

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


def _price_list(price_list_id: str = "central-2026-11", **models: str) -> UsagePriceList:
    rates = models or {"claude-opus-5-5": "1"}
    return UsagePriceList.model_validate(
        {
            "id": str(uuid4()),
            "price_list_id": price_list_id,
            "currency": "USD",
            "effective_from": "2026-11-01T00:00:00Z",
            "created_at": "2026-11-01T00:00:00Z",
            "models": {
                prefix.replace("_", "-"): {
                    "input": rate,
                    "output": rate,
                    "cache_read": "0",
                    "cache_write": "0",
                }
                for prefix, rate in rates.items()
            },
        }
    )


class FakeApi:
    def __init__(self, result: UsagePriceList | None | Exception) -> None:
        self.result = result
        self.calls: list[UUID] = []

    async def __call__(self, project_id: UUID) -> UsagePriceList | None:
        self.calls.append(project_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _tables(api: FakeApi, cache: Path, clock: Clock | None = None) -> CentralPriceTables:
    return CentralPriceTables(api, cache, BUNDLED_PRICE_TABLE, clock=clock or Clock())


def test_central_list_is_used_wholesale_longest_prefix_first() -> None:
    table = table_from_price_list(_price_list(claude_opus="2", claude_opus_5_5="1"))
    tokens = BilledTokens(input=1_000_000, output=0, cache_read=0, cache_write=0)
    assert table.estimate("claude-opus-5-5", tokens) == Decimal("1.000000")
    assert table.estimate("claude-opus-4", tokens) == Decimal("2.000000")
    assert table.estimate("gpt-5.5", tokens) is None
    assert table.pricing_ref().price_list_id == "central-2026-11"


def test_refresh_caches_and_survives_offline(tmp_path: Path) -> None:
    project = uuid4()
    api = FakeApi(_price_list())
    asyncio.run(_tables(api, tmp_path).refresh([project, project]))
    assert api.calls == [project]
    assert (tmp_path / f"{project}.json").is_file()

    offline = FakeApi(TransportError("offline"))
    restarted = _tables(offline, tmp_path)
    asyncio.run(restarted.refresh([project]))
    assert restarted.table_for(project).price_list_id == "central-2026-11"


def test_refresh_respects_ttl_and_drops_cache_on_404(tmp_path: Path) -> None:
    project = uuid4()
    clock = Clock()
    api = FakeApi(_price_list())
    tables = _tables(api, tmp_path, clock)
    asyncio.run(tables.refresh([project]))
    asyncio.run(tables.refresh([project]))
    assert len(api.calls) == 1

    api.result = None
    clock.now += timedelta(hours=1)
    asyncio.run(tables.refresh([project]))
    assert len(api.calls) == 2
    assert not (tmp_path / f"{project}.json").exists()
    assert tables.table_for(project) is BUNDLED_PRICE_TABLE


def test_unreadable_cache_falls_back_to_default(tmp_path: Path) -> None:
    project = uuid4()
    (tmp_path / f"{project}.json").write_text("{not json", encoding="utf-8")
    assert _tables(FakeApi(None), tmp_path).table_for(project) is BUNDLED_PRICE_TABLE


def test_bundled_grid_prices_opencode_providers() -> None:
    tokens = BilledTokens(input=1_000_000, output=1_000_000, cache_read=0, cache_write=0)
    for model in (
        "gemini-4-argon",
        "deepseek-v4.1-flash-free",
        "deepseek-v4-pro",
        "kimi-k3",
        "qwen3.8-max",
        "glm-5.3-flash",
        "minimax-m3",
    ):
        assert BUNDLED_PRICE_TABLE.estimate(model, tokens) is not None, model
    assert BUNDLED_PRICE_TABLE.estimate("glm-5.3-flash", tokens) == Decimal("0.650000")
    assert BUNDLED_PRICE_TABLE.estimate("glm-5.3", tokens) == Decimal("5.800000")


def test_scan_runs_even_when_price_refresh_fails() -> None:
    from studio_client.daemon.usage_scan import UsageScanLoop

    stop = asyncio.Event()
    scans: list[int] = []

    class Scanner:
        async def scan(self) -> object:
            scans.append(1)
            stop.set()
            return type("Report", (), {"entries": 0, "corrections": 0, "unattributed": 0})()

    async def failing_refresh() -> None:
        raise RuntimeError("boom")

    loop = UsageScanLoop(
        Scanner(),  # type: ignore[arg-type]
        1,
        stop_event=stop,
        initial_delay_seconds=0,
        before_scan=failing_refresh,
    )
    asyncio.run(loop.run())
    assert scans == [1]
