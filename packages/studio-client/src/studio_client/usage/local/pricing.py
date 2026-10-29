"""Dated EUR price list used to estimate the cost of a local session.

No harness runtime hands over a billed amount for interactive desktop sessions,
so the cost is derived from token counters and a dated, versioned grid — never
from a guess dressed as a fact: the entry carries `estimated` coverage and the
`PricingRef` of the grid it used. An unknown model keeps its cost `unknown`
instead of inheriting a default price.

The bundled grid is a default an operator can supersede without touching code:
`<data_root>/pricing.json` (same shape as `_BUNDLED.window` values) replaces a
model family wholesale, and the effective price list id is echoed in the entry.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from studio_contracts.usage import PricingRef

from studio_client.usage.local.base import BilledTokens

logger = logging.getLogger(__name__)

BUNDLED_PRICE_LIST_ID = "public-eur-2026-10"
BUNDLED_EFFECTIVE_FROM = datetime(2026, 10, 1, tzinfo=UTC)

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelRate:
    """EUR per million tokens, per billing bucket."""

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
    ("claude-opus-4-5", _rate("15", "75", "1.5", "18.75")),
    ("claude-opus-4-1", _rate("15", "75", "1.5", "18.75")),
    ("claude-opus-4", _rate("15", "75", "1.5", "18.75")),
    ("claude-sonnet-5", _rate("3", "15", "0.3", "3.75")),
    ("claude-sonnet-4-5", _rate("3", "15", "0.3", "3.75")),
    ("claude-sonnet-4", _rate("3", "15", "0.3", "3.75")),
    ("claude-haiku-4-5", _rate("1", "5", "0.1", "1.25")),
    ("claude-haiku-3-5", _rate("0.8", "4", "0.08", "1")),
    ("claude-haiku", _rate("0.8", "4", "0.08", "1")),
    ("gpt-6.1", _rate("1.25", "10", "0.125", "1.25")),
    ("gpt-6", _rate("1.25", "10", "0.125", "1.25")),
    ("gpt-5.1-codex", _rate("1.25", "10", "0.125", "1.25")),
    ("gpt-5-codex", _rate("1.25", "10", "0.125", "1.25")),
    ("gpt-5", _rate("1.25", "10", "0.125", "1.25")),
    ("gpt-4.1", _rate("2", "8", "0.5", "2")),
    ("o4-mini", _rate("1.1", "4.4", "0.275", "1.1")),
    ("o3", _rate("2", "8", "0.5", "2")),
    ("claude-opus", _rate("15", "75", "1.5", "18.75")),
    ("claude-sonnet", _rate("3", "15", "0.3", "3.75")),
    ("claude-haiku", _rate("0.8", "4", "0.08", "1")),
)


@dataclass(frozen=True)
class PriceTable:
    price_list_id: str
    effective_from: datetime
    rates: tuple[tuple[str, ModelRate], ...]

    def rate_for(self, model: str | None) -> ModelRate | None:
        if not model:
            return None
        normalized = model.strip().lower()
        for prefix, rate in self.rates:
            if normalized.startswith(prefix):
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
    `pricing.json` (`{"price_list_id", "effective_from", "models": {prefix:
    {"input","output","cache_read","cache_write"}}}`)."""
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
    ordered = (
        *sorted(parsed.items(), key=lambda item: len(item[0]), reverse=True),
        *((prefix, rate) for prefix, rate in _BUNDLED if prefix not in parsed),
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
    )
