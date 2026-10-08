---
name: studio-decision
description: Persist only decisions that must survive the session, via existing Studi'OS decision primitives (propose, then admin-gated resolve). Use when a choice constrains future work.
---

# Studio Decision

## Propose (any writer role)

`studio_add_decision(title, body, task_id?, idempotency_key?)` records a `proposed`
decision. It becomes visible in `studio_get_review_queue` and in later
`studio_prepare_context` calls (anything not `superseded`).

The number is the server's: `studio_add_decision` allocates `DEC-XXXX` (never by
hand — two concurrent sessions get two distinct numbers) and writes the matching
vault `decision` note, project or studio scope. Never create a
`docs/decisions/` file: the Markdown export comes from P10.

## Resolve (admin role only, DEC-0094)

- Accept: `studio_accept_decision` — the vault note becomes `validated`.
- Supersede (terminal): `studio_supersede_decision(decision_id, superseded_by?)`
  links the replacement with a `supersedes` link; the note becomes `superseded`.
- Transitions are `proposed -> accepted` and `proposed|accepted -> superseded`,
  guarded server-side; a non-entitled caller gets a rejection, not a silent skip.

## What to persist

Persist a decision only when it must survive the session — a choice that constrains
future work. Put the rationale in the decision `body`, never only in chat context,
so the next agent inherits it through `studio_prepare_context` instead of history.

## Don't

- Don't persist transient working notes as decisions.
- Don't keep the only copy of a rationale in conversation context.
- Don't invent a workaround around the admin gate.