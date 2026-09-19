/**
 * UI-3 — Accueil calme (remplace le cockpit DASH-1).
 *
 * Densité = limite haute : résumé (3 indicateurs) + Projets (3 max) +
 * Travail en cours (5 max) + À examiner (3 max) + état système compact.
 * Le reste vit sur ses pages : Kanban et détail → #/tasks, transferts →
 * #/transfers, diagnostics → Inspector, activité → onglet projet (UI-4).
 *
 * Dette de migration : les actions Approve / Request changes
 * (ai_work_review) restent sur l'Accueil en format discret jusqu'à la page
 * Review dédiée (UI-8) — 0 perte fonctionnelle. Les autres kinds n'ont
 * aucune action car aucun backend/frontend ne les rend actionnables.
 *
 * Données = endpoints existants uniquement, aucune invention : GET
 * /healthz, /api/v1/projects, /api/v1/tasks, /api/v1/review-queue,
 * /api/v1/transfers. La présence agents (Derived) est volontairement
 * absente du résumé : jamais canonique, donc jamais affichée ici.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { joinUrl } from "../config";
import { dsBadge, dsEmptyState, dsMetric, dsPageHeader, dsSectionHeader, dsSkeleton, dsStatus } from "../ds/ds";
import { resolveReview, type ReviewResolution } from "../reviewApi";
import { describeError, esc } from "../ui";
import type { components } from "../openapi-schema";

type Project = components["schemas"]["Project"];
type Task = components["schemas"]["Task"];
type Transfer = components["schemas"]["Transfer"];
type ReviewQueue = components["schemas"]["ReviewQueue"];
type ReviewQueueItem = ReviewQueue["items"][number];

export const HOME_TASK_LIMIT = 100;
export const HOME_PROJECT_LIMIT = 3;
export const HOME_WORK_LIMIT = 5;
export const HOME_REVIEW_LIMIT = 3;

const REVIEW_KIND_LABEL: Record<ReviewQueueItem["kind"], string> = {
  ai_work_review: "IA",
  decision_proposal: "Décision",
  resource_conflict: "Conflit",
  build_failure: "Build",
  pr_ready: "PR",
};

const TASK_STATUS_LABEL: Record<string, string> = {
  created: "À faire",
  in_progress: "En cours",
  blocked: "Bloquée",
  completed: "Terminée",
};

/** Sub-title for a review-queue row: AI work → agent, decision → readable_id,
 * conflict → resource path, build → workflow + branch, PR → number + branch. */
export function reviewQueueItemDetail(item: ReviewQueueItem): string {
  switch (item.kind) {
    case "ai_work_review":
      return `agent ${shortAgent(item.agent_id)}`;
    case "decision_proposal":
      return item.readable_id;
    case "resource_conflict":
      return item.resource_path;
    case "build_failure":
      return `${item.workflow_name} on ${item.branch}`;
    case "pr_ready":
      return `PR #${item.pr_number} ${item.head_branch} → ${item.base_branch}`;
  }
}

function shortAgent(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

export type HomeResult<T> = { ok: true; value: T } | { ok: false; message: string };

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

async function settle<T>(promise: Promise<T>): Promise<HomeResult<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

export interface HealthInfo {
  reachable: boolean;
}

export async function checkHealth(baseUrl: string): Promise<HealthInfo> {
  try {
    const response = await fetch(joinUrl(baseUrl, "/healthz"));
    return { reachable: response.ok };
  } catch {
    return { reachable: false };
  }
}

export interface OverviewContext {
  client: StudioClient;
  baseUrl: string;
  authed: boolean;
}

export async function renderOverview(root: HTMLElement, ctx: OverviewContext): Promise<void> {
  root.innerHTML = homeLoadingHtml();
  const health = await checkHealth(ctx.baseUrl);
  if (!ctx.authed) {
    root.innerHTML = homePageHtml({
      health,
      projects: { ok: true, value: [] },
      tasks: { ok: true, value: [] },
      reviewQueue: { ok: true, value: null },
      transfers: { ok: true, value: [] },
      authed: false,
    });
    return;
  }
  const [projects, tasks, reviewQueue, transfers] = await Promise.all([
    settle(unwrap(ctx.client.GET("/api/v1/projects"))),
    settle(
      unwrap(
        ctx.client.GET("/api/v1/tasks", { params: { query: { limit: HOME_TASK_LIMIT, offset: 0 } } }),
      ),
    ),
    settle(unwrap(ctx.client.GET("/api/v1/review-queue"))),
    settle(unwrap(ctx.client.GET("/api/v1/transfers"))),
  ]);
  root.innerHTML = homePageHtml({ health, projects, tasks, reviewQueue, transfers, authed: ctx.authed });
  bindReviewActions(root, ctx);
}

export interface HomeData {
  health: HealthInfo;
  projects: HomeResult<Project[]>;
  tasks: HomeResult<Task[]>;
  reviewQueue: HomeResult<ReviewQueue | null>;
  transfers: HomeResult<Transfer[]>;
  authed: boolean;
}

export function homeLoadingHtml(): string {
  return `${dsPageHeader("Accueil", "L'essentiel en un coup d'œil.")}${dsSkeleton(4)}`;
}

export function homePageHtml(data: HomeData): string {
  const projectList = data.projects.ok ? data.projects.value : [];
  const taskList = data.tasks.ok ? data.tasks.value : [];
  const reviewTotal = data.reviewQueue.ok ? (data.reviewQueue.value?.items.length ?? 0) : null;
  const activeProjects = projectList.filter((p) => !p.archived).length;
  const activeTasks = taskList.filter((t) => t.status !== "completed").length;
  const sections = [
    dsPageHeader("Accueil", "L'essentiel en un coup d'œil : projets, travail en cours et points à examiner."),
    homeHealthHtml(data.health),
    homeMetricsHtml(activeProjects, activeTasks, reviewTotal),
    homeProjectsHtml(data.projects),
    homeTasksHtml(data.tasks, projectList),
    homeReviewHtml(data.reviewQueue, data.authed),
    homeTransferSignalHtml(data.transfers),
  ];
  if (!data.authed) {
    sections.push(
      dsEmptyState(
        "Connectez-vous pour voir vos données",
        "Saisissez votre jeton machine pour charger projets, tâches et éléments à examiner.",
      ),
    );
  }
  return `<div class="home">${sections.join("")}</div>`;
}

export function homeHealthHtml(health: HealthInfo): string {
  return `<p class="home-health">${
    health.reachable ? dsStatus("success", "Système opérationnel") : dsStatus("danger", "Système indisponible")
  }</p>`;
}

export function homeMetricsHtml(activeProjects: number, activeTasks: number, reviewTotal: number | null): string {
  return `<section class="home-section" aria-label="Résumé"><div class="home-metrics">` +
    `${dsMetric("Projets actifs", activeProjects)}` +
    `${dsMetric("Tâches en cours", activeTasks)}` +
    `${dsMetric("À examiner", reviewTotal ?? "—")}` +
    `</div></section>`;
}

/** Projets récents non archivés d'abord (tri updated_at desc), 3 max. */
export function pickHomeProjects(projects: Project[]): Project[] {
  return [...projects]
    .sort((a, b) => {
      if (a.archived !== b.archived) return a.archived ? 1 : -1;
      return b.updated_at.localeCompare(a.updated_at);
    })
    .slice(0, HOME_PROJECT_LIMIT);
}

export function homeProjectsHtml(result: HomeResult<Project[]>): string {
  const header = dsSectionHeader("Projets", { label: "Voir tous les projets", href: "#/projects" });
  if (!result.ok) {
    return `<section class="home-section home-section--projects" aria-labelledby="home-projets"><div id="home-projets">${header}</div><div class="ds-notice ds-notice--danger"><strong>Projets indisponibles.</strong>${esc(result.message)}</div></section>`;
  }
  if (result.value.length === 0) {
    return `<section class="home-section home-section--projects" aria-labelledby="home-projets"><div id="home-projets">${header}</div>${dsEmptyState("Aucun projet", "Créez votre premier projet pour commencer.", { label: "Voir les projets", href: "#/projects" })}</section>`;
  }
  const items = pickHomeProjects(result.value)
    .map((p) => {
      const rawDesc = p.description ?? "";
      const desc = rawDesc.trim() === "" ? "" : `<div class="ds-list-sub">${esc(rawDesc)}</div>`;
      const badge = p.archived ? dsBadge("Archivé", "warning") : "";
      return `<li class="ds-list-item"><div class="grow"><div class="ds-list-title"><a href="#/projects/${esc(p.id)}">${esc(p.name)}</a></div>${desc}</div>${badge}</li>`;
    })
    .join("");
  return `<section class="home-section home-section--projects" aria-labelledby="home-projets"><div id="home-projets">${header}</div><ul class="ds-list ds-list--card">${items}</ul></section>`;
}

function taskTone(status: string): "neutral" | "info" | "warning" | "success" {
  switch (status) {
    case "in_progress":
      return "info";
    case "blocked":
      return "warning";
    case "completed":
      return "success";
    default:
      return "neutral";
  }
}

export function homeTasksHtml(result: HomeResult<Task[]>, projects: Project[]): string {
  const header = dsSectionHeader("Travail en cours", { label: "Voir toutes les tâches", href: "#/tasks" });
  if (!result.ok) {
    return `<section class="home-section home-section--work" aria-labelledby="home-travail"><div id="home-travail">${header}</div><div class="ds-notice ds-notice--danger"><strong>Tâches indisponibles.</strong>${esc(result.message)}</div></section>`;
  }
  const active = result.value.filter((t) => t.status !== "completed").slice(0, HOME_WORK_LIMIT);
  if (active.length === 0) {
    return `<section class="home-section home-section--work" aria-labelledby="home-travail"><div id="home-travail">${header}</div>${dsEmptyState("Rien en cours", "Aucune tâche active pour le moment.", { label: "Voir les tâches", href: "#/tasks" })}</section>`;
  }
  const names = new Map(projects.map((p) => [p.id, p.name]));
  const items = active
    .map((t) => {
      const project = names.get(t.project_id) ?? "Projet";
      const label = TASK_STATUS_LABEL[t.status] ?? t.status;
      return `<li class="ds-list-item"><div class="grow"><div class="ds-list-title"><a href="#/tasks/${esc(t.id)}">${esc(t.title)}</a></div><div class="ds-list-sub">${esc(project)} · ${esc(label)}</div></div>${dsBadge(label, taskTone(t.status))}</li>`;
    })
    .join("");
  return `<section class="home-section home-section--work" aria-labelledby="home-travail"><div id="home-travail">${header}</div><ul class="ds-list ds-list--card">${items}</ul></section>`;
}

export function reviewActionsHtml(item: ReviewQueueItem, authed: boolean): string {
  if (item.kind !== "ai_work_review") return "";
  return `<span class="home-review-actions"><button class="ds-btn ds-btn--sm" type="button" data-review-approve="${esc(item.id)}" ${authed ? "" : "disabled"}>Approuver</button>` +
    `<button class="ds-btn ds-btn--sm" type="button" data-review-changes="${esc(item.id)}" ${authed ? "" : "disabled"}>Demander des modifications</button></span>`;
}

export function homeReviewHtml(result: HomeResult<ReviewQueue | null>, authed: boolean): string {
  const header = dsSectionHeader("À examiner", { label: "Voir les décisions", href: "#/decisions" });
  if (!result.ok) {
    return `<section class="home-section home-section--review" aria-labelledby="home-examiner"><div id="home-examiner">${header}</div><div class="ds-notice ds-notice--danger"><strong>File d'examen indisponible.</strong>${esc(result.message)}</div></section>`;
  }
  const items = result.value?.items ?? [];
  if (items.length === 0) {
    return `<section class="home-section home-section--review" aria-labelledby="home-examiner"><div id="home-examiner">${header}</div>${dsEmptyState("Rien à examiner", "Aucun élément n'attend une décision humaine.", { label: "Voir les décisions", href: "#/decisions" })}</section>`;
  }
  const shown = items.slice(0, HOME_REVIEW_LIMIT);
  const rows = shown
    .map((item) => {
      const title = item.title.length > 80 ? `${item.title.slice(0, 80)}…` : item.title;
      return `<li class="ds-list-item"><div class="grow"><div class="ds-list-title">${esc(title)}</div><div class="ds-list-sub">${esc(REVIEW_KIND_LABEL[item.kind])} · ${esc(reviewQueueItemDetail(item))}</div></div>${reviewActionsHtml(item, authed)}</li>`;
    })
    .join("");
  const more = items.length > shown.length ? `<p class="ds-list-sub">+ ${items.length - shown.length} autre(s) — voir les décisions.</p>` : "";
  return `<section class="home-section home-section--review" aria-labelledby="home-examiner"><div id="home-examiner">${header}</div><p class="ds-list-sub">${items.length} élément(s) à examiner.</p><ul class="ds-list ds-list--card">${rows}</ul>${more}<div data-review-msg class="ds-list-sub" role="status"></div></section>`;
}

/** Signal discret uniquement si un envoi est réellement en cours. */
export function homeTransferSignalHtml(result: HomeResult<Transfer[]>): string {
  if (!result.ok) return "";
  const pending = result.value.filter((t) => t.status === "created" || t.status === "uploading");
  if (pending.length === 0) return "";
  return `<div class="ds-notice ds-notice--info"><strong>Transfert en cours.</strong>${pending.length} envoi(s) en cours — <a href="#/transfers">voir les transferts</a>.</div>`;
}

function bindReviewActions(root: HTMLElement, ctx: OverviewContext): void {
  const buttons = root.querySelectorAll<HTMLButtonElement>("[data-review-approve], [data-review-changes]");
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset["reviewApprove"] ?? button.dataset["reviewChanges"] ?? "";
      const resolution: ReviewResolution = button.dataset["reviewApprove"] !== undefined ? "approved" : "changes_requested";
      buttons.forEach((other) => {
        other.disabled = true;
      });
      resolveReview(ctx.client, id, resolution)
        .then(() => void renderOverview(root, ctx))
        .catch((error: unknown) => {
          setReviewMsg(root, describeError(error));
          buttons.forEach((other) => {
            other.disabled = false;
          });
        });
    });
  });
}

function setReviewMsg(root: HTMLElement, text: string): void {
  const node = root.querySelector("[data-review-msg]");
  if (node !== null) node.textContent = text;
}
