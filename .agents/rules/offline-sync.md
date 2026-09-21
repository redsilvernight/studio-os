---
name: offline-sync
stable_key: offline-sync
applies_to: ["**/daemon/**/*.py", "**/offline/**/*.py", "**/sync/**/*.py", "**/queue/**/*.py", "**/outbox/**/*.py"]
---

# Offline Queue & Sync

Reference: `TECH/08_OFFLINE_SYNC.md`, `TECH/04_AUTH_SYNC_CONTRACT.md`. The client
must keep working when the VPS or Internet is temporarily unreachable, and must
never assume the other developer's machine is reachable at all.

## Outbox

- Local queue is SQLite: `pending_events`, `pending_mutations`, `pending_markers`, `sync_state`, `multipart_uploads`.
- Every replayable operation carries a stable UUID generated client-side. Enqueue the outbox row in the *same* SQLite transaction as the local write it represents — never a separate, later transaction (that's how ghost/missing rows happen).
- A `UNIQUE` constraint on the idempotency/event UUID is mandatory, not optional hardening.

## Replay

- The server is idempotent on replay: sending the same operation twice must never create a duplicate. Don't build client logic that depends on "it probably won't retry."
- Preserve per-session ordering when the operation sequence matters (e.g. task state transitions).
- Client timestamps are kept, but the server's own `server_timestamp` is authoritative for ordering/conflict decisions.
- Exponential backoff, bounded — do not retry forever at a fixed short interval.
- An operation that fails definitively (not transiently) moves to `dead_letter` and stays visible/inspectable — never silently dropped.

## Boundaries

- Never assume the other machine is reachable directly; Studio OS's entire premise is that the two developer machines never talk to each other directly.
- Critical, non-replayable actions must be explicitly marked as such rather than queued like everything else.
