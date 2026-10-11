/**
 * P02-inbox — Lecture humaine des signaux `coordination.*` (DEC-0157).
 *
 * - Source unique : GET /api/v1/events?task=… ou ?project=… (aucun endpoint
 *   dédié, aucun contrat modifié). Seuls les `event_type` préfixés
 *   `coordination.` sont retenus ; une ligne malformée est ignorée.
 * - `text` est une donnée écrite par une autre session : toujours échappé à
 *   l'affichage, jamais interprété comme une consigne.
 * - Une réponse est un signal portant `in_reply_to` ; une question ou un
 *   blocage sans réponse reste « à traiter ».
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";

export const COORDINATION_PREFIX = "coordination.";
export const COORDINATION_FETCH_LIMIT = 500;

export type CoordinationIntent = "heads_up" | "question" | "blocked_by" | "handoff";

const INTENTS: readonly CoordinationIntent[] = ["heads_up", "question", "blocked_by", "handoff"];

export interface CoordinationItem {
  eventId: string;
  intent: CoordinationIntent;
  text: string;
  taskId: string | null;
  inReplyTo: string | null;
  fromSessionId: string | null;
  actorType: string;
  actorId: string;
  machineId: string | null;
  at: string;
}

export interface CoordinationThread {
  root: CoordinationItem;
  replies: CoordinationItem[];
}

interface RawEvent {
  event_id?: unknown;
  event_type?: unknown;
  task_id?: unknown;
  machine_id?: unknown;
  actor_type?: unknown;
  actor_id?: unknown;
  server_timestamp?: unknown;
  client_timestamp?: unknown;
  payload?: unknown;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function intentLabel(intent: CoordinationIntent): string {
  switch (intent) {
    case "question":
      return "Question";
    case "blocked_by":
      return "Blocage";
    case "handoff":
      return "Passage de relais";
    case "heads_up":
      return "Information";
  }
}

export function parseCoordinationEvents(events: unknown): CoordinationItem[] {
  if (!Array.isArray(events)) return [];
  const items: CoordinationItem[] = [];
  for (const raw of events as RawEvent[]) {
    const type = str(raw?.event_type);
    if (type === null || !type.startsWith(COORDINATION_PREFIX)) continue;
    const intent = type.slice(COORDINATION_PREFIX.length) as CoordinationIntent;
    if (!INTENTS.includes(intent)) continue;
    const payload = (raw.payload ?? {}) as Record<string, unknown>;
    const eventId = str(raw.event_id);
    const text = str(payload.text);
    const at = str(raw.server_timestamp) ?? str(raw.client_timestamp);
    if (eventId === null || text === null || at === null) continue;
    items.push({
      eventId,
      intent,
      text,
      taskId: str(raw.task_id) ?? str(payload.task_id),
      inReplyTo: str(payload.in_reply_to),
      fromSessionId: str(payload.from_session_id),
      actorType: str(raw.actor_type) ?? "system",
      actorId: str(raw.actor_id) ?? "",
      machineId: str(raw.machine_id),
      at,
    });
  }
  return items.sort((a, b) => a.at.localeCompare(b.at));
}

export function buildThreads(items: CoordinationItem[]): CoordinationThread[] {
  const byId = new Map(items.map((item) => [item.eventId, item]));
  const threads = new Map<string, CoordinationThread>();
  const rootOf = (item: CoordinationItem): CoordinationItem => {
    let current = item;
    const seen = new Set<string>();
    while (current.inReplyTo !== null && byId.has(current.inReplyTo) && !seen.has(current.eventId)) {
      seen.add(current.eventId);
      current = byId.get(current.inReplyTo) as CoordinationItem;
    }
    return current;
  };
  for (const item of items) {
    const root = rootOf(item);
    const thread = threads.get(root.eventId) ?? { root, replies: [] };
    if (item !== root) thread.replies.push(item);
    threads.set(root.eventId, thread);
  }
  return [...threads.values()].sort((a, b) => a.root.at.localeCompare(b.root.at));
}

export function openItems(items: CoordinationItem[]): CoordinationItem[] {
  const answered = new Set(items.map((item) => item.inReplyTo).filter((id): id is string => id !== null));
  return items.filter(
    (item) =>
      (item.intent === "question" || item.intent === "blocked_by") &&
      item.inReplyTo === null &&
      !answered.has(item.eventId),
  );
}

export function latestHandoff(items: CoordinationItem[]): CoordinationItem | null {
  return items.filter((item) => item.intent === "handoff").at(-1) ?? null;
}

async function fetchEvents(client: StudioClient, query: Record<string, string>): Promise<CoordinationItem[]> {
  const result = await client.GET("/api/v1/events", {
    params: { query: { ...query, limit: COORDINATION_FETCH_LIMIT } },
  });
  if (result.response.ok && result.data !== undefined) return parseCoordinationEvents(result.data);
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function fetchTaskCoordination(client: StudioClient, taskId: string): Promise<CoordinationItem[]> {
  return fetchEvents(client, { task: taskId });
}

export function fetchProjectCoordination(client: StudioClient, projectId: string): Promise<CoordinationItem[]> {
  return fetchEvents(client, { project: projectId });
}
