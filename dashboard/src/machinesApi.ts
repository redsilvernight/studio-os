/**
 * DASH-4 — Machines / canonical presence.
 *
 * Canonical truth would be `GET /api/v1/machines`, which does NOT exist on the
 * current API (only `POST /machines` and `POST /machines/{id}/revoke`). That
 * probe is attempted once and degrades to `null` on 404/405/501; the view then
 * builds a clearly-labelled Derived presence from existing reads only:
 * `GET /agents`, `GET /sessions`, `GET /events`. No business logic is
 * duplicated server-side — the dashboard derives a display state, nothing more.
 * Canonical heartbeat thresholds mirror `services/heartbeats.py` exactly.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import { joinUrl } from "./config";
import type { components } from "./openapi-schema";

export type Machine = components["schemas"]["Machine"];
export type MachineStatus = components["schemas"]["MachineStatus"];
export type Agent = components["schemas"]["Agent"];
export type WorkSession = components["schemas"]["WorkSession"];
export type EventEnvelope = components["schemas"]["EventEnvelope"];

/** Mirrors settings.heartbeat_interval_seconds / heartbeat_offline_after_seconds. */
export const HEARTBEAT_INTERVAL_SECONDS = 30;
export const HEARTBEAT_OFFLINE_AFTER_SECONDS = 90;

/** Derived fallback thresholds, deliberately looser than the canonical 30s/90s
 * heartbeat: events are sparse, so the canonical window would paint almost
 * every machine offline. Clearly surfaced as Derived in the UI. */
export const DERIVED_ONLINE_MS = 5 * 60 * 1000;
export const DERIVED_IDLE_MS = 30 * 60 * 1000;

/** Event types the Machines screen reacts to (the shell's SSE refetch). */
export const MACHINE_PRESENCE_EVENT_TYPES = [
  "session.started",
  "session.ended",
  "agent.started",
  "agent.stopped",
] as const;

function ageMs(iso: string | null | undefined, now: number): number | null {
  if (iso === null || iso === undefined || iso === "") return null;
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return null;
  return Math.max(now - time, 0);
}

/** Canonical status from `last_seen_at`, same thresholds as
 * `heartbeats_service.derive_status` (online ≤ 1.5×interval, idle ≤ offline). */
export function canonicalPresence(lastSeenAt: string | null | undefined, now: number): MachineStatus {
  const age = ageMs(lastSeenAt, now);
  if (age === null) return "offline";
  if (age <= HEARTBEAT_INTERVAL_SECONDS * 1.5 * 1000) return "online";
  if (age <= HEARTBEAT_OFFLINE_AFTER_SECONDS * 1000) return "idle";
  return "offline";
}

export function derivedPresence(lastActivityAt: string | null | undefined, now: number): MachineStatus {
  const age = ageMs(lastActivityAt, now);
  if (age === null) return "offline";
  if (age <= DERIVED_ONLINE_MS) return "online";
  if (age <= DERIVED_IDLE_MS) return "idle";
  return "offline";
}

export interface MachineRow {
  machineId: string;
  displayName: string | null;
  ownerUserId: string | null;
  /** Canonical heartbeat, only when `GET /machines` answered. */
  lastSeenAt: string | null;
  /** Newest evidence timestamp (events/sessions), always derived. */
  lastActivityAt: string | null;
  status: MachineStatus;
  statusSource: "canonical" | "derived";
  agentCount: number;
  activeSessionCount: number;
}

export interface MachineEvidence {
  machines?: Machine[] | null;
  agents: Agent[];
  sessions: WorkSession[];
  events: EventEnvelope[];
  now?: number;
}

function newest(current: string | null, candidate: string | null | undefined): string | null {
  if (candidate === null || candidate === undefined || candidate === "") return current;
  if (current === null) return candidate;
  return new Date(candidate).getTime() > new Date(current).getTime() ? candidate : current;
}

const STATUS_RANK: Record<MachineStatus, number> = { online: 0, idle: 1, offline: 2 };

/**
 * Builds one row per known machine id, canonical when the (missing today)
 * `GET /machines` answered, otherwise purely derived. Counts and last activity
 * always come from agents/sessions/events.
 */
export function buildMachineRows(evidence: MachineEvidence): MachineRow[] {
  const now = evidence.now ?? Date.now();
  const rows = new Map<string, MachineRow>();

  for (const machine of evidence.machines ?? []) {
    rows.set(machine.id, {
      machineId: machine.id,
      displayName: machine.display_name,
      ownerUserId: machine.owner_user_id,
      lastSeenAt: machine.last_seen_at ?? null,
      lastActivityAt: null,
      status: "offline",
      statusSource: "canonical",
      agentCount: 0,
      activeSessionCount: 0,
    });
  }

  const ensure = (machineId: string): MachineRow => {
    const existing = rows.get(machineId);
    if (existing !== undefined) return existing;
    const created: MachineRow = {
      machineId,
      displayName: null,
      ownerUserId: null,
      lastSeenAt: null,
      lastActivityAt: null,
      status: "offline",
      statusSource: "derived",
      agentCount: 0,
      activeSessionCount: 0,
    };
    rows.set(machineId, created);
    return created;
  };

  for (const agent of evidence.agents) {
    if (!agent.machine_id) continue;
    const row = ensure(agent.machine_id);
    row.agentCount += 1;
  }

  for (const session of evidence.sessions) {
    const row = ensure(session.machine_id);
    if (session.ended_at === null || session.ended_at === undefined) row.activeSessionCount += 1;
    row.lastActivityAt = newest(row.lastActivityAt, session.ended_at ?? session.started_at);
  }

  for (const event of evidence.events) {
    if (!event.machine_id) continue;
    const row = ensure(event.machine_id);
    row.lastActivityAt = newest(row.lastActivityAt, event.server_timestamp);
  }

  for (const row of rows.values()) {
    if (row.statusSource === "canonical" && row.lastSeenAt !== null) {
      row.status = canonicalPresence(row.lastSeenAt, now);
    } else {
      row.statusSource = "derived";
      row.status = derivedPresence(row.lastActivityAt, now);
    }
  }

  return [...rows.values()].sort(
    (a, b) =>
      STATUS_RANK[a.status] - STATUS_RANK[b.status] ||
      (new Date(b.lastActivityAt ?? 0).getTime() || 0) - (new Date(a.lastActivityAt ?? 0).getTime() || 0) ||
      a.machineId.localeCompare(b.machineId),
  );
}

/** Active sessions only (`ended_at` unset) — what the view calls "active". */
export function activeSessions(sessions: WorkSession[]): WorkSession[] {
  return sessions.filter((session) => session.ended_at === null || session.ended_at === undefined);
}

/**
 * Canonical machines read. Returns `null` when the endpoint is absent
 * (404/405/501) so the caller can fall back to derived presence; throws only
 * on a real error (401/403/5xx other than 501).
 */
export async function fetchCanonicalMachines(baseUrl: string, token: string): Promise<Machine[] | null> {
  const response = await fetch(joinUrl(baseUrl, "/api/v1/machines"), {
    headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
  });
  if (response.status === 404 || response.status === 405 || response.status === 501) return null;
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(parseErrorBody(response.status, body));
  }
  const data: unknown = await response.json();
  return Array.isArray(data) ? (data as Machine[]) : null;
}

export async function fetchAgents(client: StudioClient): Promise<Agent[]> {
  const result = await client.GET("/api/v1/agents");
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export async function fetchSessions(client: StudioClient): Promise<WorkSession[]> {
  const result = await client.GET("/api/v1/sessions");
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}
