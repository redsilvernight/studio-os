---
name: studio-context
description: Targeted read-only context and refresh, including zero-history resumption. Tracked mutable work enters through studio-task and reuses start_work context.
---

# Studio Context — compatible entry point

Use `.agents/skills/studio-task/SKILL.md` for the common lifecycle, permissions
and entry-mode choice. Do not fetch context again immediately after start.
Strict read-only observation uses only `studio_prepare_context` and read tools;
no session, claim, mutable sync, decision or handoff.

For a needed refresh, call `studio_prepare_context` with project_id, objective,
and task_id/files if relevant. Inspect `why` / `matched_terms`,
`additional_available`, `omitted_for_budget`, `truncated`; lexical matches are
candidates, not obligations. Narrow the request before increasing its budget.

Send `known_ids` mapping IDs to `content_hash` only when the corresponding text
is still available locally. Reuse retained text for unchanged items. After
history loss omit hashes, reload necessary content and inspect the handoff's
NEXT through `studio_get_ai_work` only if the initial packet is insufficient.
An idempotent replay is not a context refresh.

Read only necessary decisions, files and definitions. Use
`studio_discover_definitions` / `studio_resolve_agent` for a specific need,
not the whole catalog. A missing next action is a handoff gap, not permission
for an unbounded repository scan.
