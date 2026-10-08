"""Vault writes queued while offline (`knowledge/vault_outbox.py`) and drained
by `OutboxReplayer`: a network cut keeps the row and its order, a replayed row
resends the same `Idempotency-Key` so the server never sees two notes, and the
two refusals a replay can never get past are dead-lettered with a reason a human
can act on."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from studio_client.api_client import StudioApiClient
from studio_client.config import ClientConfig
from studio_client.knowledge.vault_outbox import VAULT_NOTES_PATH, VaultWriteQueue
from studio_client.outbox import OutboxReplayer, OutboxStore, OutboxTable, connect, transaction
from studio_client.outbox.replay import VAULT_SECRET_DETECTED, VAULT_VERSION_CONFLICT
from studio_client.retry import RetryPolicy
from studio_client.tokens import MemoryTokenStore
from studio_contracts.vault import (
    VaultNoteCreate,
    VaultNoteType,
    VaultNoteUpdate,
    VaultScope,
)

NOTE_ID = uuid4()


def _create(slug: str = "offline-note", body: str = "ecrit hors ligne") -> VaultNoteCreate:
    return VaultNoteCreate(
        scope=VaultScope.STUDIO,
        slug=slug,
        note_type=VaultNoteType.NOTE,
        title="Note hors ligne",
        summary="",
        body=body,
        tags=["offline"],
    )


def _update(expected_version: int = 1, body: str = "corrige") -> VaultNoteUpdate:
    return VaultNoteUpdate(expected_version=expected_version, body=body)


def _note_json(*, version: int, slug: str = "offline-note") -> dict[str, Any]:
    return {
        "id": str(NOTE_ID),
        "scope": VaultScope.STUDIO.value,
        "project_id": None,
        "slug": slug,
        "readable_id": None,
        "note_type": VaultNoteType.NOTE.value,
        "title": "Note hors ligne",
        "summary": "",
        "body": "corrige",
        "status": "draft",
        "tags": ["offline"],
        "links": [],
        "anchors": [],
        "content_hash": "0" * 64,
        "author_type": "user",
        "author_id": str(uuid4()),
        "version": version,
        "created_at": "2026-10-07T00:00:00Z",
        "updated_at": "2026-10-07T00:00:00Z",
    }


class FakeVaultServer:
    """The vault notes endpoint as an `Idempotency-Key`-aware store: a key it
    already answered is replayed verbatim, so a client that resends the same row
    never produces a second note."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.bodies: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.offline = False
        self.refusal: tuple[int, dict[str, Any]] | None = None
        self._answered: dict[str, httpx.Response] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("Idempotency-Key")
        self.calls.append((request.method, request.url.path, key))
        self.bodies.append(json.loads(request.content))
        if self.offline:
            raise httpx.ConnectError("network is down", request=request)
        if self.refusal is not None:
            status, body = self.refusal
            return httpx.Response(status, json={"detail": body})
        if key is not None and key in self._answered:
            return self._answered[key]
        note = _note_json(version=1 if request.method == "POST" else 2)
        response = httpx.Response(201 if request.method == "POST" else 200, json=note)
        if key is not None:
            self._answered[key] = response
        if request.method == "POST":
            self.created.append(note)
        return response


def _client(server: FakeVaultServer) -> StudioApiClient:
    tokens = MemoryTokenStore()
    tokens.set_token("http://test", "test-token")
    config = ClientConfig(api_base_url="http://test", machine_id=uuid4(), max_attempts=1)
    return StudioApiClient(config, tokens, transport=httpx.MockTransport(server.handler))


def _queue(store: OutboxStore) -> VaultWriteQueue:
    return VaultWriteQueue(store)


def _store(path: Path) -> OutboxStore:
    return OutboxStore(connect(path))


def _pending(store: OutboxStore) -> list[Any]:
    return store.list_pending(OutboxTable.MUTATIONS, ready_only=False)


def _dead_letters(store: OutboxStore) -> list[Any]:
    return store.connection.execute("SELECT * FROM dead_letter ORDER BY failed_at").fetchall()


def _make_rows_ready(store: OutboxStore) -> None:
    """A row backoff-rescheduled by a transient failure is not `ready` yet; the
    backoff elapsing is what makes the next pass send it."""
    store.connection.execute(
        "UPDATE pending_mutations SET next_attempt_at = ?",
        ((datetime.now(UTC).replace(year=2000)).isoformat(),),
    )
    store.connection.commit()


async def test_queued_vault_writes_replay_in_enqueue_order_under_their_own_key(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    queue = _queue(store)
    with transaction(store.connection):
        create_key = queue.enqueue_create(_create())
        update_key = queue.enqueue_update(NOTE_ID, _update(expected_version=3))

    server = FakeVaultServer()
    async with _client(server) as client:
        outcome = await OutboxReplayer(store, client, RetryPolicy(max_attempts=1)).replay_ready()

    assert outcome.succeeded == 2
    assert outcome.dead_lettered == 0
    assert server.calls == [
        ("POST", VAULT_NOTES_PATH, create_key),
        ("PATCH", f"{VAULT_NOTES_PATH}/{NOTE_ID}", update_key),
    ]
    assert server.bodies[1]["expected_version"] == 3
    assert server.bodies[1]["body"] == "corrige"
    assert _pending(store) == []


async def test_network_cut_keeps_the_row_and_replays_it_once_the_network_is_back(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    queue = _queue(store)
    with transaction(store.connection):
        create_key = queue.enqueue_create(_create())
        update_key = queue.enqueue_update(NOTE_ID, _update())

    server = FakeVaultServer()
    server.offline = True
    async with _client(server) as client:
        replayer = OutboxReplayer(store, client, RetryPolicy(max_attempts=1))
        outcome = await replayer.replay_ready()

    assert outcome.succeeded == 0
    assert outcome.stopped_on_transient_error is True
    pending = _pending(store)
    assert [row.id for row in pending] == [create_key, update_key]
    assert pending[0].attempt_count == 1
    assert "transport error" in str(pending[0].last_error)
    assert pending[1].attempt_count == 0
    assert server.calls == [("POST", VAULT_NOTES_PATH, create_key)]

    _make_rows_ready(store)
    server.offline = False
    async with _client(server) as client:
        outcome = await OutboxReplayer(store, client, RetryPolicy(max_attempts=1)).replay_ready()

    assert outcome.succeeded == 2
    assert outcome.stopped_on_transient_error is False
    assert server.calls == [
        ("POST", VAULT_NOTES_PATH, create_key),
        ("POST", VAULT_NOTES_PATH, create_key),
        ("PATCH", f"{VAULT_NOTES_PATH}/{NOTE_ID}", update_key),
    ]
    assert len(server.created) == 1
    assert _pending(store) == []


async def test_a_row_replayed_twice_resends_the_same_key_and_creates_one_note(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    queue = _queue(store)
    create = _create()
    with transaction(store.connection):
        create_key = queue.enqueue_create(create)

    server = FakeVaultServer()
    async with _client(server) as client:
        first = await OutboxReplayer(store, client, RetryPolicy(max_attempts=1)).replay_ready()
    assert first.succeeded == 1

    with transaction(store.connection):
        store.enqueue_mutation(
            create_key,
            "vault_note.create",
            "POST",
            VAULT_NOTES_PATH,
            create.model_dump(mode="json"),
        )

    async with _client(server) as client:
        second = await OutboxReplayer(store, client, RetryPolicy(max_attempts=1)).replay_ready()

    assert second.succeeded == 1
    assert [call[2] for call in server.calls] == [create_key, create_key]
    assert len(server.created) == 1
    assert _pending(store) == []


async def test_a_stale_vault_write_is_dead_lettered_as_a_version_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    queue = _queue(store)
    with transaction(store.connection):
        update_key = queue.enqueue_update(NOTE_ID, _update(expected_version=1))

    server = FakeVaultServer()
    server.refusal = (409, {"error_code": "version_conflict", "server_version": 4})
    async with _client(server) as client:
        outcome = await OutboxReplayer(store, client, RetryPolicy(max_attempts=1)).replay_ready()

    assert outcome.vault_conflicts == [update_key]
    assert outcome.vault_secret_rejections == []
    assert outcome.dead_lettered == 1
    assert outcome.stopped_on_transient_error is False
    assert _pending(store) == []
    dead = _dead_letters(store)
    assert len(dead) == 1
    assert dead[0]["id"] == update_key
    assert dead[0]["source_table"] == OutboxTable.MUTATIONS.value
    assert dead[0]["error"].startswith(f"{VAULT_VERSION_CONFLICT} note={update_key}: ")
    assert "version_conflict" in dead[0]["error"]


async def test_a_secret_scanner_rejection_is_dead_lettered_and_reported(tmp_path: Path) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    queue = _queue(store)
    with transaction(store.connection):
        create_key = queue.enqueue_create(_create())

    server = FakeVaultServer()
    server.refusal = (
        422,
        {
            "error_code": "secret_detected",
            "details": [{"field": "body", "pattern": "aws_access_key_id"}],
        },
    )
    async with _client(server) as client:
        outcome = await OutboxReplayer(store, client, RetryPolicy(max_attempts=1)).replay_ready()

    assert outcome.vault_secret_rejections == [create_key]
    assert outcome.vault_conflicts == []
    assert outcome.dead_lettered == 1
    assert _pending(store) == []
    dead = _dead_letters(store)
    assert len(dead) == 1
    assert dead[0]["error"].startswith(f"{VAULT_SECRET_DETECTED} note={create_key}: ")
    assert "secret_detected" in dead[0]["error"]


async def test_a_version_conflict_outside_the_vault_is_not_reported_as_a_vault_conflict(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "outbox.sqlite3")
    task_id = uuid4()
    with transaction(store.connection):
        store.enqueue_mutation(
            str(uuid4()),
            "task.update",
            "PATCH",
            f"/api/v1/tasks/{task_id}",
            {"expected_version": 1, "status": "in_progress"},
        )

    server = FakeVaultServer()
    server.refusal = (409, {"error_code": "version_conflict", "server_version": 4})
    async with _client(server) as client:
        outcome = await OutboxReplayer(store, client, RetryPolicy(max_attempts=1)).replay_ready()

    assert outcome.dead_lettered == 1
    assert outcome.vault_conflicts == []
    assert outcome.vault_secret_rejections == []
    assert not str(_dead_letters(store)[0]["error"]).startswith(VAULT_VERSION_CONFLICT)


async def test_the_queue_shares_the_transaction_of_the_local_write_it_queues(
    tmp_path: Path,
) -> None:
    """A row enqueued outside the local write's transaction must not survive a
    rollback of that write: the vault write and its outbox row commit or vanish
    together (`.claude/rules/offline-sync.md`)."""
    store = _store(tmp_path / "outbox.sqlite3")
    queue = _queue(store)

    rolled_back: UUID | None = None
    try:
        with transaction(store.connection):
            rolled_back = UUID(queue.enqueue_create(_create()))
            raise RuntimeError("local vault write failed")
    except RuntimeError:
        pass

    assert _pending(store) == []
    with transaction(store.connection):
        kept = queue.enqueue_create(_create())
    assert [row.id for row in _pending(store)] == [kept]
    assert rolled_back != UUID(kept)
