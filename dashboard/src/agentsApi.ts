/**
 * UI-6 — Agents IA : lectures canoniques + activité DERIVED honnête.
 *
 * Sources (aucun endpoint créé, aucun contrat modifié) :
 * - `GET /api/v1/agents` ......... identités de provenance (CANONIQUE, liste seule — pas de détail serveur).
 * - `GET /api/v1/sessions` ....... sessions de travail, `agent_id` nullable (CANONIQUE).
 * - `GET /api/v1/ai-work` ........ journal du travail produit, `agent_id` requis (CANONIQUE).
 * - `GET /api/v1/tasks` .......... `claimed_by_agent_id` nullable (CANONIQUE).
 * - `GET /api/v1/projects` ....... noms de projets pour les résumés (CANONIQUE).
 * - `GET /api/v1/events` ......... `actor_type=agent` + `actor_id` (CANONIQUE, secondaire).
 *
 * Absences explicites (ne jamais simuler) :
 * - Aucune présence agent canonique : les heartbeats sont par machine, et
 *   `GET /api/v1/machines` n'existe pas (voir machinesApi). Toute activité
 *   agent affichée est donc DERIVED — vocabulaire imposé : « Actif
 *   récemment », « Dernière activité », jamais « En ligne ».
 * - Aucun lien backend Agent ↔ agent-definition Library : `agent_kind` et
 *   `agent_profile` sont des chaînes libres, jamais validées contre la
 *   Library (contrat POST /agents). Aucune « Définition associée ».
 * - Aucun lien backend Agent ↔ runtime/binding : les bindings sont indexés
 *   par `(kind, stable_key)`, les runtimes sont privés par utilisateur.
 *   Seuls `harness`/`provider`/`model` déclarés par l'agent sont affichés,
 *   étiquetés comme déclaratifs.
 * - Aucun nom de machine canonique : sans `GET /machines`, seule la
 *   `machine_id` courte est affichée, avec lien vers #/machines.
 */
import type { StudioClient } from "./api";
import { ApiError, parseErrorBody } from "./api";
import type { components } from "./openapi-schema";

export type Agent = components["schemas"]["Agent"];
export type WorkSession = components["schemas"]["WorkSession"];
export type AIWorkLog = components["schemas"]["AIWorkLog"];
export type AgentTask = components["schemas"]["Task"];
export type AgentProject = components["schemas"]["Project"];
export type AgentEvent = components["schemas"]["EventEnvelope"];

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok) {
    if (result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  }
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export function fetchAgents(client: StudioClient): Promise<Agent[]> {
  return unwrap(client.GET("/api/v1/agents"));
}

export function fetchAgentSessions(client: StudioClient): Promise<WorkSession[]> {
  return unwrap(client.GET("/api/v1/sessions"));
}

export function fetchAgentWork(client: StudioClient): Promise<AIWorkLog[]> {
  return unwrap(client.GET("/api/v1/ai-work"));
}

export function fetchAgentTasks(client: StudioClient): Promise<AgentTask[]> {
  return unwrap(client.GET("/api/v1/tasks", { params: { query: { limit: 100, offset: 0 } } }));
}

export function fetchAgentProjects(client: StudioClient): Promise<AgentProject[]> {
  return unwrap(client.GET("/api/v1/projects"));
}

/** Événements récents : source secondaire pure (dégradation honnête si indisponible). */
export function fetchAgentEvents(client: StudioClient): Promise<AgentEvent[]> {
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  return unwrap(client.GET("/api/v1/events", { params: { query: { limit: 200, since } } }));
}

/* ------------------------------------------------------------------ */
/* Activité DERIVED — jamais une présence canonique.                    */
/* ------------------------------------------------------------------ */

/** En deçà : « Actif récemment » ; au-delà : « Dernière activité le … ». */
export const AGENT_RECENT_MS = 30 * 60 * 1000;

export type AgentSignal = "open-session" | "recent" | "past" | "none" | "unknown";

export type AgentActivitySource = "session" | "ai-work" | "task" | "event" | null;

export interface AgentActivity {
  signal: AgentSignal;
  /** Session ouverte portée par cet agent (signal, pas preuve de connexion). */
  openSession: WorkSession | null;
  lastActivityAt: string | null;
  lastActivitySource: AgentActivitySource;
  workCount: number;
  sessionCount: number;
}

export interface AgentEvidence {
  sessions: WorkSession[];
  aiWork: AIWorkLog[];
  tasks: AgentTask[];
  events: AgentEvent[];
  /** Faux dès qu'UNE source secondaire a échoué : on ne peut plus affirmer « aucune activité ». */
  secondaryOk: boolean;
  now?: number;
}

function ageMs(iso: string | null | undefined, now: number): number | null {
  if (iso === null || iso === undefined || iso === "") return null;
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return null;
  return Math.max(now - time, 0);
}

/**
 * Dérive l'activité d'un agent depuis les seules relations réelles
 * (`session.agent_id`, `ai-work.agent_id`, `task.claimed_by_agent_id`,
 * `event.actor_type=agent` + `actor_id`). Attribution directe uniquement :
 * l'activité de la machine d'un agent n'est jamais comptée comme sienne.
 */
export function deriveAgentActivity(agentId: string, evidence: AgentEvidence): AgentActivity {
  const now = evidence.now ?? Date.now();
  const ownSessions = evidence.sessions.filter((session) => session.agent_id === agentId);
  const ownWork = evidence.aiWork.filter((work) => work.agent_id === agentId);
  const claimedTasks = evidence.tasks.filter((task) => task.claimed_by_agent_id === agentId);
  const ownEvents = evidence.events.filter(
    (event) => event.actor_type === "agent" && event.actor_id === agentId,
  );

  const open = ownSessions
    .filter((session) => session.ended_at === null || session.ended_at === undefined)
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
  const openSession = open[0] ?? null;

  let lastActivityAt: string | null = null;
  let lastActivitySource: AgentActivitySource = null;
  const consider = (at: string | null | undefined, source: Exclude<AgentActivitySource, null>): void => {
    if (at === null || at === undefined || at === "") return;
    if (lastActivityAt !== null && new Date(at).getTime() <= new Date(lastActivityAt).getTime()) return;
    lastActivityAt = at;
    lastActivitySource = source;
  };
  for (const session of ownSessions) consider(session.ended_at ?? session.started_at, "session");
  for (const work of ownWork) consider(work.ended_at ?? work.started_at, "ai-work");
  for (const task of claimedTasks) consider(task.updated_at, "task");
  for (const event of ownEvents) consider(event.server_timestamp, "event");

  let signal: AgentSignal;
  if (openSession !== null) {
    signal = "open-session";
  } else if (lastActivityAt !== null && (ageMs(lastActivityAt, now) ?? Number.MAX_SAFE_INTEGER) <= AGENT_RECENT_MS) {
    signal = "recent";
  } else if (lastActivityAt !== null) {
    signal = "past";
  } else if (!evidence.secondaryOk) {
    signal = "unknown";
  } else {
    signal = "none";
  }

  return {
    signal,
    openSession,
    lastActivityAt,
    lastActivitySource,
    workCount: ownWork.length,
    sessionCount: ownSessions.length,
  };
}

/* ------------------------------------------------------------------ */
/* Recherche locale — champs humains réellement chargés.                */
/* ------------------------------------------------------------------ */

/** Sous-chaîne insensible à la casse sur nom, nature et technique déclarée. */
export function filterAgents(agents: Agent[], query: string): Agent[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return agents;
  return agents.filter((agent) => {
    const haystack = [agent.display_name, agent.agent_kind, agent.agent_profile, agent.harness, agent.provider, agent.model]
      .filter((field): field is string => typeof field === "string")
      .join("\n")
      .toLowerCase();
    return haystack.includes(needle);
  });
}

/* ------------------------------------------------------------------ */
/* Libellés français (présentation seule — clés backend inchangées).    */
/* ------------------------------------------------------------------ */

export const AI_WORK_STATUS_LABEL_FR: Record<string, string> = {
  started: "Commencé",
  completed: "Terminé",
  failed: "Échoué",
  review_requested: "En relecture",
  approved: "Approuvé",
  changes_requested: "Retours demandés",
};

export function aiWorkStatusLabel(status: string): string {
  return AI_WORK_STATUS_LABEL_FR[status] ?? status;
}

export type AiWorkTone = "neutral" | "info" | "success" | "warning";

export function aiWorkStatusTone(status: string): AiWorkTone {
  switch (status) {
    case "completed":
    case "approved":
      return "success";
    case "started":
    case "review_requested":
      return "info";
    case "failed":
    case "changes_requested":
      return "warning";
    default:
      return "neutral";
  }
}
