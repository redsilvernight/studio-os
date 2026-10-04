/**
 * UI-4 — Workspace projet : surface de TRAVAIL (à distinguer de l'Accueil,
 * surface de synthèse). Cadre stable (header compact + navigation locale),
 * richesse distribuée par onglet : Vue d'ensemble (résumés), Tâches,
 * Claims, Activité, Décisions.
 *
 * Chaque onglet est soutenu par une capacité réelle : GET /projects/{id} +
 * /state, GET /tasks?project_id, GET /claims?project_id,
 * GET /timeline?project_id, GET /decisions?project_id. Aucun onglet décoratif.
 * Les deep links (#/projects/<id>/<onglet>) représentent l'état et le
 * back/forward navigateur fonctionne (rendu piloté par le hash, sans état JS).
 */
import type { StudioClient } from "../api";
import type { Roadmap, RoadmapDataSource } from "../roadmapTypes";
import { ApiError, parseErrorBody } from "../api";
import type { components } from "../openapi-schema";
import { dsBadge, dsEmptyState, dsSectionHeader, dsSkeleton, dsStatus, dsTechDetails } from "../ds/ds";
import { taskStatusLabel, taskStatusTone } from "../taskStatus";
import { describeError, esc, fmtTime } from "../ui";
import { fetchIdentity } from "../identityApi";
import { renderActivityInto } from "./activity";
import { renderAiIntegrationInto } from "./aiIntegration";
import { renderClaimsInto } from "./claims";
import { renderDecisionsV2 as renderDecisions } from "./decisionsV2";
import { renderMembersInto } from "./members";
import { renderTasksInto } from "./tasks";
import { isRoadmapManagerRole, renderRoadmapInto } from "./roadmap";

type Project = components["schemas"]["Project"];
type ProjectState = components["schemas"]["ProjectState"];
type Task = components["schemas"]["Task"];
type ResourceClaim = components["schemas"]["ResourceClaim"];

export type ProjectTab =
  | "overview"
  | "roadmap"
  | "tasks"
  | "claims"
  | "activity"
  | "decisions"
  | "members"
  | "ai-integration";

export interface ProjectDetailContext {
  client: StudioClient;
  authed: boolean;
  roadmapDataSource?: RoadmapDataSource;
}

export const PROJECT_TABS: ReadonlyArray<{ id: ProjectTab; label: string; suffix: string }> = [
  { id: "overview", label: "Vue d'ensemble", suffix: "" },
  { id: "roadmap", label: "Roadmap", suffix: "/roadmap" },
  { id: "tasks", label: "Tâches", suffix: "/tasks" },
  { id: "claims", label: "Réservations", suffix: "/claims" },
  { id: "activity", label: "Activité", suffix: "/activity" },
  { id: "decisions", label: "Décisions", suffix: "/decisions" },
  { id: "members", label: "Membres", suffix: "/members" },
  { id: "ai-integration", label: "Intégration IA", suffix: "/ai-integration" },
];

/** Libellés FR des statuts (source unique : taskStatus.ts, UI-5). */
const TASK_STATUS_LABEL: Record<string, string> = {
  created: taskStatusLabel("created"),
  in_progress: taskStatusLabel("in_progress"),
  blocked: taskStatusLabel("blocked"),
  completed: taskStatusLabel("completed"),
};

export const OVERVIEW_PREVIEW_LIMIT = 5;
const CLAIM_EXPIRY_SOON_MS = 24 * 60 * 60 * 1000;

/** Teinte DS d'un statut de tâche (source unique : taskStatus.ts, UI-5). */
function taskTone(status: string): "neutral" | "info" | "warning" | "success" {
  return taskStatusTone(status);
}

/** Onglets quotidiens ; les surfaces expertes (Membres, Intégration IA) vivent sous « Plus ». */
export const PROJECT_TABS_MORE: ReadonlyArray<ProjectTab> = ["members", "ai-integration"];

function projectTabLink(projectId: string, entry: (typeof PROJECT_TABS)[number], tab: ProjectTab): string {
  const active = entry.id === tab;
  const current = active ? ` aria-current="page"` : "";
  return `<a class="ds-tab" role="tab" id="ws-tab-${entry.id}" aria-controls="workspace-panel" href="#/projects/${esc(projectId)}${entry.suffix}" aria-selected="${active ? "true" : "false"}" tabindex="${active ? "0" : "-1"}" data-ws-tab="${entry.id}"${current}>${esc(entry.label)}</a>`;
}

/** Navigation locale : 6 onglets visibles + menu « Plus » (liens, deep links préservés). */
export function workspaceTabsHtml(projectId: string, tab: ProjectTab): string {
  const visible = PROJECT_TABS.filter((entry) => !PROJECT_TABS_MORE.includes(entry.id))
    .map((entry) => projectTabLink(projectId, entry, tab))
    .join("");
  const more = PROJECT_TABS.filter((entry) => PROJECT_TABS_MORE.includes(entry.id))
    .map((entry) => projectTabLink(projectId, entry, tab))
    .join("");
  const moreOpen = PROJECT_TABS_MORE.includes(tab) ? " open" : "";
  return `<div class="workspace-nav"><nav class="ds-tabs" role="tablist" aria-label="Sections du projet" data-ws-tabs>${visible}</nav>${more === "" ? "" : `<details class="workspace-more"${moreOpen}><summary class="ds-tab">Plus</summary><div class="workspace-more-list">${more}</div></details>`}</div>`;
}

/** Flèches gauche/droite et Début/Fin entre onglets (activation au clavier via Entrée). */
export function initWorkspaceTabs(root: ParentNode): void {
  const group = root.querySelector("[data-ws-tabs]");
  if (group === null) return;
  const tabs = [...group.querySelectorAll<HTMLAnchorElement>('[role="tab"]')];
  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const next =
          event.key === "ArrowRight"
            ? tabs[(index + 1) % tabs.length]
            : tabs[(index - 1 + tabs.length) % tabs.length];
        next?.focus();
        return;
      }
      if (event.key === "Home") {
        event.preventDefault();
        tabs[0]?.focus();
        return;
      }
      if (event.key === "End") {
        event.preventDefault();
        tabs[tabs.length - 1]?.focus();
      }
    });
  }
}

export function workspaceHeaderHtml(project: Project): string {
  const rawDesc = (project.description ?? "").trim();
  const desc =
    rawDesc === "" ? `<p class="ds-list-sub">Sans description.</p>` : `<p class="workspace-desc">${esc(rawDesc)}</p>`;
  const badge = project.archived ? dsBadge("Archivé", "warning") : dsBadge("Actif", "success");
  return `<div class="workspace-head"><p class="ds-list-sub workspace-back"><a href="#/projects">← Tous les projets</a> · <code class="mono">${esc(project.slug)}</code></p>` +
    `<div class="workspace-title-row"><h1>${esc(project.name)}</h1>${badge}</div>` +
    `${desc}` +
    dsTechDetails([
      { label: "Identifiant", value: project.id, mono: true },
      { label: "Version", value: String(project.version), mono: true },
      { label: "Créé le", value: fmtTime(project.created_at) },
      { label: "Mis à jour le", value: fmtTime(project.updated_at) },
    ]) +
    `</div>`;
}

/** Éléments demandant un regard : tâches bloquées + claims expirant sous 24 h. */
export function projectAttentionItems(state: ProjectState, now: number): string[] {
  const items: string[] = [];
  for (const task of state.active_tasks) {
    if (task.status === "blocked") items.push(`Tâche bloquée : ${task.title}`);
  }
  for (const claim of state.active_claims) {
    const remaining = new Date(claim.expires_at).getTime() - now;
    if (remaining <= CLAIM_EXPIRY_SOON_MS) items.push(`Réservation expirant bientôt : ${claim.resource_path}`);
  }
  return items;
}

export interface CurrentStep {
  title: string;
  phaseTitle: string;
  progress: string | null;
}

/** Étape courante d'une roadmap active (null si aucune ou introuvable). */
export function currentRoadmapStep(roadmap: Roadmap | null): CurrentStep | null {
  if (roadmap === null || roadmap.status !== "active" || !roadmap.current_step_key) return null;
  for (const phase of roadmap.phases ?? []) {
    const step = (phase.steps ?? []).find((entry) => entry.key === roadmap.current_step_key);
    if (step !== undefined) {
      const total = step.acceptance_criteria?.length ?? 0;
      const checked = step.criteria_checked?.length ?? 0;
      return { title: step.title, phaseTitle: phase.title, progress: total > 0 ? `${checked}/${total} critères` : null };
    }
  }
  return null;
}

/** Santé du projet : bloquée > à surveiller > en bonne voie (dérivée de l'état réel). */
export function projectHealthSummary(state: ProjectState, now: number): { state: "warning" | "info" | "success"; label: string } {
  const attention = projectAttentionItems(state, now);
  if (state.active_tasks.some((t) => t.status === "blocked")) return { state: "warning", label: "Blocage à lever" };
  if (attention.length > 0) return { state: "info", label: "À surveiller" };
  return { state: "success", label: "En bonne voie" };
}

/** Héros de la vue d'ensemble : objectif, santé, étape courante, blocages. */
export function projectHeroHtml(project: Project, state: ProjectState, step: CurrentStep | null, now: number = Date.now()): string {
  const health = projectHealthSummary(state, now);
  const blockers = projectAttentionItems(state, now);
  const objective = (project.description ?? "").trim();
  const stepBody =
    step === null
      ? `<p class="ds-list-sub">Aucune étape courante : <a href="#/projects/${esc(project.id)}/roadmap">ouvrir la roadmap</a>.</p>`
      : `<p class="workspace-step-title">${esc(step.title)}</p><p class="ds-list-sub">${esc(step.phaseTitle)}${step.progress === null ? "" : ` · ${esc(step.progress)}`} — <a href="#/projects/${esc(project.id)}/roadmap">voir la roadmap</a></p>`;
  const blockersBody =
    blockers.length === 0
      ? `<p class="ds-list-sub">Aucun blocage.</p>`
      : `<ul class="ds-list">${blockers.slice(0, 3).map((item) => `<li class="ds-list-item"><div class="grow">${esc(item)}</div></li>`).join("")}</ul>${blockers.length > 3 ? `<p class="ds-list-sub">+ ${blockers.length - 3} autre(s).</p>` : ""}`;
  return `<section class="workspace-hero" aria-label="Situation du projet">` +
    `<div class="workspace-hero-main"><p class="ds-hero-eyebrow">Objectif</p>` +
    `<p class="workspace-objective">${objective === "" ? "Aucun objectif renseigné." : esc(objective)}</p>` +
    `<p class="workspace-health">${dsStatus(health.state, health.label)}</p></div>` +
    `<div class="workspace-hero-step"><p class="ds-hero-eyebrow">Étape courante</p>${stepBody}</div>` +
    `<div class="workspace-hero-blockers"><p class="ds-hero-eyebrow">Blocages</p>${blockersBody}</div>` +
    `</section>`;
}

/**
 * Vue d'ensemble : répond à « Où en est ce projet ? » avec des résumés
 * (5 max) + navigation vers les onglets. Jamais de Kanban, table claims,
 * timeline ou liste de décisions complets ici.
 */
export function projectOverviewHtml(project: Project, state: ProjectState, now: number = Date.now(), step: CurrentStep | null = null): string {
  const taskPreview = state.active_tasks.slice(0, OVERVIEW_PREVIEW_LIMIT);
  const claimPreview = state.active_claims.slice(0, OVERVIEW_PREVIEW_LIMIT);
  const tasksBody =
    state.active_tasks.length === 0
      ? `<p class="ds-list-sub">Aucune tâche active.</p>`
      : `<ul class="ds-list">${taskPreview
          .map(
            (task: Task) =>
              `<li class="ds-list-item"><div class="grow"><div class="ds-list-title"><a href="#/tasks/${esc(task.id)}">${esc(task.title)}</a></div>` +
              `<div class="ds-list-sub">${esc(TASK_STATUS_LABEL[task.status] ?? task.status)}</div></div>${dsBadge(TASK_STATUS_LABEL[task.status] ?? task.status, taskTone(task.status))}</li>`,
          )
          .join("")}</ul>${state.active_tasks.length > taskPreview.length ? `<p class="ds-list-sub">+ ${state.active_tasks.length - taskPreview.length} autre(s).</p>` : ""}`;

  const claimsBody =
    state.active_claims.length === 0
      ? `<p class="ds-list-sub">Aucune réservation active.</p>`
      : `<ul class="ds-list">${claimPreview
          .map(
            (claim: ResourceClaim) =>
              `<li class="ds-list-item"><div class="grow"><div class="ds-list-title"><code class="mono">${esc(claim.resource_path)}</code></div>` +
              `<div class="ds-list-sub">${esc(claim.resource_type)} · expire ${esc(fmtTime(claim.expires_at))}</div></div></li>`,
          )
          .join("")}</ul>${state.active_claims.length > claimPreview.length ? `<p class="ds-list-sub">+ ${state.active_claims.length - claimPreview.length} autre(s).</p>` : ""}`;

  return `<div class="workspace-overview">` +
    projectHeroHtml(project, state, step, now) +
    `<section class="workspace-section" aria-label="Tâches actives">${dsSectionHeader(`Tâches actives (${state.active_tasks.length})`, { label: "Voir les tâches", href: `#/projects/${esc(project.id)}/tasks` })}${tasksBody}</section>` +
    `<section class="workspace-section" aria-label="Réservations actives">${dsSectionHeader(`Réservations actives (${state.active_claims.length})`, { label: "Voir les réservations", href: `#/projects/${esc(project.id)}/claims` })}${claimsBody}</section>` +
    `<section class="workspace-section" aria-label="Historique et décisions"><p class="ds-list-sub">L'historique complet vit dans <a href="#/projects/${esc(project.id)}/activity">Activité</a>, les décisions liées au projet dans <a href="#/projects/${esc(project.id)}/decisions">Décisions</a>.</p></section>` +
    `</div>`;
}

async function fetchProject(client: StudioClient, id: string): Promise<Project> {
  const result = await client.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: id } } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

async function fetchState(client: StudioClient, id: string): Promise<ProjectState> {
  const result = await client.GET("/api/v1/projects/{project_id}/state", { params: { path: { project_id: id } } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export async function renderProjectDetail(
  root: HTMLElement,
  ctx: ProjectDetailContext,
  projectId: string,
  tab: ProjectTab,
  roadmapId?: string,
): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = dsEmptyState(
      "Connectez-vous pour ouvrir ce projet",
      "Saisissez votre jeton machine pour charger l'espace de travail du projet.",
    );
    return;
  }
  root.innerHTML = dsSkeleton(4);
  let project: Project;
  let state: ProjectState;
  try {
    [project, state] = await Promise.all([fetchProject(ctx.client, projectId), fetchState(ctx.client, projectId)]);
  } catch (error) {
    root.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Projet indisponible.</strong>${esc(describeError(error))}</div>`;
    return;
  }
  root.innerHTML =
    `<div class="workspace">${workspaceHeaderHtml(project)}${workspaceTabsHtml(project.id, tab)}<div class="workspace-panel" role="tabpanel" id="workspace-panel" aria-labelledby="ws-tab-${tab}"></div></div>`;
  initWorkspaceTabs(root);
  const panel = root.querySelector<HTMLElement>("#workspace-panel");
  if (panel === null) return;
  if (tab === "overview") {
    let step: CurrentStep | null = null;
    if (ctx.roadmapDataSource !== undefined) {
      try {
        step = currentRoadmapStep(await ctx.roadmapDataSource.load(project.id));
      } catch {
        step = null;
      }
    }
    panel.innerHTML = projectOverviewHtml(project, state, Date.now(), step);
    return;
  }
  if (tab === "tasks") {
    panel.innerHTML = `<p class="ds-list-sub">Les tâches du projet — même présentation que la page Tâches, filtrées sur ce projet. <a href="#/tasks">Toutes les tâches</a>.</p><div data-slot></div>`;
    const slot = panel.querySelector<HTMLElement>("[data-slot]");
    if (slot !== null) {
      await renderTasksInto(slot, {
        client: ctx.client,
        authed: ctx.authed,
        projectId: project.id,
        scopeLabel: `projet ${project.slug}`,
        headingLevel: 2,
      });
    }
    return;
  }
  if (tab === "roadmap") {
    if (ctx.roadmapDataSource === undefined) {
      panel.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Roadmap indisponible.</strong> La source de données n'est pas configurée.</div>`;
      return;
    }
    const canManageLifecycle =
      ctx.roadmapDataSource.demo === true || isRoadmapManagerRole((await fetchIdentity(ctx.client))?.role ?? null);
    await renderRoadmapInto(panel, {
      dataSource: ctx.roadmapDataSource,
      projectId: project.id,
      projectName: project.name,
      roadmapId,
      canManageLifecycle,
    });
    return;
  }
  if (tab === "claims") {
    panel.innerHTML =
      `<p class="ds-list-sub">Une réservation signale qu'une ressource est en cours d'utilisation, sans jamais bloquer Git ni les écritures. Un chevauchement reste accepté et est signalé dans l'onglet Activité.</p><div data-slot></div>`;
    const slot = panel.querySelector<HTMLElement>("[data-slot]");
    if (slot !== null) {
      await renderClaimsInto(slot, { client: ctx.client, projectId: project.id, authed: ctx.authed });
    }
    return;
  }
  if (tab === "activity") {
    await renderActivityInto(panel, { client: ctx.client, projectId: project.id, authed: ctx.authed });
    return;
  }
  if (tab === "members") {
    const identity = await fetchIdentity(ctx.client);
    await renderMembersInto(panel, {
      client: ctx.client,
      projectId: project.id,
      authed: ctx.authed,
      isAdmin: identity?.role === "admin",
      selfId: identity?.user_id ?? null,
    });
    return;
  }
  if (tab === "ai-integration") {
    await renderAiIntegrationInto(panel, { client: ctx.client, projectId: project.id });
    return;
  }
  const intro = document.createElement("p");
  intro.className = "ds-list-sub";
  intro.textContent = "Seules les décisions liées à ce projet (project_id) apparaissent ici ; les décisions globales restent sur la page Décisions.";
  const slot = document.createElement("div");
  panel.append(intro, slot);
  await renderDecisions(slot, { client: ctx.client, authed: ctx.authed, projectId: project.id });
}
