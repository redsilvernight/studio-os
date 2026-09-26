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
import { describeError, esc, fmtTime, shortId } from "../ui";

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

/** Acteur/source : type explicite + nom (agent, machine) ou identifiant court, jamais d'UUID affiché. */
export function timelineEventActor(event: TimelineEvent): string {
  const kind = ACTOR_LABEL[event.actor_type] ?? event.actor_type;
  const actor = `${kind} ${event.actor_type === "agent" ? agentLabel(event.actor_id) : shortId(event.actor_id)}`;
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
      : `<a class="tl-task" href="#/tasks/${esc(event.task_id)}">Voir la tâche ${esc(shortId(event.task_id))}</a>`;
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
    : date.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  return `<section class="tl-day" aria-labelledby="tl-day-${esc(day.date)}">` +
    `<h3 id="tl-day-${esc(day.date)}"><time datetime="${esc(day.date)}">${esc(label)}</time> · ${day.events.length} événement(s)</h3>` +
    `<ol class="tl-list">${day.events.map(eventHtml).join("")}</ol></section>`;
}

export interface TimelineViewData {
  timeline: Timeline;
  limit: number;
}

export function timelineHtml(data: TimelineViewData): string {
  const total = countTimelineEvents(data.timeline);
  if (total === 0) {
    return dsEmptyState(
      "Aucune activité pour ce projet",
      "Aucun événement enregistré pour le moment. Certains types d'événements ne sont pas encore émis par le serveur.",
    );
  }
  const days = data.timeline.days
    .filter((day) => day.events.length > 0)
    .map(dayHtml)
    .join("");
  const more =
    total >= data.limit && data.limit < TIMELINE_LIMIT_MAX
      ? `<button class="ds-btn" type="button" data-timeline-more>Afficher plus d'événements</button>`
      : "";
  const capped =
    total >= data.limit && data.limit >= TIMELINE_LIMIT_MAX
      ? `<p class="ds-list-sub">L'historique affiché atteint la limite serveur (${TIMELINE_LIMIT_MAX} événements) : seuls les plus récents sont visibles ici.</p>`
      : "";
  return `<p class="ds-list-sub" role="status">${total} événement(s) affiché(s) — historique complet, du plus récent au plus ancien.</p>${days}${more}${capped}`;
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
      root.innerHTML = timelineHtml({ timeline, limit });
      root.querySelector("[data-timeline-more]")?.addEventListener("click", () => {
        limit = TIMELINE_LIMIT_MAX;
        void reload();
      });
    } catch (error) {
      root.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Activité indisponible.</strong>${esc(describeError(error))}</div>`;
    }
  };
  await reload();
}
