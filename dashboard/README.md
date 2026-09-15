# Studi'OS Dashboard — V0 (DASH-0 / DASH-1 / DASH-2)

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
npm test           # vitest (49 unit tests)
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

## Implemented (DASH-2)

Projects list, Project Detail (Overview/Tasks/Claims tabs), Tasks with
Kanban, Task Detail, task claim/release, and project resource claims —
all through the existing API, no new backend contract.

| Feature | Endpoint(s) |
|---|---|
| Projects list | `GET /api/v1/projects` (read-only) |
| Project Detail bootstrap | `GET /api/v1/projects/{id}` + `.../state` (first paint; tab lists are the detailed truth) |
| Tasks list + Kanban | `GET /api/v1/tasks?project_id&limit&offset` (real pagination; status filter, no server total/sort/search, is client-side) |
| Edit task | `PATCH /api/v1/tasks/{id}` + `If-Match-Version` |
| Task claim/release | `POST /api/v1/tasks/{id}/claim` / `.../release` |
| Resource claims | `GET/POST /api/v1/claims`, `POST /api/v1/claims/{id}/renew`, `DELETE /api/v1/claims/{id}` |

**Optimistic concurrency.** Every `PATCH /tasks/{id}` carries
`If-Match-Version` set to the version last read by the client. A stale
write gets `409 {error_code: version_conflict, server_version}`. The
client never retries automatically and never last-write-wins: it
re-reads `GET /tasks/{id}`, repaints the form with server values, and
shows a banner naming the live version — the user re-applies their
change consciously. Covered in `tasksApi.test.ts`.

**Task claims.** `claim` uses the caller's machine (`agent_id` is
`None` server-side today); a second claim surfaces `409
already_claimed`. `release` is owner-or-admin and does **not** reset
`status` — the UI states this explicitly and never fabricates a
status change after release.

**Resource claims are a soft lock**, not a mutex: an overlapping
`POST /claims` still returns `201` (the server emits a
`resource.conflict` event instead of failing the request). The client
never turns an overlap into an invented `409`; conflict visibility
via events is DASH-3. Creation sends a client-generated
`Idempotency-Key` (fresh UUID per logical attempt, never reused across
attempts). `renew`/`release` (`DELETE` → `204`) are owner-or-admin.

**Permissions.** The UI disables actions it can determine are
unauthorized, but the backend stays the only authority. `401/403/404/
409/422` are all mapped to a message via `describeError`; a
`readonly` token can still browse every DASH-2 view (lists, detail,
Kanban) with mutating controls disabled rather than the page breaking.

**No drag & drop.** Column moves go through an explicit per-card
status `<select>` + button (`PATCH` + `If-Match-Version`, then a
server refetch) — accessible and avoids an irreversible optimistic
reorder. No DnD library was introduced.

**Realtime limits before DASH-3.** DASH-2 does not add a live event
loop, reconnect/watchdog, or timeline. After a mutation made by the
dashboard itself, the view does an explicit REST refetch; changes made
by other actors are not pushed to an open tab until DASH-3 wires SSE
into the mutated views.

## Deliberately absent (later phases)

Machines screen, canonical presence, human login, CORS, multipart
upload UI, review workflow (approve/reject), decision/transfer
creation, project/task creation, drag-and-drop, live timeline,
notifications, realtime refetch from other actors' changes —
DASH-3 → DASH-5.
