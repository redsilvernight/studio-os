"""Vault writes taken offline, queued through the shared `pending_mutations`
outbox instead of a second, knowledge-specific queue.

Both vault endpoints accept `Idempotency-Key`
(`services/api/src/studio_api/routers/vault.py`), so the UUID generated here is
the row's `idempotency_key` and the server's dedup key: replaying a row never
creates a second note. Deliberately not re-exported from
`studio_client.knowledge` (DEC-0047) — the outbox pulls the HTTP client in and
that package must stay free of network code."""

from __future__ import annotations

from uuid import UUID, uuid4

from studio_contracts.vault import VaultNoteCreate, VaultNoteUpdate

from studio_client.outbox.store import OutboxStore

VAULT_NOTES_PATH = "/api/v1/vault/notes"
VAULT_NOTE_CREATE_KIND = "vault_note.create"
VAULT_NOTE_UPDATE_KIND = "vault_note.update"


class VaultWriteQueue:
    """Enqueue-only: no call leaves the process here. Rows are drained by
    `OutboxReplayer` in `created_at` order, and a creation sent twice under the
    same key is a single note server-side.

    Like every `OutboxStore.enqueue_*`, nothing commits here — the caller owns
    the transaction boundary, so the row can land in the same SQLite
    transaction as the local write it represents (`.claude/rules/offline-sync.md`)."""

    def __init__(self, store: OutboxStore) -> None:
        self._store = store

    def enqueue_create(self, note: VaultNoteCreate) -> str:
        """Queues `POST /api/v1/vault/notes` and returns the idempotency key of
        the row. The key is minted here, never by the API client, so a caller
        retrying the same creation reuses the row already queued instead of
        queueing a second one."""
        key = str(uuid4())
        self._store.enqueue_mutation(
            key,
            VAULT_NOTE_CREATE_KIND,
            "POST",
            VAULT_NOTES_PATH,
            note.model_dump(mode="json"),
        )
        return key

    def enqueue_update(self, note_id: UUID | str, note: VaultNoteUpdate) -> str:
        """Queues `PATCH /api/v1/vault/notes/{id}` and returns the row's
        idempotency key. `expected_version` is mandatory on `VaultNoteUpdate`,
        so the queued body always carries it: a note changed in the meantime is
        refused by the server with `409 version_conflict` rather than silently
        overwritten."""
        key = str(uuid4())
        self._store.enqueue_mutation(
            key,
            VAULT_NOTE_UPDATE_KIND,
            "PATCH",
            f"{VAULT_NOTES_PATH}/{note_id}",
            note.model_dump(mode="json"),
        )
        return key
