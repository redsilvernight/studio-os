/**
 * UI-4 — Onglet Activité du workspace projet (réactivation validée).
 *
 * Sources : index des dates, timeline paginée par jour UTC et sessions.
 * Rendu = timeline lisible
 * (événement, acteur/source, moment, contexte utile), jamais un dump JSON :
 * seules des clés d'affichage connues sont extraites du payload, les types
 * inconnus restent tolérés (contrat additif) avec un libellé générique.
 *
 * Les signaux `coordination.*` passent par la même timeline : leur libellé
 * vient de `intentLabel` (`../coordination`), pas du type brut.
 *
 * Bruit `ai_work.*` (DEC-0165 D5) : la paire started/completed d'un même
 * `payload.ai_work_id` sature la timeline. Le rendu n'affiche qu'une entrée
 * par travail IA via `collapseAiWork`, fonction pure : la timeline brute
 * chargée depuis l'API n'est jamais modifiée.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { dsEmptyState, dsSkeleton } from "../ds/ds";
import type { components } from "../openapi-schema";
import { agentLabel, machineLabel } from "../actorNames";
import { COORDINATION_PREFIX, intentLabel, type CoordinationIntent } from "../coordination";
import { describeError, esc } from "../ui";
import { FALLBACK_LABEL } from "../language";

type Timeline = components["schemas"]["Timeline"];
type TimelineDay = components["schemas"]["TimelineDay"];
type TimelineEvent = components["schemas"]["EventEnvelope"];
type WorkSession = components["schemas"]["WorkSession"];

export const TIMELINE_LIMIT_DEFAULT = 200;
export const TIMELINE_LIMIT_MAX = 500;

const EVENT_LABEL: Record<string, string> = {
  "project.created": "Projet créé",
  "task.created": "Tâche créée",
  "task.started": "Tâche démarrée",
  "task.updated": "Tâche mise à jour",
  "task.blocked": "Tâche bloquée",
  "task.completed": "Tâche terminée",
  "task_launch.requested": "Lancement distant demandé",
  "task_launch.accepted": "Lancement distant accepté",
  "task_launch.rejected": "Lancement distant refusé",
  "task_launch.cancelled": "Lancement distant annulé",
  "task_launch.expired": "Lancement distant expiré",
  "task_launch.finished": "Lancement distant terminé",
  "session.started": "Session démarrée",
  "session.ended": "Session terminée",
  "resource.claimed": "Ressource réservée",
  "resource.renewed": "Réservation renouvelée",
  "resource.released": "Réservation libérée",
  "resource.conflict": "Chevauchement de réservation",
  "decision.proposed": "Décision proposée",
  "decision.created": "Décision créée",
  "decision.accepted": "Décision acceptée",
  "decision.superseded": "Décision remplacée",
  "library.version.created": "Version de bibliothèque créée",
  "library.version.activated": "Version de bibliothèque activée",
  "library.resource.deprecated": "Ressource de bibliothèque dépréciée",
  "library.lock.set": "Verrou posé",
  "library.lock.released": "Verrou libéré",
  "agent.started": "Agent démarré",
  "agent.stopped": "Agent arrêté",
  "ai_work.started": "Travail IA démarré",
  "ai_work.completed": "Travail IA terminé",
  "ai_work.failed": "Travail IA échoué",
  "ai_work.review_requested": "Relecture IA demandée",
  "ai_work.approved": "Travail IA approuvé",
  "ai_work.changes_requested": "Modifications demandées",
  "git.commit": "Commit enregistré",
  "git.branch.changed": "Branche modifiée",
  "git.pr.opened": "Pull request ouverte",
  "git.pr.merged": "Pull request fusionnée",
  "graph.updated": "Graphe mis à jour",
  "memory.proposed": "Mémoire proposée",
  "memory.updated": "Mémoire mise à jour",
  "godot.started": "Godot démarré",
  "godot.stopped": "Godot arrêté",
  "recording.started": "Enregistrement démarré",
  "recording.finished": "Enregistrement terminé",
  "recording.marker.created": "Marqueur d'enregistrement créé",
  "build.started": "Build démarré",
  "build.succeeded": "Build réussi",
  "build.failed": "Build échoué",
  "producer.job.requested": "Analyse Producer demandée",
  "producer.job.completed": "Analyse Producer terminée",
  "producer.job.failed": "Analyse Producer échouée",
  "transfer.created": "Transfert créé",
  "transfer.uploading": "Envoi en cours",
  "transfer.ready": "Transfert prêt",
  "transfer.downloaded": "Transfert téléchargé",
  "transfer.expired": "Transfert expiré",
  "transfer.deleted": "Transfert supprimé",
  "marketing.candidate.created": "Candidat marketing créé",
  "marketing.post.published": "Publication marketing publiée",
};

/** Intentions `coordination.*` reconnues ; une intention future reste tolérée. */
const COORDINATION_INTENTS: readonly CoordinationIntent[] = ["heads_up", "question", "blocked_by", "handoff"];

/** Libellé humain d'un type d'événement ; les types futurs restent tolérés.
 *
 * La timeline est volontairement non filtrée (DEC-0051) : elle contient donc
 * aussi les signaux `coordination.*`, qui sont des événements comme les
 * autres. Reconnus, ils sont nommés par `intentLabel` (source unique des
 * intentions, `../coordination`) ; un `coordination.<inconnu>` retombe sur le
 * libellé générique, jamais sur le type brut affiché à l'écran. */
export function timelineEventLabel(eventType: string): string {
  if (eventType.startsWith(COORDINATION_PREFIX)) {
    const intent = eventType.slice(COORDINATION_PREFIX.length) as CoordinationIntent;
    if (COORDINATION_INTENTS.includes(intent)) return intentLabel(intent);
  }
  return EVENT_LABEL[eventType] ?? "Événement";
}

/** Clés de payload sûres à afficher comme contexte (chaînes courtes réelles). */
const CONTEXT_KEYS = [
  "resource_path",
  "title",
  "readable_id",
  "filename",
  "transfer_code",
  "branch",
  "workflow_name",
  "reason",
  "status",
] as const;

/** Contexte utile : première clé connue renseignée, jamais le payload brut. */
export function timelineEventContext(event: TimelineEvent): string {
  for (const key of CONTEXT_KEYS) {
    const value: unknown = event.payload[key];
    if (typeof value === "string" && value.trim() !== "") return value.trim();
  }
  return "";
}

const ACTOR_LABEL: Record<string, string> = {
  user: "utilisateur",
  agent: "agent",
  system: "système",
};

/** Acteur/source : type explicite + nom (agent, machine) ou libellé générique, jamais d'identifiant affiché. */
export function timelineEventActor(event: TimelineEvent): string {
  const kind = ACTOR_LABEL[event.actor_type] ?? event.actor_type;
  const actor = `${kind} ${event.actor_type === "agent" ? agentLabel(event.actor_id) : FALLBACK_LABEL.user}`;
  return event.machine_id ? `${actor} · machine ${machineLabel(event.machine_id)}` : actor;
}

export function countTimelineEvents(timeline: Timeline): number {
  return timeline.days.reduce((total, day) => total + day.events.length, 0);
}

const AI_WORK_PREFIX = "ai_work.";
const AI_WORK_ID_KEY = "ai_work_id";

/** Identifiant de regroupement d'un événement `ai_work.*`, "" sinon (jamais regroupé). */
function aiWorkGroupId(event: TimelineEvent): string {
  if (!event.event_type.startsWith(AI_WORK_PREFIX)) return "";
  const raw: unknown = event.payload[AI_WORK_ID_KEY];
  return typeof raw === "string" ? raw.trim() : "";
}

/**
 * Une seule entrée affichée par travail IA : les événements `ai_work.*` d'un
 * même `payload.ai_work_id` sont réduits au plus récent (`server_timestamp` max),
 * qui reste dans son jour d'origine ; les jours sans événement disparaissent et
 * l'ordre relatif des autres événements est conservé. Fonction pure : l'entrée
 * n'est jamais modifiée et l'opération est idempotente.
 */
export function collapseAiWork(timeline: Timeline): Timeline {
  const latest = new Map<string, TimelineEvent>();
  for (const day of timeline.days) {
    for (const event of day.events) {
      const id = aiWorkGroupId(event);
      if (id === "") continue;
      const seen = latest.get(id);
      if (seen === undefined || event.server_timestamp > seen.server_timestamp) latest.set(id, event);
    }
  }
  const kept = new Set<TimelineEvent>();
  const days = timeline.days.flatMap((day) => {
    const events = day.events.filter((event) => {
      const id = aiWorkGroupId(event);
      if (id === "") return true;
      if (latest.get(id) !== event || kept.has(event)) return false;
      kept.add(event);
      return true;
    });
    return events.length === 0 ? [] : [{ ...day, events }];
  });
  return { ...timeline, days };
}

function eventHtml(event: TimelineEvent): string {
  const context = timelineEventContext(event);
  const contextHtml = context === "" ? "" : `<div class="tl-context">${esc(context)}</div>`;
  const taskHtml =
    event.task_id === null || event.task_id === undefined
      ? ""
      : `<a class="tl-task" href="#/tasks/${esc(event.task_id)}">Ouvrir la tâche</a>`;
  return `<li class="tl-item"><span class="tl-marker" aria-hidden="true"></span><div class="tl-card">` +
    `<div class="tl-title">${esc(timelineEventLabel(event.event_type))}</div>` +
    `${contextHtml}` +
    `<div class="tl-meta"><span title="${esc([event.actor_id, event.machine_id].filter(Boolean).join(" · "))}">${esc(timelineEventActor(event))}</span> · <time datetime="${esc(event.server_timestamp)}">${utcTime(event.server_timestamp)}</time>${taskHtml === "" ? "" : ` · ${taskHtml}`}</div>` +
    `</div></li>`;
}

function utcTime(value: string): string {
  return esc(new Date(value).toLocaleString("fr-FR", { timeZone: "UTC" }));
}

export function newestTimelineFirst(timeline: Timeline): Timeline {
  return { ...timeline, days: timeline.days.map((day) => ({
    ...day,
    events: [...day.events].sort((a, b) => Date.parse(b.server_timestamp) - Date.parse(a.server_timestamp) || b.event_id.localeCompare(a.event_id)),
  })).sort((a, b) => b.date.localeCompare(a.date)) };
}

export function utcDayWindow(date: string): { since: string; until: string } {
  const start = new Date(`${date}T00:00:00Z`);
  return { since: start.toISOString(), until: new Date(start.getTime() + 86_400_000).toISOString() };
}

function sessionsHtml(sessions: WorkSession[]): string {
  if (sessions.length === 0) return "";
  return `<section aria-label="Sessions de travail"><h3>Sessions de travail</h3><ol class="tl-list">` + sessions.map((session) =>
    `<li class="tl-item"><span class="tl-marker" aria-hidden="true"></span><div class="tl-card">` +
    `<div class="tl-title">Session de travail${session.ended_at ? " terminée" : " ouverte"}</div>` +
    `<div class="tl-meta">${esc(machineLabel(session.machine_id))}${session.agent_id ? ` · ${esc(agentLabel(session.agent_id))}` : ""}</div>` +
    `<p>Début : <time datetime="${esc(session.started_at)}">${utcTime(session.started_at)}</time>` +
    `${session.ended_at ? ` · Fin : <time datetime="${esc(session.ended_at)}">${utcTime(session.ended_at)}</time>` : ""}</p>` +
    `<a href="#/tasks/${esc(session.task_id)}">Ouvrir la tâche</a></div></li>`,
  ).join("") + `</ol></section>`;
}

function dayHtml(day: TimelineDay): string {
  const date = new Date(`${day.date}T00:00:00Z`);
  const label = Number.isNaN(date.getTime())
    ? day.date
    : date.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  return `<section class="tl-day" aria-labelledby="tl-day-${esc(day.date)}">` +
    `<h3 id="tl-day-${esc(day.date)}"><time datetime="${esc(day.date)}">${esc(label)}</time> · ${day.events.length} événement(s)</h3>` +
    `<ol class="tl-list">${day.events.map(eventHtml).join("")}</ol></section>`;
}

/** Vue calendrier : mois affiché (YYYY-MM) et jour sélectionné (YYYY-MM-DD). */
export interface CalendarView {
  month: string;
  selected: string;
}

/** Vue par défaut : le jour le plus récent qui porte des événements. */
export function defaultCalendarView(timeline: Timeline): CalendarView {
  const dates = timeline.days.filter((day) => day.events.length > 0).map((day) => day.date).sort();
  const latest = dates[dates.length - 1] ?? new Date().toISOString().slice(0, 10);
  return { month: latest.slice(0, 7), selected: latest };
}

export function shiftMonth(month: string, delta: number): string {
  const [year = 1970, mon = 1] = month.split("-").map(Number);
  const d = new Date(Date.UTC(year, mon - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function calendarHtml(timeline: Timeline, view: CalendarView, dates: string[]): string {
  const counts = new Map(timeline.days.map((day) => [day.date, day.events.length]));
  const available = new Set(dates);
  const [year = 1970, mon = 1] = view.month.split("-").map(Number);
  const first = new Date(Date.UTC(year, mon - 1, 1));
  const daysInMonth = new Date(Date.UTC(year, mon, 0)).getUTCDate();
  const offset = (first.getUTCDay() + 6) % 7; // semaine commençant le lundi
  const title = first.toLocaleDateString("fr-FR", { month: "long", year: "numeric", timeZone: "UTC" });
  const head = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."].map((d) => `<span class="cal-dow" aria-hidden="true">${d}</span>`).join("");
  const blanks = Array.from({ length: offset }, () => `<span class="cal-blank" aria-hidden="true"></span>`).join("");
  const cells = Array.from({ length: daysInMonth }, (_, i) => {
    const date = `${view.month}-${String(i + 1).padStart(2, "0")}`;
    const n = counts.get(date) ?? 0;
    const selected = date === view.selected;
    if (!available.has(date)) return `<span class="cal-day cal-day--empty">${i + 1}</span>`;
    return `<button type="button" class="cal-day cal-day--busy${selected ? " is-selected" : ""}" data-cal-day="${date}" aria-pressed="${selected ? "true" : "false"}" aria-label="${i + 1} : activité enregistrée">${i + 1}<span class="cal-count" aria-hidden="true">${n || "•"}</span></button>`;
  }).join("");
  return `<div class="cal" aria-label="Calendrier de l'activité">` +
    `<div class="cal-nav"><button type="button" class="ds-btn ds-btn--sm" data-cal-month="-1" aria-label="Mois précédent">‹</button>` +
    `<strong class="cal-title">${esc(title)}</strong>` +
    `<button type="button" class="ds-btn ds-btn--sm" data-cal-month="1" aria-label="Mois suivant">›</button>` +
    `<button type="button" class="ds-btn ds-btn--ghost ds-btn--sm" data-cal-latest>Dernière activité</button></div>` +
    `<div class="cal-grid">${head}${blanks}${cells}</div></div>`;
}

export interface TimelineViewData {
  timeline: Timeline;
  limit: number;
  view?: CalendarView;
  dates?: string[];
  hasMore?: boolean;
  sessions?: WorkSession[];
  loading?: boolean;
  failure?: string;
}

export function timelineHtml(data: TimelineViewData): string {
  const timeline = newestTimelineFirst(collapseAiWork(data.timeline));
  const dates = data.dates ?? timeline.days.filter((day) => day.events.length > 0).map((day) => day.date);
  if (dates.length === 0) {
    return dsEmptyState(
      "Aucune activité pour ce projet",
      "Aucun événement enregistré pour le moment. Certains types d'événements ne sont pas encore émis par le serveur.",
    );
  }
  const view = data.view ?? defaultCalendarView(timeline);
  const day = timeline.days.find((d) => d.date === view.selected && d.events.length > 0);
  const sessions = data.sessions ?? [];
  const dayBody = data.loading ? activityLoadingHtml()
    : data.failure ? `<div class="ds-notice ds-notice--danger" role="alert">${esc(data.failure)} <button type="button" class="ds-btn" data-timeline-retry>Réessayer</button></div>`
      : (day === undefined && sessions.length === 0 ? `<p class="ds-list-sub">Aucune activité enregistrée ce jour-là.</p>` : `${day === undefined ? "" : dayHtml(day)}${sessionsHtml(sessions)}`);
  const fetched = countTimelineEvents(data.timeline);
  const more =
    !data.loading && !data.failure && (data.hasMore ?? fetched >= data.limit)
      ? `<button class="ds-btn" type="button" data-timeline-more>Charger la suite de cette journée</button>`
      : "";
  return `<p class="ds-list-sub">Dates et heures en UTC. Toutes les dates enregistrées sont accessibles dans le calendrier.</p><div class="tl-layout">${calendarHtml(timeline, view, dates)}<div class="tl-selected" aria-busy="${String(data.loading ?? false)}">${dayBody}</div></div>${more}`;
}

export function activityLoadingHtml(): string {
  return dsSkeleton(4);
}

export async function fetchTimeline(
  client: StudioClient,
  projectId: string,
  limit: number,
  day?: string,
  offset = 0,
): Promise<Timeline> {
  const result = await client.GET("/api/v1/timeline", {
    params: { query: { project_id: projectId, limit, offset, ...(day ? utcDayWindow(day) : {}) } },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export async function fetchActivityDates(client: StudioClient, projectId: string): Promise<string[]> {
  const result = await client.GET("/api/v1/timeline/dates", { params: { query: { project_id: projectId } } });
  if (result.response.ok && result.data !== undefined) return [...result.data].sort().reverse();
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export async function fetchDaySessions(client: StudioClient, projectId: string, day: string, offset = 0): Promise<WorkSession[]> {
  const result = await client.GET("/api/v1/sessions", {
    params: { query: { project_id: projectId, ...utcDayWindow(day), limit: TIMELINE_LIMIT_DEFAULT, offset } },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export interface ActivityContext {
  client: StudioClient;
  projectId: string;
  authed: boolean;
}

export async function renderActivityInto(root: HTMLElement, ctx: ActivityContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = dsEmptyState(
      "Connectez-vous pour voir l'activité",
      "Saisissez votre jeton machine pour charger l'historique du projet.",
    );
    return;
  }
  root.innerHTML = activityLoadingHtml();
  try {
    const dates = await fetchActivityDates(ctx.client, ctx.projectId);
    if (dates.length === 0) {
      root.innerHTML = timelineHtml({ timeline: { project_id: ctx.projectId, days: [] }, limit: TIMELINE_LIMIT_DEFAULT, dates });
      return;
    }
    const latest = dates[0]!;
    let view: CalendarView = { month: latest.slice(0, 7), selected: latest };
    let timeline: Timeline = { project_id: ctx.projectId, days: [] };
    let sessions: WorkSession[] = [];
    let moreEvents = false;
    let moreSessions = false;
    let loading = false;
    let failure = "";
    let request = 0;
    const loadDay = async (append = false): Promise<void> => {
      const currentRequest = ++request;
      const day = view.selected;
      const eventOffset = append ? countTimelineEvents(timeline) : 0;
      const sessionOffset = append ? sessions.length : 0;
      if (!append) {
        timeline = { project_id: ctx.projectId, days: [] };
        sessions = [];
      }
      loading = true;
      failure = "";
      paint();
      try {
        const [nextTimeline, nextSessions] = await Promise.all([
          !append || moreEvents ? fetchTimeline(ctx.client, ctx.projectId, TIMELINE_LIMIT_DEFAULT, day, eventOffset) : Promise.resolve({ project_id: ctx.projectId, days: [] }),
          !append || moreSessions ? fetchDaySessions(ctx.client, ctx.projectId, day, sessionOffset) : Promise.resolve([]),
        ]);
        if (currentRequest !== request) return;
        moreEvents = countTimelineEvents(nextTimeline) === TIMELINE_LIMIT_DEFAULT;
        moreSessions = nextSessions.length === TIMELINE_LIMIT_DEFAULT;
        const events = new Map([...timeline.days.flatMap((item) => item.events), ...nextTimeline.days.flatMap((item) => item.events)].map((event) => [event.event_id, event]));
        timeline = { project_id: ctx.projectId, days: events.size > 0 ? [{ date: day, events: [...events.values()] }] : [] };
        sessions = [...new Map([...sessions, ...nextSessions].map((session) => [session.id, session])).values()];
      } catch (error) {
        if (currentRequest !== request) return;
        failure = describeError(error);
      }
      loading = false;
      paint();
    };
    const paint = (): void => {
        root.innerHTML = timelineHtml({ timeline, limit: TIMELINE_LIMIT_DEFAULT, view, dates, sessions, hasMore: moreEvents || moreSessions, loading, failure });
        root.querySelectorAll<HTMLButtonElement>("[data-cal-day]").forEach((b) =>
          b.addEventListener("click", () => {
            view = { ...view, selected: b.dataset["calDay"] ?? view.selected };
            void loadDay();
          }),
        );
        root.querySelectorAll<HTMLButtonElement>("[data-cal-month]").forEach((b) =>
          b.addEventListener("click", () => {
            view = { ...view, month: shiftMonth(view.month, Number(b.dataset["calMonth"])) };
            paint();
          }),
        );
        root.querySelector("[data-cal-latest]")?.addEventListener("click", () => {
          view = { month: latest.slice(0, 7), selected: latest };
          void loadDay();
        });
        root.querySelector("[data-timeline-more]")?.addEventListener("click", () => {
          void loadDay(true);
        });
        root.querySelector("[data-timeline-retry]")?.addEventListener("click", () => { void loadDay(); });
    };
    await loadDay();
  } catch (error) {
    root.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Activité indisponible.</strong>${esc(describeError(error))}</div>`;
  }
}
