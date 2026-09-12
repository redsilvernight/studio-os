---
paths: ["**/schemas/**/*.py", "**/contracts/**/*.py", "**/*_contract*.py", "**/*contract*.py", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/02_API_CONTRACT.md", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/03_EVENT_CONTRACT.md", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/04_AUTH_SYNC_CONTRACT.md", "docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/05_DATA_MODEL.md"]
---

# Contract Discipline

Studio OS is built as two parallel tracks (Bloc A: Cloud/Core, Bloc B: Local
Client) that only stay compatible because these four contracts are treated as
frozen unless explicitly versioned. Dispatch `contract-guardian` before merging a
change that touches this file or these paths — do not rely on judgment alone.

## Rules

- Adding an optional field, a new endpoint, or a new event type that old clients can ignore is safe.
- Removing/renaming a field, changing required-ness, changing a status code, changing an event envelope shape, or changing URL/verb semantics is **breaking** — it requires a new `schema_version` (events) or an explicit contract version bump (API), never a silent change.
- Every replayable creation endpoint (task, transfer, decision, ...) must keep supporting the `Idempotency-Key` header — the server must return the original result on an identical replay, never a duplicate.
- The event envelope (`event_id`, `event_type`, `project_id`, `task_id`, `machine_id`, `actor_type`, `actor_id`, `client_timestamp`, `server_timestamp`, `payload`, `schema_version`) is fixed; only `payload` grows.
- A breaking change updates the contract `.md` file itself in the same change — the doc is the spec, not an afterthought.
- If Bloc A and Bloc B mocks diverge from the real contract, that's a bug in the mock, not a reason to special-case the contract.
- A change here that reflects a real architectural choice should produce a Decision (`DEC-XXXX`), per `AI/01_AI_OPERATING_REFERENCE.md`.
