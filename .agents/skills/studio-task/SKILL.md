---
name: studio-task
description: Run a unit of work through existing Studi'OS primitives (task, claim, session, AI work) with optimistic concurrency and idempotency. Use for any tracked work; no server facade exists.
---

# Studio Task

## Composition (existing primitives only)

1. Find work: `studio_get_active_tasks` / `studio_get_project_state` / `studio_get_task`.
2. Take it: `studio_claim_task` (+ `studio_claim_resource` for paths, `studio_start_session`
   for traceability). Pass a stable `idempotency_key` (UUID) on every replayable creation.
3. Do the work locally.
4. Persist state: `studio_update_task` with `expected_version`.
   On 409 `version_conflict`, reread (`server_version` in the error), merge, retry —
   never overwrite silently. `blocked` and `completed` are statuses set here, not endpoints.
5. Trace it: `studio_log_ai_work` (`summary`, `changed_files`, `tests_run`, `task_id`).
6. Release: `studio_release_task` / `studio_release_resource`.

There is deliberately no single-call task facade: the six calls above are the protocol.

## Subagents (principal by default, subagent by exception)

Delegate only when a real trigger matches:

| Trigger | Delegate to |
|---|---|
| Non-trivial architecture or Cloud/Core ↔ local-client boundary | architect |
| Contract, endpoint, event, schema, or data-model change | contract guardian |
| Uncertain offline-queue, idempotency, claim, or transfer root cause | sync debugger |
| Significant validation before declaring work done | tester |

A subagent receives a precise objective plus the smallest self-contained file set,
prepares its own Studi'OS context (`studio-context` skill), and never receives the
parent's full history. Canonical definitions pin no model; concrete models live only
in generated harness projections.
