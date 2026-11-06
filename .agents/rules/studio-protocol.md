# Studio Protocol — minimal permanent rule (canonical)

Studio OS is the persistent memory; LLM context is a temporary cache.

1. Explicit read-only intent is decisive: an audit or observation request uses `studio_prepare_context` and read tools only, even if a task ID or agent ID is supplied. Never start, claim, sync, hand off or write during that audit. Classify intent before choosing a tool.
2. Mutable tracked work: `studio_start_work` once (task, session, context, sync).
3. Load only what is needed: `why` / `matched_terms`, `additional_available` / `omitted_for_budget`. Refresh via `studio_prepare_context`.
4. Follow `studio-task`; group needed claims; `studio_sync` at boundaries: deduplicate event_id, process durably, then ack. Handoff never auto-acks.
5. Replay writes with `idempotency_key`; on 409 reread, merge, retry with `expected_version`.
6. Persist decisions via `studio_add_decision`; resolve only when entitled.
7. Load definitions on demand: `studio_discover_definitions`, `studio_resolve_agent`.
8. One agent by default; subagent on a real trigger. Tracked completed tasks require real completion evidence via `studio_handoff`; failed mandatory checks forbid completion. Separate implemented/tested/integrated/deployed.
