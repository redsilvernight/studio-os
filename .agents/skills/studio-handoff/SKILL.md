---
name: studio-handoff
description: Close a unit of work with existing Studi'OS primitives so a zero-history agent (possibly another harness) can resume via studio_prepare_context. Use at the end of any significant work.
---

# Studio Handoff

## Closing sequence (existing primitives only, no `handoff.close`)

1. `studio_log_ai_work` (final, with `task_id`): `summary` holds the structured note —
   `DONE` / `STATE` / `CHANGED` / `TESTS` / `NEXT` / `BLOCKERS` — plus `changed_files`
   and `tests_run` (honored on creation too; on update `summary` replaces the stored one).
   Keep it under ~800 characters; it is the resume packet, not a report.
2. `studio_release_resource` for each active claim of the task.
3. `studio_release_task`.
4. `studio_end_session` for the session, if one was started.
5. Optional: `studio_emit_event` for a session note other consumers should see.
6. Stop for the user's merge approval (`studio-git-flow`); set `completed` only after the merge.

Typical cost: 4 calls plus one per active resource claim.

## Resume (Agent B, zero history, possibly another harness)

1. Same minimal Rule.
2. `studio_prepare_context(objective, task_id)` for task state, decisions, claims.
3. `studio_get_ai_work(task_id)` for the handoff summary → read `NEXT`.
4. If Steps 2–3 do not yield the next action, the handoff was incomplete — report
   that instead of reconstructing state by scanning the repo.

## Don't

- Don't transfer conversation history to the next agent.
- Don't write the handoff only in chat; anything the next agent needs must be persisted.
- Don't add a server-side closer in P1; the sequence above is the protocol and its
  measured cost decides whether P2/P3 needs one.
