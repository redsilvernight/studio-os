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
  "coordination_text": "<=280 chars: where the next agent resumes",
  "changed_files": ["..."],
  "tests_run": ["..."],
  "idempotency_key": "<uuid>"
}
```

Composes: task status update + releases all claims + logs AI work (with `session_id` for traceability) + ends session. Idempotent via `Idempotency-Key`. Emits one `coordination.handoff` signal when `coordination_text` is set (never re-emitted on replay). Compact response: ids + statuses + last bounded `sync` block + `handoff_cursor_seq`.

## Failure

If `studio_handoff` fails, fix the cause and replay it with the same `idempotency_key`; do not rebuild the closing from `studio_release_task` / `studio_end_session` (deprecated, DEC-0186).

## Resume (Agent B, zero history, possibly another harness)

Agent B starts with `studio_start_work(project_id, agent_id, task_id)` — claims the task, resumes/creates session, returns context. The `sync` block (or `studio_sync(session_id)`) delivers the `coordination.handoff` signal as quoted data; then `studio_get_ai_work(task_id)` gives the handoff summary → `NEXT`. Ack `next_cursor` on the next checkpoint: a re-delivered signal is a no-op, never a duplicate.

## Don't

- Don't transfer conversation history to the next agent.
- Don't write the handoff only in chat; anything the next agent needs must be persisted.
- Don't use the old 4+ call sequence when `studio_handoff` is available.