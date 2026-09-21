# Studio Protocol — minimal permanent rule (canonical)

Studio OS is the persistent memory and source of truth. LLM context is a temporary work cache.

1. For any non-trivial work, call `studio_prepare_context` first — never start with a broad repo scan.
2. Load only what the current objective needs; follow `why` / `matched_terms`, then `additional_available` / `omitted_for_budget`.
3. Persist work state with tasks, claims and AI work (`expected_version`; on 409 reread, merge, retry).
4. Persist durable decisions with `studio_add_decision` (resolve with `studio_accept_decision` / `studio_supersede_decision` when entitled) instead of keeping rationale only in chat.
5. End significant work with the `studio-handoff` sequence.
6. Load specialized rules/skills only on demand (`studio_discover_definitions`, `studio_resolve_agent`).
7. One agent by default; delegate to a subagent only on a real trigger (see `studio-task` skill).
