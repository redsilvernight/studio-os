---
name: studio-task
description: Run a unit of work through Studi'OS primitives using L2/L3 composite calls (start_work + handoff). Use for any tracked work; no server facade exists.
---

# Studio Task (L2/L3)

## Composition (L2/L3 composites)

1. **Find/start work**: `studio_start_work(project_id, agent_id, task_id?, objective?, agent_stable_key?, files?, limit?, max_chars?, idempotency_key?)`
   - With `task_id`: claims task (idempotent), resumes/creates session, returns scoped context.
   - Without `task_id`: returns context + candidate tasks (current roadmap step first), no claim.
   - Agent identity from harness hook (`agent_id` + `agent_stable_key`).
   - `idempotency_key` makes it replay-safe.

2. **Do the work locally** (in task branch per `studio-git-flow`).

3. **Persist state**: `studio_update_task` with `expected_version` if needed.
   - On 409 `version_conflict`, reread (`server_version` in error), merge, retry — never overwrite silently.
   - `blocked` / `completed` are statuses set here.

4. **Trace it**: `studio_log_ai_work` with `session_id` (from step 1), `summary`, `changed_files`, `tests_run`, `task_id`.

5. **Close (L3)**: `studio_handoff(project_id, session_id, expected_version, task_status?, agent_id, summary, changed_files, tests_run, idempotency_key?)` — one call releases all claims, logs AI work, ends session.

## Subagents (principal by default, subagent by exception)

Delegate only when a real trigger matches:

| Trigger | Delegate to |
|---|---|
| Non-trivial architecture or Cloud/Core ↔ local-client boundary | architect |
| Contract, endpoint, event, schema, or data-model change | contract guardian |
| Uncertain offline-queue, idempotency, claim, or transfer root cause | sync debugger |
| Significant validation before declaring work done | tester |

A subagent receives a precise objective plus the smallest self-contained file set, prepares its own Studi'OS context (`studio-context` skill), and never receives the parent's full history. Canonical definitions pin no model; concrete models live only in generated harness projections.