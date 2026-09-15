# Studi'OS Dashboard — V0 (DASH-0 / DASH-1)

Human read-only client of the canonical Studi'OS HTTP API + SSE.
No direct Postgres, no MCP-for-REST, no duplicated business logic,
no local memory, no AI-provider dependency.

## Location

`dashboard/` (repo root). Nothing outside this directory was changed
for DASH-0/1 — backend, contracts and migrations are untouched.

## Prerequisites

- Node.js ≥ 20, npm ≥ 10.
- A running Studi'OS API (see backend docs) + a machine token
  (`studio-admin` / `POST /machines`, admin).

## Install / dev / build

```bash
cd dashboard
npm install        # clean-checkout install
npm run dev        # vite dev server :5173
npm test           # vitest (30 unit tests)
npm run build      # tsc --noEmit + vite build → dist/
npm run preview    # serve dist/ locally
```

## API URL configuration

No URL is hardcoded. Resolution (`src/config.ts`):

- `VITE_STUDIO_API_URL` empty (default) → **same-origin**
  (relative `/api/v1/...`, the future Caddy/FastAPI deployment);
- set it for local dev against a remote API:

```bash
# .env.local (git-ignored, never commit tokens or hosts)
VITE_STUDIO_API_URL=http://localhost:8000
```

No CORS is configured (backend has none either) — same-origin or
same-machine dev only for now.

## OpenAPI client / types

Source of truth: the backend OpenAPI document. Checked-in snapshot:
`dashboard/openapi.json`. Typed client: `openapi-fetch` +
`openapi-typescript`-generated `src/openapi-schema.ts`.

Regenerate when the API evolves (backend venv required for export):

```bash
npm run openapi        # export from backend + regenerate types
npm run openapi:export # backend → dashboard/openapi.json only
npm run openapi:types  # openapi.json → src/openapi-schema.ts only
```

Never edit the OpenAPI to suit the frontend.

## Token usage (auth V0)

Header bar → paste a `Bearer <machine-token>` → **Set**.
Rules:

- memory only (`src/auth.ts`); never localStorage/cookie/log;
- all `/api/v1` calls + SSE send it; `GET /healthz` stays anonymous;
- **Clear** drops it from the page session (server revocation stays
  `POST /machines/{id}/revoke`, admin).

Security limits: a permanent Bearer in a browser is a known weakness
(DEC-0012) — acceptable for a local/admin tool behind HTTPS, not for
multi-user exposure. No human login/JWT/OAuth exists (out of V0 scope).

## Implemented (DASH-0)

- App shell + nav (Dashboard live; Projects/Tasks/Activity/Agents/
  Worklogs/Decisions/Transfers shown **disabled**, no fake content;
  no Machines entry).
- `GET /healthz` connection badge (reachable / unreachable distinct
  from 401/403 on protected routes).
- Config, typed API client, Bearer injection, machine-readable error
  mapping, minimal store, loading/error/empty states.
- SSE foundation (`src/sse.ts`): fetch+ReadableStream (native
  EventSource cannot send `Authorization`), `id:/data:` parser,
  in-memory `lastSeq`, `Last-Event-ID`/`since_seq` resume helpers.
  Live loop, backoff, watchdog, refetch dispatch = DASH-3.

## Implemented (DASH-1, read-only)

Overview page, existing endpoints only:

| Panel | Endpoint |
|---|---|
| Projects | `GET /api/v1/projects` + project selector |
| Project state | `GET /api/v1/projects/{id}/state` (active tasks/claims, generated_at) |
| Active tasks | `GET /api/v1/tasks?limit&offset`, columns TODO/IN PROGRESS/BLOCKED/DONE (blocked never merged) |
| Recent activity | `GET /api/v1/events?limit&since` (24h; **not claimed exhaustive** — most types need manual emission) |
| Agents | `GET /api/v1/agents`; presence is **Derived** from recent events, never canonical |
| Reviews | `GET /api/v1/ai-work`, client filter `review_requested`, read-only |
| Transfers | `GET /api/v1/transfers`, first 10, read-only |

## Deliberately absent (later phases)

Machines screen, canonical presence, human login, CORS, multipart
upload UI, review workflow (approve/reject), decision/transfer/task
creation, interactive Kanban/claims, live timeline, notifications,
DASH-2 → DASH-5.
