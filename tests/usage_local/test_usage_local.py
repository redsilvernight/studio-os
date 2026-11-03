"""Local usage readers, pricing and scanner (P03 local collection)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from studio_client.outbox import OutboxStore, connect
from studio_client.usage.local import (
    ClaudeCodeLocalReader,
    CodexLocalReader,
    LocalSession,
    LocalUsageScanner,
    OpenCodeLocalReader,
    PriceTable,
    WorkspaceRoot,
    load_price_table,
    project_for_path,
)
from studio_client.usage.local.base import BilledTokens, TaskClaim, UsageEvent
from studio_client.usage.local.pricing import BUNDLED_PRICE_TABLE, table_from_document

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "usage" / "local"
PROJECT = UUID("11111111-1111-4111-8111-111111111111")
TASK = UUID("22222222-2222-4222-8222-222222222222")
MACHINE = UUID("33333333-3333-4333-8333-333333333333")
SINCE = datetime(2026, 10, 1, tzinfo=UTC)


class _Sink:
    def __init__(self) -> None:
        self.items: list[object] = []

    def emit(self, item: object) -> None:
        self.items.append(item)

    def of(self, kind: type) -> list[object]:
        return [item for item in self.items if isinstance(item, kind)]


def _claude_state(sink: _Sink) -> dict[str, object]:
    reader = ClaudeCodeLocalReader(root=FIXTURES / "claude")
    sessions = reader.sessions(SINCE)
    assert len(sessions) == 1
    return reader.read(sessions[0], {}, sink)


def _claude_events(sink: _Sink) -> list[UsageEvent]:
    return [item for item in sink.of(UsageEvent) if isinstance(item, UsageEvent)]


def test_claude_reader_counts_one_usage_per_message_and_reads_the_claim() -> None:
    sink = _Sink()
    state = _claude_state(sink)
    claims = [item for item in sink.of(TaskClaim) if isinstance(item, TaskClaim)]
    events = _claude_events(sink)
    assert claims
    assert {(claim.project_id, claim.task_id) for claim in claims} == {(PROJECT, TASK)}
    assert len(events) == 2
    assert events[0].tokens == BilledTokens(input=100, output=50, cache_read=200, cache_write=20)
    assert events[0].model == "claude-sonnet-4-5"
    assert state["harness_version"] == "2.1.287"
    assert (
        state["offset"]
        == (FIXTURES / "claude" / "studio-os" / "sess-claude-1.jsonl").stat().st_size
    )


def test_claude_reader_is_incremental(tmp_path: Path) -> None:
    source = FIXTURES / "claude" / "studio-os" / "sess-claude-1.jsonl"
    copy = tmp_path / "studio-os" / "sess-copy.jsonl"
    copy.parent.mkdir(parents=True)
    copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    reader = ClaudeCodeLocalReader(root=tmp_path)
    (session,) = reader.sessions(SINCE)
    first = _Sink()
    state = reader.read(session, {}, first)
    assert len(_claude_events(first)) == 2
    second = _Sink()
    state = reader.read(session, state, second)
    assert _claude_events(second) == []
    with copy.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-10-29T10:10:00.000Z",
                    "message": {
                        "id": "msg_3",
                        "model": "claude-sonnet-4-5",
                        "usage": {"input_tokens": 5, "output_tokens": 7},
                    },
                }
            )
            + "\n"
        )
    third = _Sink()
    reader.read(session, state, third)
    (event,) = _claude_events(third)
    assert event.tokens == BilledTokens(input=5, output=7)


def test_codex_reader_maps_inclusive_input_back_to_disjoint_parts() -> None:
    reader = CodexLocalReader(root=FIXTURES / "codex")
    (session,) = reader.sessions(SINCE)
    sink = _Sink()
    state = reader.read(session, {}, sink)
    claims = [item for item in sink.of(TaskClaim) if isinstance(item, TaskClaim)]
    events = _claude_events(sink)
    assert len(claims) == 1
    assert (claims[0].project_id, claims[0].task_id) == (PROJECT, TASK)
    assert [event.tokens for event in events] == [
        BilledTokens(input=650, output=40, cache_read=300, cache_write=50),
        BilledTokens(input=400, output=20, cache_read=100, cache_write=0),
    ]
    assert {event.model for event in events} == {"gpt-6.1-sol"}
    assert state["harness_version"] == "0.163.0"


def _opencode_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            "CREATE TABLE session (id TEXT PRIMARY KEY, directory TEXT, version TEXT);"
            "CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,"
            " time_updated INTEGER, data TEXT);"
            "CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,"
            " time_created INTEGER, data TEXT);"
        )
        connection.execute(
            "INSERT INTO session VALUES (?, ?, ?)",
            ("ses_1", "C:/work/repo", "1.18.3"),
        )
        connection.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
            (
                "part_1",
                "msg_1",
                "ses_1",
                1_791_000_000_000,
                json.dumps(
                    {
                        "type": "tool",
                        "tool": "studio-os_studio_start_work",
                        "state": {"input": {"project_id": str(PROJECT), "task_id": str(TASK)}},
                    }
                ),
            ),
        )
        connection.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            (
                "msg_1",
                "ses_1",
                1_791_000_001_000,
                1_791_000_001_000,
                json.dumps(
                    {
                        "role": "assistant",
                        "modelID": "claude-sonnet-4-5",
                        "providerID": "anthropic",
                        "tokens": {
                            "input": 100,
                            "output": 20,
                            "reasoning": 5,
                            "cache": {"read": 10, "write": 2},
                        },
                        "time": {"created": 1_791_000_001_000, "completed": 1_791_000_002_000},
                    }
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_opencode_reader_emits_deltas_and_claims(tmp_path: Path) -> None:
    database = tmp_path / "opencode.db"
    _opencode_database(database)
    reader = OpenCodeLocalReader(database=database)
    (session,) = reader.sessions(SINCE)
    sink = _Sink()
    state = reader.read(session, {}, sink)
    claims = [item for item in sink.of(TaskClaim) if isinstance(item, TaskClaim)]
    events = _claude_events(sink)
    assert len(claims) == 1
    assert (claims[0].project_id, claims[0].task_id) == (PROJECT, TASK)
    assert [event.tokens for event in events] == [
        BilledTokens(input=100, output=25, cache_read=10, cache_write=2)
    ]
    assert state["harness_version"] == "1.18.3"

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE message SET time_updated = ?, data = ? WHERE id = ?",
            (
                1_791_000_003_000,
                json.dumps(
                    {
                        "role": "assistant",
                        "modelID": "claude-sonnet-4-5",
                        "providerID": "anthropic",
                        "tokens": {
                            "input": 150,
                            "output": 20,
                            "reasoning": 5,
                            "cache": {"read": 10, "write": 2},
                        },
                        "time": {"created": 1_791_000_001_000, "completed": 1_791_000_003_000},
                    }
                ),
                "msg_1",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    update = _Sink()
    reader.read(session, state, update)
    (delta,) = _claude_events(update)
    assert delta.tokens == BilledTokens(input=50, output=0, cache_read=0, cache_write=0)


def test_pricing_estimates_known_models_and_leaves_unknown_alone() -> None:
    tokens = BilledTokens(input=1_000_000, output=1_000_000, cache_read=0, cache_write=0)
    assert BUNDLED_PRICE_TABLE.estimate("claude-sonnet-4-5", tokens) == 18
    assert BUNDLED_PRICE_TABLE.estimate("gpt-6.1-sol", tokens) == 11.25
    assert BUNDLED_PRICE_TABLE.estimate("muse-spark-1.3-contributor", tokens) is None
    assert BUNDLED_PRICE_TABLE.estimate(None, tokens) is None


def test_price_table_override_document_supersedes_a_family(tmp_path: Path) -> None:
    document = {
        "price_list_id": "perso-v1",
        "effective_from": "2026-10-15T00:00:00Z",
        "models": {"claude-sonnet": {"input": 1, "output": 2, "cache_read": 0.1, "cache_write": 1}},
    }
    table = table_from_document(document)
    assert isinstance(table, PriceTable)
    assert table.price_list_id == "perso-v1"
    tokens = BilledTokens(input=1_000_000, output=1_000_000)
    assert table.estimate("claude-sonnet-4-5", tokens) == 3
    assert table.estimate("gpt-6.1-sol", tokens) == 11.25
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_price_table(path).price_list_id == "perso-v1"
    assert load_price_table(tmp_path / "absent.json") is BUNDLED_PRICE_TABLE


def test_project_for_path_prefers_the_longest_root(tmp_path: Path) -> None:
    outer = WorkspaceRoot(path=tmp_path, project_id=PROJECT)
    inner = WorkspaceRoot(path=tmp_path / "repo", project_id=TASK)
    assert project_for_path(str(tmp_path / "repo" / "src"), [outer, inner]) == TASK
    assert project_for_path(str(tmp_path / "other"), [outer, inner]) == PROJECT
    assert project_for_path("C:/elsewhere", [outer, inner]) is None
    assert project_for_path(None, [outer, inner]) is None


def _scanner(store: OutboxStore, root: Path) -> LocalUsageScanner:
    return LocalUsageScanner(
        store=store,
        machine_id=MACHINE,
        readers=(ClaudeCodeLocalReader(root=root),),
        workspace_roots=lambda: (),
        price_table=BUNDLED_PRICE_TABLE,
        lookback=timedelta(days=3650),
        clock=lambda: datetime(2026, 10, 30, tzinfo=UTC),
    )


def _rows(store: OutboxStore) -> list[sqlite3.Row]:
    return list(
        store.connection.execute(
            "SELECT kind, path, payload_json FROM pending_mutations ORDER BY rowid"
        )
    )


async def test_scanner_enqueues_one_entry_per_bucket_then_a_correction(tmp_path: Path) -> None:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    source = FIXTURES / "claude" / "studio-os" / "sess-claude-1.jsonl"
    root = tmp_path / "claude" / "studio-os"
    root.mkdir(parents=True)
    copy = root / "sess-claude-1.jsonl"
    copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    scanner = _scanner(store, tmp_path / "claude")

    report = await scanner.scan()
    assert report.entries == 1
    (row,) = _rows(store)
    assert row["kind"] == "usage.create"
    payload = json.loads(row["payload_json"])
    assert payload["project_id"] == str(PROJECT)
    assert payload["task_id"] == str(TASK)
    assert payload["source_event_id"].startswith("session.studio-local-claude-code.")
    assert payload["tokens_in"] == {"value": 120, "coverage": "measured", "unit": "tokens"}
    assert payload["tokens_cached"]["value"] == 200
    assert payload["tokens_out"]["value"] == 60
    assert payload["cost"]["coverage"] == "estimated"
    assert payload["cost"]["currency"] == "EUR"
    assert payload["cost"]["value"] == "0.001335"
    assert payload["pricing"]["price_list_id"] == "public-eur-2026-10"
    assert payload["provenance"]["harness"] == "claude-code"
    assert payload["provenance"]["model"] == "claude-sonnet-4-5"

    repeat = await scanner.scan()
    assert (repeat.entries, repeat.corrections) == (0, 0)
    assert len(_rows(store)) == 1
    with copy.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-10-29T10:20:00.000Z",
                    "version": "2.1.287",
                    "message": {
                        "id": "msg_4",
                        "model": "claude-sonnet-4-5",
                        "usage": {"input_tokens": 1000, "output_tokens": 0},
                    },
                }
            )
            + "\n"
        )
    second = await scanner.scan()
    assert second.corrections == 1
    kinds = [row["kind"] for row in _rows(store)]
    assert kinds == ["usage.create", "usage.correct"]
    correction = json.loads(_rows(store)[1]["payload_json"])
    assert correction["expected_version"] == 1
    assert correction["source_event_id"] == payload["source_event_id"]


async def test_scanner_falls_back_to_the_workspace_project_without_claim(tmp_path: Path) -> None:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    reader = ClaudeCodeLocalReader(root=tmp_path / "claude")
    root = tmp_path / "claude" / "studio-os"
    root.mkdir(parents=True)
    (root / "sess-plain.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-10-29T11:00:00.000Z",
                "cwd": str(tmp_path / "repo" / "src"),
                "message": {
                    "id": "msg_1",
                    "model": "unknown-model",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    scanner = LocalUsageScanner(
        store=store,
        machine_id=MACHINE,
        readers=(reader,),
        workspace_roots=lambda: (WorkspaceRoot(path=tmp_path / "repo", project_id=PROJECT),),
        price_table=BUNDLED_PRICE_TABLE,
        lookback=timedelta(days=3650),
        clock=lambda: datetime(2026, 10, 30, tzinfo=UTC),
    )
    assert (await scanner.scan()).entries == 1
    (row,) = _rows(store)
    payload = json.loads(row["payload_json"])
    assert payload["project_id"] == str(PROJECT)
    assert payload["task_id"] is None
    assert payload["cost"]["coverage"] == "unknown"
    assert "pricing" not in payload or payload["pricing"] is None


async def test_scanner_ignores_unattributable_sessions(tmp_path: Path) -> None:
    store = OutboxStore(connect(tmp_path / "outbox.sqlite3"))
    root = tmp_path / "claude" / "studio-os"
    root.mkdir(parents=True)
    (root / "sess-plain.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-10-29T11:00:00.000Z",
                "cwd": "C:/elsewhere",
                "message": {"id": "msg_1", "usage": {"input_tokens": 10}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    scanner = _scanner(store, tmp_path / "claude")
    report = await scanner.scan()
    assert report.entries == 0
    assert report.unattributed == 1
    assert _rows(store) == []


def test_daemon_config_exposes_usage_scan_settings() -> None:
    from studio_client.config import ClientConfig

    config = ClientConfig(api_base_url="https://studio.example.test")
    assert config.usage_scan_enabled is True
    assert config.usage_scan_interval_seconds > 0
    assert config.usage_scan_lookback_days > 0


def test_entry_source_ids_fit_the_contract() -> None:
    from studio_client.usage.local.scanner import _bucket_id, _Collected

    reader = ClaudeCodeLocalReader(root=FIXTURES / "claude")
    item = _Collected(
        reader=reader,
        session=LocalSession(
            native_id="rollout-2026-10-22T16-47-26-01a16414-c7c9-7711-972e-43145dbca539",
            location="fixture",
            mtime=SINCE,
        ),
    )
    event = UsageEvent(
        ts=datetime(2026, 10, 29, tzinfo=UTC),
        model="claude-sonnet-4-5",
        provider=None,
        tokens=BilledTokens(input=1),
    )
    bucket = _bucket_id(item, uuid4(), uuid4(), event)
    assert len(bucket) <= 128
    assert bucket[0].isalnum()
