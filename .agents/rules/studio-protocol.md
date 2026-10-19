# Studio Protocol — minimal permanent rule (canonical)

Studio OS is the persistent memory; LLM context is a temporary cache.

1. Start with `studio_start_work` (with a task: claim, session and context); never scan broadly.
2. Load only what is needed: `why` / `matched_terms`, `additional_available` / `omitted_for_budget`. Refresh via `studio_prepare_context`.
3. Follow `studio-workflow` / `next`; group resource claims, checkpoint with `studio_sync`.
4. Replay writes with `idempotency_key`; on 409 reread, merge, retry with `expected_version`.
5. Persist decisions via `studio_add_decision`; resolve only when entitled.
6. Load definitions on demand: `studio_discover_definitions`, `studio_resolve_agent`.
7. One agent by default; subagent only for a real trigger. End via one `studio_handoff`; completed requires merge into `dev` and verified green CI.
