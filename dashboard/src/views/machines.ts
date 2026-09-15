/**
 * DASH-4 — Machines / canonical presence screen.
 *
 * Canonical source: `GET /api/v1/machines` (absent on the current API — the
 * probe degrades to null and the screen says so). Derived fallback reads only
 * existing endpoints: `GET /agents`, `GET /sessions`, `GET /events?since=24h`.
 * The SSE shell already re-renders this view on every live event; the
 * presence-relevant types are `session.*`/`agent.*` (see
 * `MACHINE_PRESENCE_EVENT_TYPES`). An explicit Reload is always available.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { getToken } from "../auth";
import {
  activeSessions,
  buildMachineRows,
  fetchAgents,
  fetchCanonicalMachines,
  fetchSessions,
  MACHINE_PRESENCE_EVENT_TYPES,
  type Agent,
  type EventEnvelope,
  type Machine,
  type MachineRow,
  type MachineStatus,
  type WorkSession,
} from "../machinesApi";
import { describeError, esc, fmtTime, idCell, section, statusBlock } from "../ui";

export interface MachinesContext {
  client: StudioClient;
  baseUrl: string;
  authed: boolean;
}

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown };

async function settle<T>(promise: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    return { ok: false, error };
  }
}

const STATUS_CLASS: Record<MachineStatus, string> = { online: "ok", idle: "warn", offline: "bad" };

export function statusBadge(row: MachineRow): string {
  const title =
    row.statusSource === "canonical"
      ? "Canonical: derived server-side from last heartbeat"
      : "Derived: inferred from agents/sessions/events — not canonical";
  return `<span class="status ${STATUS_CLASS[row.status]}" title="${esc(title)}">${esc(row.status)}<span class="tag ${row.statusSource === "derived" ? "derived" : ""}">${row.statusSource}</span></span>`;
}

function rowsTable(rows: MachineRow[]): string {
  if (rows.length === 0) return statusBlock("empty", "No machine activity visible to this token.");
  const body = rows
    .map(
      (row) =>
        `<tr><td>${row.displayName !== null ? esc(row.displayName) : "<span class=\"meta\">unknown</span>"}<div class="mono">${esc(row.machineId)}</div></td>` +
        `<td>${row.ownerUserId !== null ? idCell(row.ownerUserId) : "<span class=\"meta\">—</span>"}</td>` +
        `<td>${fmtTime(row.lastSeenAt)}</td>` +
        `<td>${fmtTime(row.lastActivityAt)}</td>` +
        `<td>${statusBadge(row)}</td>` +
        `<td>${row.agentCount}</td><td>${row.activeSessionCount}</td></tr>`,
    )
    .join("");
  return `<table><thead><tr><th>Machine</th><th>Owner</th><th>Last heartbeat</th><th>Last activity</th><th>Status</th><th>Agents</th><th>Active sessions</th></tr></thead><tbody>${body}</tbody></table>`;
}

function agentsTable(agents: Agent[]): string {
  if (agents.length === 0) return statusBlock("empty", "No agents registered.");
  const body = agents
    .map(
      (agent) =>
        `<tr><td>${esc(agent.display_name)}</td><td><code class="mono">${esc(agent.agent_kind === "" ? "—" : agent.agent_kind)}</code></td>` +
        `<td>${idCell(agent.machine_id)}</td><td>${agent.provider !== null && agent.provider !== undefined ? esc(agent.provider) : "—"}</td>` +
        `<td>${agent.model !== null && agent.model !== undefined ? esc(agent.model) : "—"}</td></tr>`,
    )
    .join("");
  return `<table><thead><tr><th>Agent</th><th>Kind</th><th>Machine</th><th>Provider</th><th>Model</th></tr></thead><tbody>${body}</tbody></table>`;
}

function sessionsTable(sessions: WorkSession[], machinesById: Map<string, MachineRow>): string {
  if (sessions.length === 0) return statusBlock("empty", "No active sessions.");
  const body = sessions
    .map(
      (session) =>
        `<tr><td>${idCell(session.id)}</td><td>${idCell(session.machine_id)} <span class="meta">${esc(machinesById.get(session.machine_id)?.status ?? "unknown")}</span></td>` +
        `<td>${idCell(session.agent_id)}</td><td>${idCell(session.task_id)}</td><td>${fmtTime(session.started_at)}</td></tr>`,
    )
    .join("");
  return `<table><thead><tr><th>Session</th><th>Machine</th><th>Agent</th><th>Task</th><th>Started</th></tr></thead><tbody>${body}</tbody></table>`;
}

export async function renderMachines(root: HTMLElement, ctx: MachinesContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = section("Machines", "GET /machines", statusBlock("empty", "Set a machine token to read presence."));
    return;
  }
  root.innerHTML = section("Machines", "GET /machines + /agents + /sessions", statusBlock("loading"));

  const token = getToken();
  const [agents, sessions, events, canonical] = await Promise.all([
    settle(fetchAgents(ctx.client)),
    settle(fetchSessions(ctx.client)),
    settle(fetchEvents(ctx.client)),
    token === null ? Promise.resolve({ ok: true as const, value: null as Machine[] | null }) : settle(fetchCanonicalMachines(ctx.baseUrl, token)),
  ]);

  const now = Date.now();
  const rows = buildMachineRows({
    machines: canonical.ok ? canonical.value : null,
    agents: agents.ok ? agents.value : [],
    sessions: sessions.ok ? sessions.value : [],
    events: events.ok ? events.value : [],
    now,
  });

  const canonicalAvailable = canonical.ok && canonical.value !== null;
  const notice = canonicalAvailable
    ? `<div class="health ok"><span class="dot"></span>Canonical presence — GET /machines answered<span class="meta">last_seen_at server-derived</span></div>`
    : `<div class="health bad"><span class="dot"></span>Canonical read unavailable (GET /api/v1/machines does not exist on this API) — presence below is <strong>Derived</strong> from agents, sessions and recent events<span class="meta">no last_seen_at / owner</span></div>`;

  const machinesById = new Map(rows.map((row) => [row.machineId, row]));
  const problems: string[] = [];
  if (!agents.ok) problems.push(`agents: ${describeError(agents.error)}`);
  if (!sessions.ok) problems.push(`sessions: ${describeError(sessions.error)}`);
  if (!events.ok) problems.push(`events: ${describeError(events.error)}`);
  if (!canonical.ok) problems.push(`machines: ${describeError(canonical.error)}`);

  root.innerHTML =
    section(
      "Machines",
      `GET /machines · reload · SSE ${MACHINE_PRESENCE_EVENT_TYPES.join(" / ")}`,
      `${notice}<div class="row"><button type="button" data-reload>Reload</button><span class="meta">${rows.length} machine id(s) observed</span></div>${problems.length > 0 ? `<div class="state error">${esc(problems.join(" · "))}</div>` : ""}${rowsTable(rows)}`,
    ) +
    section("Agents", "GET /agents", agentsTable(agents.ok ? agents.value : [])) +
    section("Active sessions", "GET /sessions · open sessions only", sessionsTable(activeSessions(sessions.ok ? sessions.value : []), machinesById));

  root.querySelector("[data-reload]")?.addEventListener("click", () => {
    void renderMachines(root, ctx);
  });
}

async function fetchEvents(client: StudioClient): Promise<EventEnvelope[]> {
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const result = await client.GET("/api/v1/events", { params: { query: { limit: 200, since } } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}
