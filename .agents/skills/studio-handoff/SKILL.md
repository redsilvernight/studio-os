---
name: studio-handoff
description: Compatible closing entry point; studio-task owns sync, completion evidence and resumable single-call handoff.
---

# Studio Handoff — compatible entry point

Follow `.agents/skills/studio-task/SKILL.md`, Validate and close, and its
`.agents/skills/studio-task/references/completion.md` reference. Do not duplicate
the common sequence. Strict read-only audits never call a mutable handoff.

`studio_handoff` logs work, releases eligible claims and ends the session.
Every tracked completed task needs actual completion evidence and its work log.
Use `DONE / STATE / CHANGED / TESTS / NEXT / BLOCKERS` in the summary;
coordination_text emits `coordination.handoff`. Preserve IDs, versions, keys,
pending items and durable processing references for the next worker.

Handoff closes the session. Never call `studio_sync` afterward with its
`session_id`; that returns `session_not_found`. If the handoff's final sync was
lost or reports pending content, its warnings are NOT automatically acknowledged.
Process pending items durably, then recover with stateless
`studio_sync(agent_id=..., task_id=...)`, using `handoff_cursor_seq` as the
starting cursor when available. Process items durably, retain `event_id`s, and
deduplicate redelivery; stateless reads do not persist a session cursor. A
successor enters its own mutable unit via `studio_start_work` or uses
read-only context when only observing. Only pass options advertised by the
connected tool.
