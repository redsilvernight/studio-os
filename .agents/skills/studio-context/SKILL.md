---
name: studio-context
description: Prepare the minimal Studi'OS context for an objective via studio_prepare_context before any broad exploration. Use when starting work, resuming a task, or taking over after a handoff.
---

# Studio Context

## Principle

**`studio_prepare_context` before broad scan.** A fresh agent must be able to
start from the Rule plus one bounded call — never by loading the full doc
pack, all ADRs, all roadmaps, all skills, or the whole history.

## Sequence

1. Call `studio_prepare_context(project_id, objective, task_id?, files?, limit?, max_chars?)`.
   Keep `max_chars` at its default unless the response says budget was the limit.
2. Read the response with progressive disclosure:
   - `why` / `matched_terms` — prefer `requested`, `linked_to_task`, `project_scope`
     over pure `lexical` matches; lexical-only items are candidates, not requirements.
   - `additional_available` — fetch selectively (`studio_get_task`, `studio_get_decisions`,
     `studio_discover_definitions`) only for categories relevant to the objective.
   - `omitted_for_budget` — if non-empty and needed, narrow the objective or raise
     `max_chars` (max 50000); never bulk-load everything.
3. Only if the objective still needs more, in this order:
   - `studio_resolve_agent` — when acting under an agent role that needs its
     rules/skills/model profile;
   - `studio_discover_definitions` — for one specialized rule/skill, never the catalog;
   - local `graph_query` / `memory_search` (Bloc B) — for file-level or historical detail;
   - targeted file reads — smallest set that answers the objective.

## Resume after handoff

A new agent with zero history resumes with `studio_prepare_context(objective, task_id)`
plus `studio_get_ai_work(task_id)` for the previous handoff summary, then identifies
NEXT. If those two calls do not yield the next action, the handoff was incomplete —
say so instead of scanning the repo.

## Don't

- Don't read the whole documentation pack "to be safe".
- Don't treat a lexical match as a requirement.
- Don't preload specialized rules/skills for every task.
