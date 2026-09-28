---
name: studio-handoff
description: Close a unit of work in one call (L3 studio_handoff) so a zero-history agent (possibly another harness) can resume via studio_prepare_context. Use at the end of any significant work.
---

# Studio Handoff (L3)

## Closing sequence (one call: `studio_handoff`)

```json
{
  "project_id": "<uuid>",
  "session_id": "<uuid>",
  "expected_version": <int>,
  "task_status": "completed|blocked",
  "agent_id": "<uuid>",
  "summary": "DONE ...\nSTATE ...\nCHANGED ...\nTESTS ...\nNEXT ...\nBLOCKERS ...",
  "changed_files": ["..."],
  "tests_run": ["..."],
  "idempotency_key": "<uuid>"
}
```

Composes: task status update + releases all claims + logs AI work (with `session_id` for traceability) + ends session. Idempotent via `Idempotency-Key`. Compact response: ids + statuses only.

## Minimal fallback (if L3 not available)

1. `studio_log_ai_work` (final, with `task_id`, `session_id`): structured note `DONE/STATE/CHANGED/TESTS/NEXT/BLOCKERS` + `changed_files`/`tests_run`
2. `studio_release_resource` for each active claim of the task
3. `studio_release_task`
4. `studio_end_session` (now auto-releases task claims)

## Resume (Agent B, zero history, possibly another harness)

Agent B starts with `studio_start_work(project_id, agent_id, task_id)` — claims the task, resumes/creates session, returns context. Then reads `studio_get_ai_work(task_id)` for the handoff summary → `NEXT`.

## Don't

- Don't transfer conversation history to the next agent.
- Don't write the handoff only in chat; anything the next agent needs must be persisted.
- Don't use the old 4+ call sequence when `studio_handoff` is available.