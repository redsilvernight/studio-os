---
name: openapi-sync
description: Regenerate the dashboard's OpenAPI snapshot and TypeScript types after an API change, then verify the dashboard still builds. Use after changing a FastAPI route, request/response schema or status code in services/api, or when dashboard/openapi.json or dashboard/src/openapi-schema.ts must be refreshed.
---

# OpenAPI sync

`dashboard/openapi.json` and `dashboard/src/openapi-schema.ts` are generated —
never edit them by hand (a project hook blocks it).

## Steps (from `dashboard/`)

1. `npm run openapi` — exports the spec from the backend
   (`scripts/export_openapi.py`, needs `../.venv`; it falls back to the
   checked-in snapshot when the backend is not importable: if it says so, fix
   the import, do not commit a stale snapshot) and regenerates the types.
2. `npm run check:local-contracts` — local contract mirror still in sync
   (`npm run gen:local-contracts` if it drifted).
3. `npm run build` — `tsc --noEmit` catches consumers broken by the new types.
4. `npm test` for the touched modules.

## Then

- Review `git diff --stat dashboard/openapi.json dashboard/src/openapi-schema.ts`:
  only the endpoints you changed should move.
- A removed/renamed field or changed status code is a contract change: follow
  skill `contract-change` and ask the `contract-guardian` agent for a verdict.

## Report

Commands run with their result, endpoints whose schema changed, consumers fixed.
