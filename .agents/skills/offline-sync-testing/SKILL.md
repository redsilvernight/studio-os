---
name: offline-sync-testing
description: Validation checklist for the offline queue, idempotent replay, resource claims, and resumable Studio Transfer, per TECH/10_TEST_ACCEPTANCE.md. Use when testing a change that touches the daemon, sync queue, claims, or transfers — or delegate this to the studio-tester agent for an isolated Tier-3 pass.
---

# Offline & Sync Testing

A change touching the offline queue, claims, or transfers is not verified by
reading the code — these are exactly the paths that only fail under interruption,
concurrency, or replay. Reference: `TECH/10_TEST_ACCEPTANCE.md`.

## Backend

- Auth/permissions on the touched endpoint(s).
- Heartbeat and offline-detection thresholds.
- Task lifecycle transitions (including via `claim`/`release`).
- Claim TTL expiry and overlap/conflict detection (folder vs. descendant file).
- Decision creation/listing.
- **Event idempotency**: submit the same `event_id` twice — assert no duplicate was created and the response matches the first result.
- ProjectState aggregation reflects the change.
- Any touched MCP tool, called directly.

## Transfers

- Tiny file (≈1 KB) end-to-end.
- Large file (≈1 GB) via multipart.
- Interrupt the upload at ~50% completion, then resume — assert already-completed parts are not re-uploaded.
- Expired pre-signed URL is rejected, not silently accepted.
- Wrong hash on complete is rejected.
- Quota exceeded is rejected before signing.
- Deletion and expiration behave as specified.
- Range-request download resumes correctly.

## Client / daemon

- Daemon restart: queued operations survive and still replay.
- Queue persistence across process restart, not just in-memory.
- Reconnection after a simulated network cut.
- Git/Godot watcher still detects changes correctly (if touched).
- CLI output matches the expected command contract.
- Graphify/Obsidian adapters (if touched) respect the read/write boundary in `AI/02_AGENT_RULES.md`.

## End-to-end (when the change is significant)

Simulate two machines on two different networks: one task per machine,
concurrent claims on overlapping resources, an AIWorkLog entry, a file transfer,
a network cut mid-task and resume, and a daily review pass — per the "Definition
de done globale" in `TECH/10_TEST_ACCEPTANCE.md`.

## Reporting

State plainly what was actually executed vs. simulated vs. not tested (e.g. "no
live Postgres/MinIO in this environment — multipart resume verified by code
inspection only, not exercised").
