from __future__ import annotations

import json
from uuid import UUID

from studio_contracts.usage import UsageLedgerCorrection, UsageLedgerEntryCreate

from studio_client.outbox import OutboxStore

USAGE_PATH = "/api/v1/usage"
USAGE_CORRECTIONS_PATH = f"{USAGE_PATH}/corrections"


class UsageWriteQueue:
    """Queue observations in the caller's SQLite transaction under stable UUIDs."""

    def __init__(self, store: OutboxStore) -> None:
        self._store = store

    def enqueue_entry(self, entry: UsageLedgerEntryCreate, *, idempotency_key: UUID) -> bool:
        return self._enqueue(entry, idempotency_key, "usage.create", USAGE_PATH)

    def enqueue_correction(
        self, correction: UsageLedgerCorrection, *, idempotency_key: UUID
    ) -> bool:
        return self._enqueue(correction, idempotency_key, "usage.correct", USAGE_CORRECTIONS_PATH)

    def _enqueue(
        self,
        observation: UsageLedgerEntryCreate | UsageLedgerCorrection,
        idempotency_key: UUID,
        kind: str,
        path: str,
    ) -> bool:
        key = str(idempotency_key)
        payload = observation.model_dump(mode="json")
        existing = self._store.connection.execute(
            "SELECT kind, method, path, payload_json FROM pending_mutations "
            "WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if existing is not None and (
            existing["kind"] != kind
            or existing["method"] != "POST"
            or existing["path"] != path
            or json.loads(existing["payload_json"]) != payload
        ):
            raise ValueError("idempotency_key_payload_mismatch")
        return self._store.enqueue_mutation(key, kind, "POST", path, payload)
