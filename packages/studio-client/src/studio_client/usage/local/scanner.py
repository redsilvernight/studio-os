"""Turn local harness sessions into idempotent ledger entries, per task.

One scan reads each recently touched local session store, attributes every
measured slice to the Studio task the agent had claimed at that moment (falling
back to the workspace's project), and enqueues one ledger entry per
(session, task, model, UTC day) bucket through the existing outbox queue — the
same `usage.create` / `usage.correct` mutations the launch path already uses.

Buckets are recomputed incrementally from the parsed facts: a bucket that grows
while the session is still running is sent again as a correction of the fact
already recorded, never as a second entry. Every write keeps its stable
idempotency key, so a crash between enqueue and local state update replays the
same fact instead of duplicating it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from studio_contracts.usage import (
    CacheTokenScope,
    CostMeasurement,
    DurationMeasurement,
    MeasurementCoverage,
    TokenMeasurement,
    UsageLedgerCorrection,
    UsageLedgerEntryCreate,
    UsageProvenance,
)

from studio_client.outbox import OutboxStore, transaction
from studio_client.usage import UsageWriteQueue
from studio_client.usage.collectors.base import safe_model, safe_tag
from studio_client.usage.local.base import (
    BilledTokens,
    Emission,
    LocalSession,
    LocalUsageReader,
    TaskClaim,
    UsageEvent,
    as_state,
)
from studio_client.usage.local.pricing import PriceTable

logger = logging.getLogger(__name__)

_STATE_PREFIX = "usage.session"
DEFAULT_LOOKBACK = timedelta(days=7)
PARSE_CONCURRENCY = 4


@dataclass(frozen=True)
class WorkspaceRoot:
    path: Path
    project_id: UUID


@dataclass
class ScanReport:
    sessions: int = 0
    parsed: int = 0
    entries: int = 0
    corrections: int = 0
    unattributed: int = 0
    failed: int = 0


@dataclass
class _Collected:
    reader: LocalUsageReader
    session: LocalSession
    reader_state: dict[str, Any] = field(default_factory=dict)
    emissions: list[Emission] = field(default_factory=list)

    def emit(self, item: Emission) -> None:
        self.emissions.append(item)


def project_for_path(cwd: str | None, roots: Sequence[WorkspaceRoot]) -> UUID | None:
    """The workspace project whose root contains `cwd` (longest match wins)."""
    if not cwd or not roots:
        return None
    try:
        candidate = os.path.normcase(os.path.abspath(os.path.normpath(cwd)))
    except (OSError, ValueError):
        return None
    best: tuple[int, UUID] | None = None
    for root in roots:
        try:
            base = os.path.normcase(os.path.abspath(os.path.normpath(root.path)))
        except (OSError, ValueError):
            continue
        if candidate == base or candidate.startswith(f"{base}{os.sep}"):
            if best is None or len(base) > best[0]:
                best = (len(base), root.project_id)
    return None if best is None else best[1]


class LocalUsageScanner:
    def __init__(
        self,
        store: OutboxStore,
        machine_id: UUID,
        readers: Sequence[LocalUsageReader],
        workspace_roots: Callable[[], Sequence[WorkspaceRoot]],
        price_table: PriceTable,
        *,
        lookback: timedelta = DEFAULT_LOOKBACK,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._machine_id = machine_id
        self._readers = tuple(readers)
        self._workspace_roots = workspace_roots
        self._price_table = price_table
        self._lookback = lookback
        self._clock = clock or (lambda: datetime.now(UTC))
        self._queue = UsageWriteQueue(store)

    async def scan(self) -> ScanReport:
        since = self._clock() - self._lookback
        collected = self._discover(since)
        report = ScanReport(sessions=len(collected))
        if not collected:
            return report
        semaphore = asyncio.Semaphore(PARSE_CONCURRENCY)

        async def parse(item: _Collected) -> None:
            async with semaphore:
                try:
                    await asyncio.to_thread(self._parse, item)
                except Exception:  # noqa: BLE001
                    report.failed += 1
                    logger.warning(
                        "local usage parse failed for %s session %s",
                        item.reader.harness,
                        item.session.native_id,
                        exc_info=True,
                    )

        await asyncio.gather(*(parse(item) for item in collected))
        roots = tuple(self._workspace_roots())
        for item in collected:
            if not item.reader_state and not item.emissions:
                continue
            report.parsed += 1
            entries, corrections, unattributed = self._apply(item, roots)
            report.entries += entries
            report.corrections += corrections
            report.unattributed += unattributed
        return report

    def _discover(self, since: datetime) -> list[_Collected]:
        collected: list[_Collected] = []
        for reader in self._readers:
            for session in reader.sessions(since):
                state = self._row_state(reader, session)
                collected.append(
                    _Collected(
                        reader=reader,
                        session=session,
                        reader_state=as_state(state.get("reader")),
                    )
                )
        return collected

    def _parse(self, item: _Collected) -> None:
        item.reader_state = item.reader.read(item.session, item.reader_state, item)

    def _apply(self, item: _Collected, roots: Sequence[WorkspaceRoot]) -> tuple[int, int, int]:
        key = _state_key(item.reader.harness, item.session.location)
        state = self._row_state(item.reader, item.session)
        claim_state = as_state(state.get("claim"))
        current: TaskClaim | None = None
        project_id = _uuid_or_none(claim_state.get("project_id"))
        task_id = _uuid_or_none(claim_state.get("task_id"))
        if project_id is not None and task_id is not None:
            current = TaskClaim(ts=self._clock(), project_id=project_id, task_id=task_id)
        buckets = as_state(state.get("buckets"))
        unattributed = 0
        for emission in item.emissions:
            if isinstance(emission, TaskClaim):
                current = emission
                continue
            project = (
                current.project_id if current is not None else project_for_path(emission.cwd, roots)
            )
            if project is None:
                unattributed += 1
                continue
            bucket_id = _bucket_id(item, project, current.task_id if current else None, emission)
            _accumulate(buckets, bucket_id, item, project, current, emission)
        new_state: dict[str, object] = {
            "reader": item.reader_state,
            "claim": (
                None
                if current is None
                else {"project_id": str(current.project_id), "task_id": str(current.task_id)}
            ),
            "buckets": buckets,
        }
        if new_state == state:
            return 0, 0, unattributed
        with transaction(self._store.connection):
            entries, corrections = self._flush(item, buckets)
            self._store.set_sync_state(key, new_state)
        return entries, corrections, unattributed

    def _flush(self, item: _Collected, buckets: dict[str, Any]) -> tuple[int, int]:
        entries = corrections = 0
        machine = self._machine_id
        for bucket_id, bucket in buckets.items():
            if not isinstance(bucket, dict):
                continue
            totals = _totals(bucket)
            digest = hashlib.sha256(repr(totals).encode("utf-8")).hexdigest()[:16]
            if bucket.get("sent_hash") == digest:
                continue
            version = bucket.get("version")
            version = version if isinstance(version, int) else 0
            provenance = UsageProvenance(
                collector=item.reader.collector_id,
                collector_version=item.reader.collector_version,
                harness=item.reader.harness,
                harness_version=safe_tag(bucket.get("harness_version")),
                provider=safe_tag(bucket.get("provider")),
                model=safe_model(bucket.get("model")),
            )
            start = _parse_iso(bucket.get("first"))
            end = _parse_iso(bucket.get("last"))
            if start is None or end is None:
                continue
            tokens_in = _add_opt(bucket.get("normal"), bucket.get("write"))
            tokens_out = _as_opt_int(bucket.get("out"))
            tokens_cached = _as_opt_int(bucket.get("read"))
            if (tokens_in or 0) + (tokens_out or 0) + (tokens_cached or 0) == 0:
                bucket["sent_hash"] = digest
                continue
            billed = BilledTokens(
                input=_as_opt_int(bucket.get("normal")),
                output=tokens_out,
                cache_read=tokens_cached,
                cache_write=_as_opt_int(bucket.get("write")),
            )
            cost_value = self._price_table.estimate(bucket.get("model"), billed)
            cost = (
                CostMeasurement(
                    value=cost_value,
                    coverage=MeasurementCoverage.ESTIMATED,
                    currency="EUR",
                )
                if cost_value is not None
                else CostMeasurement()
            )
            pricing = self._price_table.pricing_ref() if cost_value is not None else None
            duration = _duration(start, end)
            tokens_in_measure = _token(tokens_in)
            tokens_out_measure = _token(tokens_out)
            tokens_cached_measure = _token(tokens_cached)
            if version == 0:
                entry = UsageLedgerEntryCreate(
                    project_id=UUID(bucket["project_id"]),
                    machine_id=machine,
                    source_event_id=bucket_id,
                    provenance=provenance,
                    period_start=start,
                    period_end=end,
                    task_id=_uuid_or_none(bucket.get("task_id")),
                    tokens_in=tokens_in_measure,
                    tokens_out=tokens_out_measure,
                    tokens_cached=tokens_cached_measure,
                    cached_tokens_scope=CacheTokenScope.ADDITIONAL_TO_INPUT,
                    cost=cost,
                    duration=duration,
                    pricing=pricing,
                )
                self._queue.enqueue_entry(entry, idempotency_key=_create_key(machine, bucket_id))
                entries += 1
            else:
                correction = UsageLedgerCorrection(
                    machine_id=machine,
                    source_event_id=bucket_id,
                    expected_version=version,
                    provenance=provenance,
                    period_start=start,
                    period_end=end,
                    tokens_in=tokens_in_measure,
                    tokens_out=tokens_out_measure,
                    tokens_cached=tokens_cached_measure,
                    cached_tokens_scope=CacheTokenScope.ADDITIONAL_TO_INPUT,
                    cost=cost,
                    duration=duration,
                    pricing=pricing,
                )
                self._queue.enqueue_correction(
                    correction,
                    idempotency_key=_correction_key(machine, bucket_id, version, digest),
                )
                corrections += 1
            bucket["version"] = version + 1
            bucket["sent_hash"] = digest
        return entries, corrections

    def _row_state(self, reader: LocalUsageReader, session: LocalSession) -> dict[str, Any]:
        value = self._store.get_sync_state(_state_key(reader.harness, session.location))
        return as_state(value)


def _state_key(harness: str, location: str) -> str:
    digest = hashlib.sha256(location.encode("utf-8")).hexdigest()[:20]
    return f"{_STATE_PREFIX}.{harness}.{digest}"


def _bucket_id(
    item: _Collected,
    project_id: UUID,
    task_id: UUID | None,
    event: UsageEvent,
) -> str:
    scope = hashlib.sha256(
        f"{project_id}|{task_id or '-'}|{event.model or '-'}".encode()
    ).hexdigest()[:12]
    native = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in item.session.native_id
    )[:48]
    day = event.ts.strftime("%Y%m%d")
    return f"session.{item.reader.collector_id}.{native}.{scope}.{day}"


def _accumulate(
    buckets: dict[str, Any],
    bucket_id: str,
    item: _Collected,
    project_id: UUID,
    claim: TaskClaim | None,
    event: UsageEvent,
) -> None:
    bucket = buckets.get(bucket_id)
    if not isinstance(bucket, dict):
        bucket = {
            "project_id": str(project_id),
            "task_id": None if claim is None else str(claim.task_id),
            "model": event.model,
            "provider": event.provider,
            "harness_version": item.reader_state.get("harness_version"),
            "first": event.ts.isoformat(),
            "last": event.ts.isoformat(),
            "normal": None,
            "out": None,
            "read": None,
            "write": None,
            "version": 0,
            "sent_hash": None,
        }
        buckets[bucket_id] = bucket
    if event.model is not None and bucket.get("model") is None:
        bucket["model"] = event.model
    if event.provider is not None and bucket.get("provider") is None:
        bucket["provider"] = event.provider
    version = item.reader_state.get("harness_version")
    if version is not None:
        bucket["harness_version"] = version
    token_fields = {
        "normal": event.tokens.input,
        "out": event.tokens.output,
        "read": event.tokens.cache_read,
        "write": event.tokens.cache_write,
    }
    for name, value in token_fields.items():
        bucket[name] = _add_opt(bucket.get(name), value)
    first = _parse_iso(bucket.get("first"))
    last = _parse_iso(bucket.get("last"))
    if first is None or event.ts < first:
        bucket["first"] = event.ts.isoformat()
    if last is None or event.ts > last:
        bucket["last"] = event.ts.isoformat()


def _totals(bucket: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(bucket.get(name) for name in ("normal", "out", "read", "write", "first", "last"))


def _token(value: int | None) -> TokenMeasurement:
    if value is None:
        return TokenMeasurement()
    return TokenMeasurement(value=value, coverage=MeasurementCoverage.MEASURED)


def _duration(start: datetime, end: datetime) -> DurationMeasurement:
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return DurationMeasurement()
    return DurationMeasurement(
        value=Decimal(str(seconds)).quantize(Decimal("0.001")),
        coverage=MeasurementCoverage.MEASURED,
    )


def _create_key(machine: UUID, source_event_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"studio:usage-local:{machine}:{source_event_id}")


def _correction_key(machine: UUID, source_event_id: str, version: int, digest: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"studio:usage-local:{machine}:{source_event_id}:{version}:{digest}",
    )


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _uuid_or_none(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _as_opt_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _add_opt(left: object, right: object) -> int | None:
    first = _as_opt_int(left)
    second = _as_opt_int(right)
    if first is None and second is None:
        return None
    return (first or 0) + (second or 0)
