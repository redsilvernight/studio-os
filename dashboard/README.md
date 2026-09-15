# Studi'OS Dashboard — V0 (DASH-0 → DASH-5)

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
npm test           # vitest (95 unit tests)
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
  Live loop, backoff, watchdog, refetch dispatch = DASH-3 (below).

## Implemented (DASH-1, read-only)

Overview page, existing endpoints only:

| Panel | Endpoint |
|---|---|
| Projects | `GET /api/v1/projects` + project selector |
| Project state | `GET /api/v1/projects/{id}/state` (active tasks/claims, generated_at) |
| Active tasks | `GET /api/v1/tasks?limit&offset`, columns TODO/IN PROGRESS/BLOCKED/DONE (blocked never merged) |
| Recent activity | `GET /api/v1/events?limit&since` (24h; **not claimed exhaustive** — most types need manual emission) |
| Agents | `GET /api/v1/agents`; presence is **Derived** from recent events, never canonical |
| Reviews ("Needs attention") | `GET /api/v1/review-queue` (DASH-3+: server-aggregated AI work review + proposed decisions + recent conflicts), read-only |
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

## Implemented (DASH-3, realtime)

One live connection per tab (`src/realtime.ts` + `src/sse.ts`), owned by
the app shell (`src/main.ts`), opened/closed as the selected project or
token changes — never per-view, since the backend has exactly one stream
per project (`project` required, DEC-0018).

| Feature | Detail |
|---|---|
| Reconnect | `openLiveProjectStream` (`src/sse.ts`) wraps the DASH-0 one-shot `connectEventStream` in a persistent loop, resuming with `Last-Event-ID` = last seen `seq`. |
| Backoff | Exponential (1s base, ×2, capped 30s, ±20% jitter), resets to the base delay after a clean close/message, grows on repeated errors. |
| Watchdog | Defense-in-depth only (default 75s silence): `stream_events` never emits a periodic keep-alive, so a quiet project is indistinguishable from a stalled connection by silence alone — a short timeout would cause reconnect churn on legitimately idle projects. `onError`/`onClose` cover the common failure modes; the watchdog only guards a connection some proxy/NAT silently dropped. |
| Refetch dispatch | `src/realtime.ts` JSON-parses each live message into an `EventEnvelope` (malformed frames are dropped, never thrown) and, debounced ~300ms, calls the **same** `render()` a manual navigation would — SSE is never a second source of truth (`store.ts`). |
| Reviews → Review Queue | Overview's "Needs attention" panel now calls `GET /api/v1/review-queue` instead of client-filtering `GET /ai-work`, rendering all three kinds (`ai_work_review`/`decision_proposal`/`resource_conflict`) with a kind badge. DASH-5 adds Approve / Request changes for `ai_work_review` rows (`PATCH /ai-work/{id}`). |
| Conflict banner | A live `resource.conflict` event shows a transient banner (resource path, from the event's own payload — no extra REST call) in the app shell, per the promise made in DASH-2. |
| Live traffic caveat | Views wired to `task.*` (Kanban) will see near-zero live traffic until server-side `task.*` emission exists (question ouverte n°9, `ROADMAP_STEP8_BREAKDOWN.md`) — the wiring is correct and future-proof, just currently quiet. `resource.conflict` is the only claims-related event actually emitted today. |

No new backend/contract changes — DASH-3 is pure client-side plumbing over
the events stream that already existed (DASH-0) and the review-queue/timeline
endpoints added by 8.4/8.5.

## Implemented (DASH-4, Machines / presence)

New `#/machines` screen (nav entry), existing endpoints only. (Naming note:
the step-8 roadmap also labels the human JWT login `DASH-4`, DEC-0056; this
mission uses DASH-4 for the Machines screen, and both features coexist.)

| Column | Source |
|---|---|
| Machine | derived machine id (`agents.machine_id` / `sessions.machine_id` / `events.machine_id`) |
| Owner | `GET /machines` only — **unavailable today**, blank otherwise |
| Last heartbeat | `Machine.last_seen_at` — **unavailable today**, blank |
| Last activity | newest `server_timestamp` / session timestamp seen (Derived) |
| Status | `online`/`idle`/`offline`; canonical thresholds (45s/90s, same as `services/heartbeats.py`) when `last_seen_at` exists, otherwise looser Derived windows (5min/30min) |
| Agents / Active sessions | counts from `GET /agents` and `GET /sessions` |

**`GET /api/v1/machines` does not exist** on the current API (only
`POST /machines` and `POST /machines/{id}/revoke`; neither `openapi.json`
nor the backend exposes a machine read). The screen probes it once and, on
`404/405/501`, says so and falls back to a **Derived** presence built from
`GET /agents`, `GET /sessions`, `GET /events?since=24h`. No fake canonical
status, no owner invented. When a machine read is added server-side, the same
view lights up with canonical `last_seen_at`/`owner` without a rewrite.

Below the table: registered agents and their **active** sessions
(`ended_at` unset). Refresh is the shell's SSE re-render (the presence-relevant
types `session.*`/`agent.*` are listed in `machinesApi.MACHINE_PRESENCE_EVENT_TYPES`)
plus an explicit **Reload**. SSE stays per selected project (the backend has no
global stream), so without a selected project only the explicit Reload runs.

## Implemented (DASH-5, write dashboard)

All writes go through the canonical HTTP API with a fresh client-generated
`Idempotency-Key` where the contract supports it; every mutation refetches.

| Feature | Endpoint(s) |
|---|---|
| Create project (admin/developer) | `POST /api/v1/projects` |
| Create task | `POST /api/v1/tasks` |
| Create decision | `POST /api/v1/decisions` (proposer required; `proposed_by_id` prefilled from a JWT `sub`, entered manually for an opaque machine token) |
| Create + upload transfer | `POST /api/v1/transfers` → `POST .../upload/initiate` → direct PUT to storage → `POST .../upload/complete` |
| Review workflow | `PATCH /api/v1/ai-work/{id}` `{status: approved\|changes_requested}` from the Overview Review Queue (server: admin-only, `review_requested` only — a `403`/`409` is surfaced, never pre-judged) |
| Task drag & drop | `PATCH /api/v1/tasks/{id}` + `If-Match-Version`, then refetch |

**Upload.** `POST /transfers` declares metadata and reserves quota; the bytes
then go **straight to object storage** via the pre-signed URL(s) — never through
the API. Small files use the single PUT path with `Content-MD5` (the dashboard
mirrors the Python client: initiate → `422 missing_content_md5` → retry with the
base64 MD5). Files > 128 MiB use multipart (64 MiB parts, bounded concurrency
4); each part's ETag is sent back on completion. MD5 has no WebCrypto primitive,
so `src/md5.ts` implements it (unit-tested against RFC 1321 vectors); SHA-256
uses `crypto.subtle`. Progress is shown from the returned byte counts.
Multipart part state is in-memory only (no resumable UI, nothing persisted);
multipart completion requires the storage CORS to expose `ETag`.

**Drag & drop.** HTML5 DnD between the four Kanban columns; each drop sends
`PATCH` + `If-Match-Version` with the version last read, then refetches. A `409`
re-reads server truth and says so — never an optimistic reorder. The explicit
`<select>`+Move control stays as the accessible fallback.

## Deliberately absent (later phases)

Human login/JWT is already present (`src/login.ts`, DEC-0056) and the V0 token
bar still accepts a machine token. Remaining gaps: CORS (same-origin/same-machine
only), a global (non-per-project) SSE stream for project-independent screens like
Machines, resumable multipart upload UI, decision accept/supersede (no server
endpoint exists), and Activity/Worklogs views (nav entries stay disabled).
