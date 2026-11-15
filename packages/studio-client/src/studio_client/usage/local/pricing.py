"""Dated public API price list (USD, DEC-0361) used to estimate the
API-equivalent cost of a local session.

No harness runtime hands over a billed amount for interactive desktop sessions,
so the cost is derived from token counters and a dated, versioned grid — never
from a guess dressed as a fact: the entry carries `estimated` coverage and the
`PricingRef` of the grid it used. An unknown model keeps its cost `unknown`
instead of inheriting a default price. Only models listed on the providers'
public pricing pages are bundled; a family prefix matches a model id only up to
an identifier boundary, so `gpt-5` never prices `gpt-5.7-*`.

Known limits: buckets are daily sums, so per-request tiers (Haiku 5.5 above
100k prompt tokens, long-context and Fast-mode premiums) use the base rate, and
Batch discounts never apply to interactive sessions.

The reference grid is central (DEC-0362): `CentralPriceTables` fetches the
list in force for each followed project from `GET /usage/price-lists/effective`,
caches it under `<data_root>/pricing-cache/` and uses it wholesale, so every
machine prices the same session alike. Offline or before any list is
published, it falls back to the cache, then to the local default: the bundled
grid, optionally superseded by `<data_root>/pricing.json` (`models` shaped like
`ModelRate.to_state()`, optional `currency`, default USD) family by family. The
effective price list id is echoed in the entry either way.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from studio_contracts.usage import PricingRef, UsagePriceList

from studio_client.errors import StudioApiError
from studio_client.usage.local.base import BilledTokens

logger = logging.getLogger(__name__)

BUNDLED_PRICE_LIST_ID = "public-usd-2026-11b"
BUNDLED_CURRENCY = "USD"
BUNDLED_EFFECTIVE_FROM = datetime(2026, 11, 15, tzinfo=UTC)

_MILLION = Decimal(1_000_000)
_ID_BOUNDARIES = frozenset("-@[:/")
_CURRENCY = re.compile(r"[A-Z]{3}")


@dataclass(frozen=True)
class ModelRate:
    """Price per million tokens in the table currency, per billing bucket."""

    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal

    def cost(self, tokens: BilledTokens) -> Decimal:
        total = Decimal(0)
        total += _amount(tokens.input, self.input)
        total += _amount(tokens.output, self.output)
        total += _amount(tokens.cache_read, self.cache_read)
        total += _amount(tokens.cache_write, self.cache_write)
        return total

    def to_state(self) -> dict[str, str]:
        return {
            "input": str(self.input),
            "output": str(self.output),
            "cache_read": str(self.cache_read),
            "cache_write": str(self.cache_write),
        }


def _amount(tokens: int | None, rate: Decimal) -> Decimal:
    if not tokens:
        return Decimal(0)
    return (Decimal(tokens) / _MILLION) * rate


def _rate(input: str, output: str, cache_read: str, cache_write: str) -> ModelRate:
    return ModelRate(
        input=Decimal(input),
        output=Decimal(output),
        cache_read=Decimal(cache_read),
        cache_write=Decimal(cache_write),
    )


# Ordered longest-prefix-first: the first matching family wins.
_BUNDLED: tuple[tuple[str, ModelRate], ...] = (
    ("claude-fable-5-1", _rate("10", "50", "0.25", "12.5")),
    ("claude-fable-5", _rate("10", "50", "1", "12.5")),
    ("claude-mythos-5-1", _rate("10", "50", "0.25", "12.5")),
    ("claude-mythos-5", _rate("10", "50", "1", "12.5")),
    ("claude-opus-5-5", _rate("4", "20", "0.2", "5")),
    ("claude-opus-5", _rate("5", "25", "0.5", "6.25")),
    ("claude-opus-4-8", _rate("5", "25", "0.5", "6.25")),
    ("claude-opus-4-7", _rate("5", "25", "0.5", "6.25")),
    ("claude-opus-4-6", _rate("5", "25", "0.5", "6.25")),
    ("claude-opus-4-5", _rate("5", "25", "0.5", "6.25")),
    ("claude-opus-4", _rate("15", "75", "1.5", "18.75")),
    ("claude-sonnet-5-5", _rate("2", "10", "0.1", "2.5")),
    ("claude-sonnet-5", _rate("2", "10", "0.2", "2.5")),
    ("claude-sonnet-4", _rate("3", "15", "0.3", "3.75")),
    # shortcut: Haiku 5.5 costs 5x above 100k prompt tokens; daily buckets use the base tier.
    ("claude-haiku-5-5", _rate("0.1", "0.5", "0.01", "0.125")),
    ("claude-haiku-4-5", _rate("1", "5", "0.1", "1.25")),
    ("claude-haiku-3-5", _rate("0.8", "4", "0.08", "1")),
    ("gpt-6.1-sol", _rate("2", "10", "0.1", "2")),
    ("gpt-6.1-terra", _rate("1", "5", "0.05", "1")),
    ("gpt-6-astra", _rate("10", "50", "1", "10")),
    ("gpt-6-sol", _rate("2", "10", "0.2", "2")),
    ("gpt-6-luna", _rate("0.1", "0.5", "0.01", "0.1")),
    ("gpt-5.6-sol", _rate("4", "20", "0.4", "4")),
    ("gpt-5.6-terra", _rate("2", "12", "0.2", "2")),
    ("gpt-5.6-luna", _rate("0.2", "1.2", "0.02", "0.2")),
    ("gpt-5.6-cyber", _rate("12.5", "75", "1.25", "12.5")),
    ("gpt-5.5-pro", _rate("30", "180", "30", "30")),
    ("gpt-5.5-cyber", _rate("12.5", "75", "1.25", "12.5")),
    ("gpt-5.5", _rate("5", "30", "0.5", "5")),
    ("gpt-5.4-mini", _rate("0.75", "4.5", "0.075", "0.75")),
    ("gpt-5.4-nano", _rate("0.2", "1.25", "0.02", "0.2")),
    ("gpt-5.4", _rate("2.5", "15", "0.25", "2.5")),
    ("gpt-5.3-codex", _rate("1.75", "14", "0.175", "1.75")),
    ("gpt-5.2", _rate("1.75", "14", "0.175", "1.75")),
    ("gpt-5.1", _rate("1.25", "10", "0.125", "1.25")),
    ("gpt-5-mini", _rate("0.25", "2", "0.025", "0.25")),
    ("gpt-5-nano", _rate("0.05", "0.4", "0.005", "0.05")),
    ("gpt-5", _rate("1.25", "10", "0.125", "1.25")),
    ("gpt-4.1-mini", _rate("0.4", "1.6", "0.1", "0.4")),
    ("gpt-4.1", _rate("2", "8", "0.5", "2")),
    ("gpt-4o-mini", _rate("0.15", "0.6", "0.075", "0.15")),
    ("gpt-4o", _rate("2.5", "10", "1.25", "2.5")),
    ("o3-pro", _rate("20", "80", "20", "20")),
    ("o3", _rate("2", "8", "0.5", "2")),
    # OpenCode providers. shortcut: public list prices as reported by price
    # aggregators on 2026-11-15, peak tier, cache read at the published cached
    # rate or 10% of input when none is listed; a central list supersedes them.
    ("gemini-4-argon", _rate("2", "10", "0.1", "2")),
    ("gemini-3.8-flash", _rate("0.75", "3.75", "0.075", "0.75")),
    ("deepseek-v4.1-flash", _rate("0.3", "1.2", "0.03", "0.3")),
    ("deepseek-v4-pro", _rate("1.32", "3.96", "0.132", "1.32")),
    ("kimi-k3", _rate("3", "15", "0.3", "3")),
    ("qwen3.8-max", _rate("2", "6", "0.25", "2")),
    ("glm-5.3-flashx", _rate("0.37", "1.25", "0.037", "0.37")),
    ("glm-5.3-flash", _rate("0.15", "0.5", "0.015", "0.15")),
    ("glm-5.3", _rate("1.4", "4.4", "0.26", "1.4")),
    ("minimax-m3", _rate("0.3", "1.2", "0.03", "0.3")),
)


@dataclass(frozen=True)
class PriceTable:
    price_list_id: str
    effective_from: datetime
    rates: tuple[tuple[str, ModelRate], ...]
    currency: str = BUNDLED_CURRENCY

    def rate_for(self, model: str | None) -> ModelRate | None:
        if not model:
            return None
        normalized = model.strip().lower()
        for prefix, rate in self.rates:
            if normalized.startswith(prefix) and (
                len(normalized) == len(prefix) or normalized[len(prefix)] in _ID_BOUNDARIES
            ):
                return rate
        return None

    def estimate(self, model: str | None, tokens: BilledTokens) -> Decimal | None:
        rate = self.rate_for(model)
        if rate is None:
            return None
        if tokens.total() is None:
            return None
        quantized = rate.cost(tokens).quantize(Decimal("0.000001"))
        return quantized if quantized >= 0 else None

    def pricing_ref(self) -> PricingRef:
        return PricingRef(
            price_list_id=self.price_list_id,
            effective_from=self.effective_from,
        )


BUNDLED_PRICE_TABLE = PriceTable(
    price_list_id=BUNDLED_PRICE_LIST_ID,
    effective_from=BUNDLED_EFFECTIVE_FROM,
    rates=_BUNDLED,
)


def load_price_table(overrides: Path | None = None) -> PriceTable:
    """The bundled grid, optionally superseded family by family by a local
    `pricing.json` (`{"price_list_id", "effective_from", "currency", "models":
    {prefix: {"input","output","cache_read","cache_write"}}}`). A grid in
    another currency than the bundled one replaces it whole: bundled USD rates
    are never mixed into it."""
    if overrides is None or not overrides.is_file():
        return BUNDLED_PRICE_TABLE
    try:
        raw: Any = json.loads(overrides.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("pricing.json unreadable; keeping the bundled price list")
        return BUNDLED_PRICE_TABLE
    return table_from_document(raw) or BUNDLED_PRICE_TABLE


def table_from_document(value: object) -> PriceTable | None:
    if not isinstance(value, Mapping):
        return None
    models = value.get("models")
    if not isinstance(models, Mapping):
        return None
    parsed: dict[str, ModelRate] = {}
    for raw_prefix, raw_rate in models.items():
        if not isinstance(raw_prefix, str) or not isinstance(raw_rate, Mapping):
            continue
        try:
            parsed[raw_prefix.strip().lower()] = _rate(
                str(raw_rate.get("input", 0)),
                str(raw_rate.get("output", 0)),
                str(raw_rate.get("cache_read", 0)),
                str(raw_rate.get("cache_write", 0)),
            )
        except ArithmeticError:
            continue
    if not parsed:
        return None
    currency = value.get("currency", BUNDLED_CURRENCY)
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        return None
    ordered = (
        *sorted(parsed.items(), key=lambda item: len(item[0]), reverse=True),
        *(
            (prefix, rate)
            for prefix, rate in _BUNDLED
            if prefix not in parsed and currency == BUNDLED_CURRENCY
        ),
    )
    price_list_id = value.get("price_list_id")
    price_list_id = price_list_id if isinstance(price_list_id, str) and price_list_id else "custom"
    effective = value.get("effective_from")
    effective_from = (
        datetime.fromisoformat(str(effective).replace("Z", "+00:00"))
        if isinstance(effective, str)
        else BUNDLED_EFFECTIVE_FROM
    )
    return PriceTable(
        price_list_id=price_list_id,
        effective_from=effective_from,
        rates=ordered,
        currency=currency,
    )


def table_from_price_list(price_list: UsagePriceList) -> PriceTable:
    """A central list is used as published: never completed with bundled
    rates, whose version depends on the client build (DEC-0362)."""
    rates = sorted(
        (
            (
                prefix,
                ModelRate(
                    input=rate.input,
                    output=rate.output,
                    cache_read=rate.cache_read,
                    cache_write=rate.cache_write,
                ),
            )
            for prefix, rate in price_list.models.items()
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    return PriceTable(
        price_list_id=price_list.price_list_id,
        effective_from=price_list.effective_from,
        rates=tuple(rates),
        currency=price_list.currency,
    )


PriceListFetcher = Callable[[UUID], Awaitable[UsagePriceList | None]]


class CentralPriceTables:
    """Per-project price tables from the API, cached on disk (DEC-0362).

    `refresh` asks the API at most once per `ttl` per project; `None` from the
    fetcher (no list in force) drops the cache, an API error keeps it.
    `table_for` never touches the network: memory, then disk cache, then the
    local default. shortcut: the list is the one in force at refresh time,
    not at the entry's period; good enough while lists change monthly."""

    def __init__(
        self,
        fetch: PriceListFetcher,
        cache_dir: Path,
        default: PriceTable,
        *,
        ttl: timedelta = timedelta(hours=1),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetch = fetch
        self._cache_dir = cache_dir
        self._default = default
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tables: dict[UUID, PriceTable | None] = {}
        self._fetched_at: dict[UUID, datetime] = {}

    def _cache_path(self, project_id: UUID) -> Path:
        return self._cache_dir / f"{project_id}.json"

    async def refresh(self, project_ids: Iterable[UUID]) -> None:
        now = self._clock()
        for project_id in dict.fromkeys(project_ids):
            fetched = self._fetched_at.get(project_id)
            if fetched is not None and now - fetched < self._ttl:
                continue
            try:
                price_list = await self._fetch(project_id)
            except StudioApiError as exc:
                logger.info("price list unavailable for %s (%s); keeping cache", project_id, exc)
                continue
            self._fetched_at[project_id] = now
            path = self._cache_path(project_id)
            if price_list is None:
                self._tables[project_id] = None
                path.unlink(missing_ok=True)
                continue
            self._tables[project_id] = table_from_price_list(price_list)
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(price_list.model_dump_json(), encoding="utf-8")
                os.replace(temporary, path)
            except OSError:
                logger.warning("price list cache not writable: %s", path)

    def table_for(self, project_id: UUID) -> PriceTable:
        if project_id not in self._tables:
            self._tables[project_id] = self._load_cache(project_id)
        return self._tables[project_id] or self._default

    def _load_cache(self, project_id: UUID) -> PriceTable | None:
        path = self._cache_path(project_id)
        if not path.is_file():
            return None
        try:
            price_list = UsagePriceList.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            logger.warning("price list cache unreadable: %s", path)
            return None
        return table_from_price_list(price_list)
