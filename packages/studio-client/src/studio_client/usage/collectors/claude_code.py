"""Pilot collector for Claude Code headless runs (`claude -p --output-format
json` or `stream-json`).

Certified against Claude Code 2.1.x: the final `{"type": "result", ...}`
document carries `usage` (input, output, cache creation and cache read tokens,
disjoint from each other), `total_cost_usd` (the cost Claude Code computes
itself) and `modelUsage` keyed by model id. Stderr is merged into the captured
output, so the document is searched line by line from the end.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

from studio_contracts.usage import (
    CacheTokenScope,
    CostMeasurement,
    MeasurementCoverage,
    TokenMeasurement,
    UsageMetrics,
)

from studio_client.usage.collectors.base import (
    CollectedUsage,
    CollectorDiagnostic,
    RunObservation,
    measured_duration,
    safe_model,
    safe_tag,
)

COLLECTOR_ID = "studio-claude-code"
COLLECTOR_VERSION = "1.0.0"
CERTIFIED_HARNESS_SERIES = "2.1"

_PROVIDER_ALIASES = {"firstParty": "anthropic"}


def _counter(container: dict[str, Any], key: str) -> tuple[int | None, bool]:
    """`(value, valid)`: an absent key is `(None, True)`, a present but
    non-integer or negative one is `(None, False)`."""
    if key not in container:
        return None, True
    value = container[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, False
    return value, True


def _cost(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount >= 0 else None


def _result_from(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict) and value.get("type") == "result":
        return value
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict) and item.get("type") == "result":
                return item
    return None


def find_result_document(
    output: str, *, truncated: bool = False
) -> tuple[dict[str, Any] | None, CollectorDiagnostic | None]:
    text = output.strip()
    if not text:
        return None, CollectorDiagnostic.OUTPUT_EMPTY
    saw_json = False
    corrupted = False
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    else:
        saw_json = True
        document = _result_from(whole)
        if document is not None:
            return document, None
    if whole is None:
        for line in reversed(text.splitlines()):
            candidate = line.strip()
            if not candidate.startswith(("{", "[")):
                continue
            try:
                parsed = json.loads(candidate)
            except ValueError:
                corrupted = True
                continue
            saw_json = True
            document = _result_from(parsed)
            if document is not None:
                return document, None
    if truncated:
        return None, CollectorDiagnostic.OUTPUT_TRUNCATED
    if corrupted:
        return None, CollectorDiagnostic.CORRUPTED_OUTPUT
    if saw_json:
        return None, CollectorDiagnostic.UNSUPPORTED_SCHEMA
    return None, CollectorDiagnostic.NO_RESULT_DOCUMENT


def _model_and_provider(
    document: dict[str, Any], diagnostics: list[CollectorDiagnostic]
) -> tuple[str | None, str | None]:
    model_usage = document.get("modelUsage")
    if not isinstance(model_usage, dict) or not model_usage:
        return None, None
    entries = {key: value for key, value in model_usage.items() if isinstance(value, dict)}
    if not entries:
        return None, None
    if len(entries) > 1:
        diagnostics.append(CollectorDiagnostic.MULTIPLE_MODELS)
    name = max(entries, key=lambda key: _cost(entries[key].get("costUSD")) or Decimal(0))
    raw_provider = entries[name].get("provider")
    provider = (
        _PROVIDER_ALIASES.get(raw_provider, safe_tag(raw_provider))
        if isinstance(raw_provider, str)
        else None
    )
    return safe_model(name), provider


class ClaudeCodeCollector:
    collector_id = COLLECTOR_ID
    collector_version = COLLECTOR_VERSION
    harness_ids = frozenset({"claude-code"})

    def collect(self, run: RunObservation) -> CollectedUsage:
        diagnostics: list[CollectorDiagnostic] = []
        if run.interrupted:
            diagnostics.append(CollectorDiagnostic.RUN_INTERRUPTED)
        duration = measured_duration(run)
        if duration.coverage is MeasurementCoverage.UNKNOWN:
            diagnostics.append(CollectorDiagnostic.TIMING_MISSING)
        document, reason = find_result_document(run.output, truncated=run.truncated)
        if document is None:
            if reason is not None:
                diagnostics.append(reason)
            return self._result(run, UsageMetrics(duration=duration), diagnostics)

        tokens_in = tokens_out = tokens_cached = TokenMeasurement()
        usage = document.get("usage")
        if not isinstance(usage, dict):
            diagnostics.append(CollectorDiagnostic.USAGE_MISSING)
        else:
            tokens_in, tokens_out, tokens_cached = self._tokens(usage, diagnostics)

        cost = CostMeasurement()
        if "total_cost_usd" not in document:
            diagnostics.append(CollectorDiagnostic.COST_MISSING)
        else:
            amount = _cost(document["total_cost_usd"])
            if amount is None:
                diagnostics.append(CollectorDiagnostic.INVALID_COUNTER)
            else:
                cost = CostMeasurement(
                    value=amount, coverage=MeasurementCoverage.MEASURED, currency="USD"
                )

        if document.get("is_error") is True:
            diagnostics.append(CollectorDiagnostic.HARNESS_ERROR_RESULT)
        model, provider = _model_and_provider(document, diagnostics)
        result = document.get("result")
        metrics = UsageMetrics(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cached=tokens_cached,
            cached_tokens_scope=CacheTokenScope.ADDITIONAL_TO_INPUT,
            cost=cost,
            duration=duration,
        )
        return self._result(
            run,
            metrics,
            diagnostics,
            model=model,
            provider=provider,
            result_text=result if isinstance(result, str) else None,
        )

    @staticmethod
    def _tokens(
        usage: dict[str, Any], diagnostics: list[CollectorDiagnostic]
    ) -> tuple[TokenMeasurement, TokenMeasurement, TokenMeasurement]:
        values: dict[str, int | None] = {}
        invalid = missing = False
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            value, valid = _counter(usage, key)
            invalid |= not valid
            missing |= valid and value is None
            values[key] = value
        if invalid:
            diagnostics.append(CollectorDiagnostic.INVALID_COUNTER)
        if missing:
            diagnostics.append(CollectorDiagnostic.UNSUPPORTED_SCHEMA)

        def measure(value: int | None) -> TokenMeasurement:
            if value is None:
                return TokenMeasurement()
            return TokenMeasurement(value=value, coverage=MeasurementCoverage.MEASURED)

        creation = values["cache_creation_input_tokens"]
        read = values["cache_read_input_tokens"]
        cached = None if creation is None or read is None else creation + read
        return measure(values["input_tokens"]), measure(values["output_tokens"]), measure(cached)

    def _result(
        self,
        run: RunObservation,
        metrics: UsageMetrics,
        diagnostics: list[CollectorDiagnostic],
        *,
        model: str | None = None,
        provider: str | None = None,
        result_text: str | None = None,
    ) -> CollectedUsage:
        return CollectedUsage(
            collector=self.collector_id,
            collector_version=self.collector_version,
            harness=run.harness_id,
            metrics=metrics,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            provider=provider,
            model=model,
            result_text=result_text,
        )
