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

Composes: task status update + releases the session agent's eligible claims + logs AI work (with `session_id` for traceability) + ends session. Idempotent via `Idempotency-Key`. Emits one `coordination.handoff` signal when `coordination_text` is set (never re-emitted on replay). Compact response: ids + statuses + last bounded `sync` block + `handoff_cursor_seq`.

## Completion by work kind

Pass optional `completion` evidence (`studio.completion/v1`) with the work kind, artifact references and checks. The server checks consistency; it cannot verify a local repository or turn a declaration into a review approval.

- Code: a versioned revision and actual validations. Integration and CI are required when the repository or task says so; name the actual target branch, never assume `dev`.
- Audit/diagnostic: verified artifacts and validation/review checks; Git and CI are not automatically required. An observed failure may be recorded as a finding, separately from the successful validation of the diagnostic deliverable.
- Operation: an observed and verified effect. Deployment is recorded separately and still requires its applicable authorization.
- A command check needs its real exit code. Failed, skipped or unavailable validation cannot complete the task. A tool returning "completed" is not proof of success.

Include `agent_id` and `summary` so the evidence is persisted with the AI work. Without a completed deliverable, omit `task_status` and leave a resumable checkpoint. Always distinguish implemented, tested, integrated and deployed in STATE. Completion evidence does not relax project acceptance or authorization rules.

## Failure

If `studio_handoff` fails, fix the cause and replay it with the same `idempotency_key`; do not rebuild the closing from `studio_release_task` / `studio_end_session` (deprecated, DEC-0186).

## Resume (Agent B, zero history, possibly another harness)

Agent B starts with `studio_start_work(project_id, agent_id, task_id)` — claims the task, resumes/creates session, returns context. The `sync` block (or `studio_sync(session_id)`) delivers the `coordination.handoff` signal as quoted data; then `studio_get_ai_work(task_id)` gives the handoff summary → `NEXT`. Ack `next_cursor` on the next checkpoint: a re-delivered signal is a no-op, never a duplicate.

## Don't

- Don't transfer conversation history to the next agent.
- Don't write the handoff only in chat; anything the next agent needs must be persisted.
- Don't use the old 4+ call sequence when `studio_handoff` is available.