/**
 * UI-4 — Onglet Activité du workspace projet (réactivation validée).
 *
 * Source unique : GET /api/v1/timeline?project_id (+ limit serveur 200 par
 * défaut, 500 max). Aucun nouvel endpoint. Rendu = timeline lisible
 * (événement, acteur/source, moment, contexte utile), jamais un dump JSON :
 * seules des clés d'affichage connues sont extraites du payload, les types
 * inconnus restent tolérés (contrat additif) avec un libellé générique.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { dsEmptyState, dsSkeleton } from "../ds/ds";
import type { components } from "../openapi-schema";
import { agentLabel, machineLabel } from "../actorNames";
import { describeError, esc, fmtTime } from "../ui";
import { FALLBACK_LABEL } from "../language";

type Timeline = components["schemas"]["Timeline"];
type TimelineDay = components["schemas"]["TimelineDay"];
type TimelineEvent = components["schemas"]["EventEnvelope"];

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

/** Libellé humain d'un type d'événement ; les types futurs restent tolérés. */
export function timelineEventLabel(eventType: string): string {
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
    `<div class="tl-meta"><span title="${esc([event.actor_id, event.machine_id].filter(Boolean).join(" · "))}">${esc(timelineEventActor(event))}</span> · <time datetime="${esc(event.server_timestamp)}">${fmtTime(event.server_timestamp)}</time>${taskHtml === "" ? "" : ` · ${taskHtml}`}</div>` +
    `</div></li>`;
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

function calendarHtml(timeline: Timeline, view: CalendarView): string {
  const counts = new Map(timeline.days.map((day) => [day.date, day.events.length]));
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
    if (n === 0) return `<span class="cal-day cal-day--empty">${i + 1}</span>`;
    return `<button type="button" class="cal-day cal-day--busy${selected ? " is-selected" : ""}" data-cal-day="${date}" aria-pressed="${selected ? "true" : "false"}" aria-label="${i + 1} : ${n} événement(s)">${i + 1}<span class="cal-count">${n}</span></button>`;
  }).join("");
  return `<div class="cal" aria-label="Calendrier de l'activité">` +
    `<div class="cal-nav"><button type="button" class="ds-btn ds-btn--sm" data-cal-month="-1" aria-label="Mois précédent">‹</button>` +
    `<strong class="cal-title">${esc(title)}</strong>` +
    `<button type="button" class="ds-btn ds-btn--sm" data-cal-month="1" aria-label="Mois suivant">›</button>` +
    `<button type="button" class="ds-btn ds-btn--ghost ds-btn--sm" data-cal-latest>Dernier événement</button></div>` +
    `<div class="cal-grid">${head}${blanks}${cells}</div></div>`;
}

export interface TimelineViewData {
  timeline: Timeline;
  limit: number;
  view?: CalendarView;
}

export function timelineHtml(data: TimelineViewData): string {
  const total = countTimelineEvents(data.timeline);
  if (total === 0) {
    return dsEmptyState(
      "Aucune activité pour ce projet",
      "Aucun événement enregistré pour le moment. Certains types d'événements ne sont pas encore émis par le serveur.",
    );
  }
  const view = data.view ?? defaultCalendarView(data.timeline);
  const day = data.timeline.days.find((d) => d.date === view.selected && d.events.length > 0);
  const dayBody = day === undefined ? `<p class="ds-list-sub">Aucun événement ce jour-là.</p>` : dayHtml(day);
  const more =
    total >= data.limit && data.limit < TIMELINE_LIMIT_MAX
      ? `<button class="ds-btn" type="button" data-timeline-more>Charger l'historique plus ancien</button>`
      : "";
  const capped =
    total >= data.limit && data.limit >= TIMELINE_LIMIT_MAX
      ? `<p class="ds-list-sub">L'historique affiché atteint la limite serveur (${TIMELINE_LIMIT_MAX} événements) : seuls les plus récents sont visibles ici.</p>`
      : "";
  return `<div class="tl-layout">${calendarHtml(data.timeline, view)}<div class="tl-selected">${dayBody}</div></div>${more}${capped}`;
}

export function activityLoadingHtml(): string {
  return dsSkeleton(4);
}

export async function fetchTimeline(
  client: StudioClient,
  projectId: string,
  limit: number,
): Promise<Timeline> {
  const result = await client.GET("/api/v1/timeline", {
    params: { query: { project_id: projectId, limit } },
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
  let limit = TIMELINE_LIMIT_DEFAULT;
  const reload = async (): Promise<void> => {
    root.innerHTML = activityLoadingHtml();
    try {
      const timeline = await fetchTimeline(ctx.client, ctx.projectId, limit);
      let view = defaultCalendarView(timeline);
      const paint = (): void => {
        root.innerHTML = timelineHtml({ timeline, limit, view });
        root.querySelectorAll<HTMLButtonElement>("[data-cal-day]").forEach((b) =>
          b.addEventListener("click", () => {
            view = { ...view, selected: b.dataset["calDay"] ?? view.selected };
            paint();
          }),
        );
        root.querySelectorAll<HTMLButtonElement>("[data-cal-month]").forEach((b) =>
          b.addEventListener("click", () => {
            view = { ...view, month: shiftMonth(view.month, Number(b.dataset["calMonth"])) };
            paint();
          }),
        );
        root.querySelector("[data-cal-latest]")?.addEventListener("click", () => {
          view = defaultCalendarView(timeline);
          paint();
        });
        root.querySelector("[data-timeline-more]")?.addEventListener("click", () => {
          limit = TIMELINE_LIMIT_MAX;
          void reload();
        });
      };
      paint();
      return;
    } catch (error) {
      root.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Activité indisponible.</strong>${esc(describeError(error))}</div>`;
    }
  };
  await reload();
}
