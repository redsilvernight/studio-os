---
name: contract-change
description: Process for proposing or modifying a Studio OS contract (API, Event, Auth/Sync, or Data Model) without silently breaking the other Bloc. Use when a task requires adding or changing an endpoint, event type, auth/sync rule, or shared schema.
---

# Contract Change

## Why this exists

Studio OS is built by two parallel tracks (Bloc A: Cloud/Core, Bloc B: Local
Client) that integrate against `TECH/02_API_CONTRACT.md`, `03_EVENT_CONTRACT.md`,
`04_AUTH_SYNC_CONTRACT.md`, and `05_DATA_MODEL.md`. A contract changed without
following this process silently breaks whichever Bloc isn't in this conversation.

## Process

1. Read the current contract section before changing anything — don't assume its shape from memory.
2. Classify the change:
   - **Additive**: new optional field, new endpoint, new event type an old client can ignore. Proceed.
   - **Breaking**: removed/renamed field, changed required-ness, changed status code, changed envelope shape, changed URL/verb. Requires a version bump (`schema_version` for events, an explicit contract version note for the API) — never ship this silently.
3. Update the contract `.md` file itself in the same change. The doc is the spec; code that implements a contract without updating the doc has not actually changed the contract, it has drifted from it.
4. Update both Blocs' mocks/fixtures so the side not present in this conversation isn't left with a stale mock — see `IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md`.
5. If the change reflects a real architectural choice (not just a clarification), record a Decision (`DEC-XXXX`) per `AI/01_AI_OPERATING_REFERENCE.md` rather than letting it live only in a commit message.
6. For anything non-trivial, dispatch the `contract-guardian` agent to double-check the additive/breaking classification before merging.
7. Emit the relevant event / log the AIWorkLog entry for the change, per the AI task cycle in the root `CLAUDE.md`.

## Don't

- Don't change a contract's meaning while keeping its field name — that's a breaking change wearing an additive disguise.
- Don't let a mock diverge from the real contract "temporarily" — fix the mock in the same change.
- Don't skip the Decision step because the change feels small; if it constrains Bloc B's implementation choices, it's a decision.
