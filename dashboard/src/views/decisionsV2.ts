/**
 * UI-8 — Decisions & Review : surface unifiée pour ce qui demande une action
 * (Review Queue) et l'historique des décisions durables.
 *
 * Deux onglets distincts :
 *   - "À examiner" : file d'attente agrégée (ai_work_review, decision_proposal,
 *     resource_conflict, build_failure, pr_ready). Seuls les ai_work_review
 *     ont une action réelle (Approuver / Demander des modifications via
 *     PATCH /ai-work/{id}). Les autres kinds sont affichés honnêtement sans
 *     bouton générique.
 *   - "Décisions" : liste des décisions enregistrées (proposed/accepted/
 *     superseded) avec création en modale (POST /decisions + Idempotency-Key).
 *
 * Liens vers Agents (#/agents/<id>), Tâches (#/tasks/<id>), Projets
 * (#/projects/<id>) quand les IDs sont fiables. Infos techniques en <details>.
 *
 * Reprend la route globale #/decisions. La vue projet-scopée (#/projects/<id>/decisions)
 * réutilise le même renderer via un context projectId.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { getToken } from "../auth";
import { decodeJwtSubject, isUuid } from "../creationsApi";
import {
  dsBadge,
  dsEmptyState,
  dsPageHeader,
  dsSectionHeader,
  dsSkeleton,
  dsTabsHtml,
  dsModalHtml,
  dsField,
  focusDsErrorBox,
  initDsTabs,
  openDsDialog,
  closeDsDialog,
  dsNotify,
  dsAgentBadge,
} from "../ds/ds";
import { resolveReview, type ReviewResolution } from "../reviewApi";
import { describeError, esc, fmtTime, newUuid, shortId } from "../ui";
import type { components } from "../openapi-schema";

type Decision = components["schemas"]["Decision"];
type DecisionCreate = components["schemas"]["DecisionCreate"];
type ReviewQueue = components["schemas"]["ReviewQueue"];
type ReviewQueueItem = ReviewQueue["items"][number];

export type { Decision, DecisionCreate, ReviewQueue, ReviewQueueItem };

export interface DecisionsContext {
  client: StudioClient;
  authed: boolean;
  projectId?: string;
}

export const REVIEW_KIND_LABEL: Record<ReviewQueueItem["kind"], string> = {
  ai_work_review: "Travail IA",
  decision_proposal: "Proposition de décision",
  resource_conflict: "Conflit de réservation",
  build_failure: "Échec de build",
  pr_ready: "PR ouverte",
  roadmap_proposal: "Proposition de roadmap",
};

export const REVIEW_KIND_TONE: Record<ReviewQueueItem["kind"], "neutral" | "info" | "warning" | "danger" | "ai"> = {
  ai_work_review: "ai",
  decision_proposal: "info",
  resource_conflict: "warning",
  build_failure: "danger",
  pr_ready: "info",
  roadmap_proposal: "warning",
};

export const DECISION_STATUS_LABEL: Record<string, string> = {
  proposed: "Proposée",
  accepted: "Acceptée",
  superseded: "Remplacée",
};

export const DECISION_STATUS_TONE: Record<string, "neutral" | "info" | "warning" | "success" | "danger"> = {
  proposed: "info",
  accepted: "success",
  superseded: "warning",
};

export const PROPOSER_TYPE_LABEL: Record<string, string> = {
  user: "Utilisateur",
  agent: "Agent",
  system: "Système",
};

/** Détail lisible selon le kind (agent, readable_id, resource_path, workflow+branch, PR#). */
export function reviewQueueItemDetail(item: ReviewQueueItem): string {
  switch (item.kind) {
    case "ai_work_review":
      return `agent ${shortId(item.agent_id)}`;
    case "decision_proposal":
      return item.readable_id;
    case "resource_conflict":
      return item.resource_path;
    case "build_failure":
      return `${item.workflow_name} sur ${item.branch}`;
    case "pr_ready":
      return `PR #${item.pr_number} ${item.head_branch} → ${item.base_branch}`;
    case "roadmap_proposal":
      return item.scope === "revision"
        ? `révision ${item.revision_no} de « ${item.title} »`
        : `« ${item.title} » soumise pour validation`;
  }
}

/** Charge la review queue (global ou project-scopé). */
async function fetchReviewQueue(
  client: StudioClient,
  projectId?: string,
): Promise<ReviewQueue> {
  const params: Record<string, string> = {};
  if (projectId !== undefined) params.project_id = projectId;
  params.conflict_window_hours = "24";
  const result = await client.GET("/api/v1/review-queue", { params: { query: params } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Charge les décisions (global ou project-scopé). */
async function fetchDecisions(
  client: StudioClient,
  projectId?: string,
): Promise<Decision[]> {
  const params: Record<string, string> = {};
  if (projectId !== undefined) params.project_id = projectId;
  const result = await client.GET("/api/v1/decisions", { params: { query: params } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Crée une décision avec Idempotency-Key. */
async function createDecision(
  client: StudioClient,
  decisionIn: DecisionCreate,
  idempotencyKey: string,
): Promise<Decision> {
  const result = await client.POST("/api/v1/decisions", {
    body: decisionIn,
    headers: { "Idempotency-Key": idempotencyKey },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

/** Génère une clé d'idempotence côté client (UUID v4 simple). */
function generateIdempotencyKey(): string {
  return newUuid();
}

/** ------------------- RENDU REVIEW QUEUE ------------------- */

export function reviewItemHtml(item: ReviewQueueItem, authed: boolean): string {
  const kindLabel = REVIEW_KIND_LABEL[item.kind];
  const kindTone = REVIEW_KIND_TONE[item.kind];
  const detail = reviewQueueItemDetail(item);
  const time = fmtTime(item.requested_at);
  const projectLink = item.project_id
    ? `<a href="#/projects/${esc(item.project_id)}">${esc(shortId(item.project_id))}</a>`
    : "—";
  const taskLink = item.task_id
    ? `<a href="#/tasks/${esc(item.task_id)}">${esc(shortId(item.task_id))}</a>`
    : "—";

  let actionsHtml = "";
  if (item.kind === "ai_work_review") {
    if (authed) {
      actionsHtml = `<div class="review-actions" role="group" aria-label="Actions pour ce travail IA">` +
        `<button class="ds-btn ds-btn--sm ds-btn--primary" type="button" data-review-approve="${esc(item.id)}">Approuver</button>` +
        `<button class="ds-btn ds-btn--sm" type="button" data-review-changes="${esc(item.id)}">Demander des modifications</button>` +
        `</div>`;
    } else {
      actionsHtml = `<div class="review-actions" role="group" aria-label="Actions pour ce travail IA">` +
        `<button class="ds-btn ds-btn--sm ds-btn--primary" type="button" data-review-approve="${esc(item.id)}" disabled>Approuver</button>` +
        `<button class="ds-btn ds-btn--sm" type="button" data-review-changes="${esc(item.id)}" disabled>Demander des modifications</button>` +
        `</div>`;
    }
  } else if (item.kind === "roadmap_proposal") {
    actionsHtml = `<div class="review-actions" role="group" aria-label="Actions pour cette proposition de roadmap">` +
      `<a class="ds-btn ds-btn--sm ds-btn--primary" href="#/projects/${esc(item.project_id)}/roadmap">Examiner dans Roadmap</a></div>`;
  } else {
    actionsHtml = `<span class="review-no-action ds-list-sub" aria-label="Aucune action disponible">Aucune action disponible dans cette interface</span>`;
  }

  const techDetails = `
    <details class="review-tech"><summary>Informations techniques</summary><dl>
      <div><dt>Identifiant</dt><dd><code class="mono">${esc(item.id)}</code></dd></div>
      <div><dt>Type</dt><dd>${esc(item.kind)}</dd></div>
      <div><dt>Projet</dt><dd>${item.project_id ? `<code class="mono">${esc(item.project_id)}</code>` : "—"}</dd></div>
      ${item.task_id ? `<div><dt>Tâche</dt><dd><code class="mono">${esc(item.task_id)}</code></dd></div>` : ""}
      ${item.kind === "ai_work_review" ? `<div><dt>Agent</dt><dd><code class="mono">${esc(item.agent_id)}</code></dd></div>` : ""}
      ${item.kind === "decision_proposal" ? `<div><dt>Proposé par</dt><dd>${esc(item.proposed_by_type)}</dd></div>` : ""}
      ${item.kind === "build_failure" ? `<div><dt>Workflow</dt><dd>${esc(item.workflow_name)}</dd></div><div><dt>Branche</dt><dd>${esc(item.branch)}</dd></div><div><dt>Commit</dt><dd><code class="mono">${esc(item.commit_sha)}</code></dd></div>${item.conclusion ? `<div><dt>Conclusion</dt><dd>${esc(item.conclusion)}</dd></div>` : ""}` : ""}
      ${item.kind === "pr_ready" ? `<div><dt>PR</dt><dd>#${item.pr_number}</dd></div><div><dt>Branche source</dt><dd>${esc(item.head_branch)}</dd></div><div><dt>Branche cible</dt><dd>${esc(item.base_branch)}</dd></div>` : ""}
      ${item.kind === "resource_conflict" ? `<div><dt>Ressource</dt><dd><code class="mono">${esc(item.resource_path)}</code></dd></div>` : ""}
      <div><dt>Demandé le</dt><dd>${esc(time)}</dd></div>
    </dl></details>`;

  return `<li class="ds-list-item review-item" data-kind="${esc(item.kind)}" data-id="${esc(item.id)}">` +
    `<div class="grow">` +
    `<div class="review-item-header">` +
    `<div class="review-item-title-row">` +
    `<span class="review-item-title">${esc(item.title)}</span>` +
    `${dsBadge(kindLabel, kindTone)}` +
    `</div>` +
    `<div class="review-item-meta">` +
    `<span>Projet: ${projectLink}</span>` +
    `<span class="meta-sep" aria-hidden="true">·</span>` +
    `<span>Tâche: ${taskLink}</span>` +
    `<span class="meta-sep" aria-hidden="true">·</span>` +
    `<span>${detail}</span>` +
    `<span class="meta-sep" aria-hidden="true">·</span>` +
    `<span>${esc(time)}</span>` +
    `</div>` +
    `</div>` +
    `<div class="review-item-actions">${actionsHtml}</div>` +
    `${techDetails}` +
    `</div>` +
    `</li>`;
}

export function reviewQueueHtml(
  reviewQueue: ReviewQueue | null,
  authed: boolean,
  projectId?: string,
  reviewError?: string,
): string {
  // Sur la page globale, un lien « Voir les décisions » pointerait vers elle-même :
  // le lien de sortie n'existe que dans l'espace projet.
  const header = dsSectionHeader("À examiner", projectId ? { label: "Voir la file globale", href: "#/decisions" } : undefined);

  if (reviewError !== undefined) {
    return `<section class="review-section" aria-labelledby="review-heading">${header}` +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>File d'examen indisponible.</strong>${esc(reviewError)}</div></section>`;
  }

  const items = reviewQueue?.items ?? [];
  if (items.length === 0) {
    return `<section class="review-section" aria-labelledby="review-heading">${header}` +
      dsEmptyState(
        "Rien à examiner",
        "Aucun élément n'attend une décision humaine pour le moment.",
        projectId ? { label: "Voir la file globale", href: "#/decisions" } : undefined,
      ) + `</section>`;
  }

  const rows = items.map((item) => reviewItemHtml(item, authed)).join("");
  return `<section class="review-section" aria-labelledby="review-heading">${header}` +
    `<p class="ds-list-sub">${items.length} élément(s) à examiner.</p>` +
    `<ul class="ds-list review-list" role="list">${rows}</ul></section>`;
}

/** ------------------- RENDU DECISIONS ------------------- */

export function decisionHtml(decision: Decision, authed: boolean): string {
  const statusLabel = DECISION_STATUS_LABEL[decision.status] ?? decision.status;
  const statusTone = DECISION_STATUS_TONE[decision.status] ?? "neutral";
  const proposerLabel = PROPOSER_TYPE_LABEL[decision.proposed_by_type] ?? decision.proposed_by_type;
  const time = fmtTime(decision.created_at);
  const projectLink = decision.project_id
    ? `<a href="#/projects/${esc(decision.project_id)}">${esc(shortId(decision.project_id))}</a>`
    : "—";
  const taskLink = decision.task_id
    ? `<a href="#/tasks/${esc(decision.task_id)}">${esc(shortId(decision.task_id))}</a>`
    : "—";
  const agentLink = decision.proposed_by_type === "agent"
    ? `<a href="#/agents/${esc(decision.proposed_by_id)}">${dsAgentBadge(decision.proposed_by_id)}</a>`
    : `${esc(proposerLabel)} <code class="mono" title="${esc(decision.proposed_by_id)}">${esc(shortId(decision.proposed_by_id))}</code>`;

  const techDetails = `
    <details class="decision-tech"><summary>Informations techniques</summary><dl>
      <div><dt>Identifiant</dt><dd><code class="mono">${esc(decision.id)}</code></dd></div>
      <div><dt>Lisible</dt><dd><code class="mono">${esc(decision.readable_id)}</code></dd></div>
      <div><dt>Projet</dt><dd>${decision.project_id ? `<code class="mono">${esc(decision.project_id)}</code>` : "—"}</dd></div>
      ${decision.task_id ? `<div><dt>Tâche</dt><dd><code class="mono">${esc(decision.task_id)}</code></dd></div>` : ""}
      <div><dt>Proposé par</dt><dd>${esc(decision.proposed_by_type)} <code class="mono">${esc(decision.proposed_by_id)}</code></dd></div>
      <div><dt>Créée le</dt><dd>${esc(time)}</dd></div>
    </dl></details>`;

  return `<li class="ds-list-item decision-item" data-id="${esc(decision.id)}">` +
    `<div class="grow">` +
    `<div class="decision-item-header">` +
    `<div class="decision-item-title-row">` +
    `<span class="decision-item-title">${esc(decision.title)}</span>` +
    `${dsBadge(statusLabel, statusTone)}` +
    `</div>` +
    `<div class="decision-item-meta">` +
    `<span>${decision.readable_id}</span>` +
    `<span class="meta-sep" aria-hidden="true">·</span>` +
    `<span>Projet: ${projectLink}</span>` +
    `<span class="meta-sep" aria-hidden="true">·</span>` +
    `<span>Tâche: ${taskLink}</span>` +
    `<span class="meta-sep" aria-hidden="true">·</span>` +
    `<span>Par: ${agentLink}</span>` +
    `<span class="meta-sep" aria-hidden="true">·</span>` +
    `<span>${esc(time)}</span>` +
    `</div>` +
    `</div>` +
    `<div class="decision-item-body">${esc(decision.body)}</div>` +
    `${techDetails}` +
    `</div>` +
    `</li>`;
}

export function decisionsHtml(
  decisions: Decision[],
  authed: boolean,
  projectId?: string,
  decisionsError?: string,
): string {
  const header = dsSectionHeader("Décisions", projectId ? { label: "Voir les décisions globales", href: "#/decisions" } : undefined);

  if (decisionsError !== undefined) {
    return `<section class="decisions-section" aria-labelledby="decisions-heading">${header}` +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Décisions indisponibles.</strong>${esc(decisionsError)}</div></section>`;
  }

  if (decisions.length === 0) {
    const createAction = authed
      ? `<p><button class="ds-btn ds-btn--primary" type="button" id="create-decision-btn">Créer une décision</button></p>`
      : "";
    return `<section class="decisions-section" aria-labelledby="decisions-heading">${header}` +
      dsEmptyState(
        "Aucune décision",
        projectId
          ? "Aucune décision liée à ce projet pour le moment."
          : "Aucune décision globale pour le moment.",
      ) +
      createAction +
      `</section>`;
  }

  const rows = decisions.map((d) => decisionHtml(d, authed)).join("");
  const createBtn = authed
    ? `<button class="ds-btn ds-btn--primary" type="button" id="create-decision-btn">Créer une décision</button>`
    : "";
  return `<section class="decisions-section" aria-labelledby="decisions-heading">${header}` +
    `<div class="decisions-toolbar">${createBtn}</div>` +
    `<ul class="ds-list decisions-list" role="list">${rows}</ul></section>`;
}

/** ------------------- MODALE CRÉATION DECISION ------------------- */

export function createDecisionFormHtml(
  authed: boolean,
  projectId: string | undefined,
  proposerId: string,
): string {
  const projectField =
    projectId !== undefined
      ? `<span class="meta">Projet: <code class="mono">${esc(projectId)}</code></span>`
      : dsField("decision-project_id", "Projet (optionnel)", `<input class="ds-input" id="FIELD" name="project_id" type="text" placeholder="uuid" />`, "Laissez vide pour une décision globale.");

  return `<form data-create-decision class="decision-form">` +
    `<input type="hidden" name="idempotency_key" value="${generateIdempotencyKey()}" />` +
    `${projectField}` +
    `${dsField("decision-task_id", "Tâche (optionnel)", `<input class="ds-input" id="FIELD" name="task_id" type="text" placeholder="uuid" />`, "Liez cette décision à une tâche si pertinent.")}` +
    `${dsField("decision-title", "Titre", `<input class="ds-input" id="FIELD" name="title" type="text" required />`, "Titre clair et concis de la décision.")}` +
    `${dsField("decision-body", "Contenu", `<textarea class="ds-input" id="FIELD" name="body" rows="4" required></textarea>`, "Décrivez la décision, son contexte et ses implications.")}` +
    `${dsField("decision-proposed_by_type", "Proposé par", `<select class="ds-input" id="FIELD" name="proposed_by_type"><option value="user">Utilisateur</option><option value="agent">Agent</option><option value="system">Système</option></select>`)}` +
    `${dsField("decision-proposed_by_id", "ID du proposant", `<input class="ds-input" id="FIELD" name="proposed_by_id" type="text" value="${esc(proposerId)}" required />`, "UUID de l'utilisateur, agent ou système.")}` +
    `<div class="decision-form-actions">` +
    `<button class="ds-btn ds-btn--primary" type="submit" ${authed ? "" : "disabled"}>Créer la décision</button>` +
    `<button class="ds-btn" type="button" data-ds-close>Annuler</button>` +
    `</div>` +
    `<div data-create-msg class="ds-list-sub" role="alert"></div>` +
    `</form>`;
}

/** ------------------- RENDU PRINCIPAL ------------------- */

export function decisionsTabsHtml(activeTab: "review" | "decisions"): string {
  return dsTabsHtml("decisions-main", [
    { id: "review", label: "À examiner", panel: '<div id="review-panel"></div>' },
    { id: "decisions", label: "Décisions", panel: '<div id="decisions-panel"></div>' },
  ], activeTab, "Décisions");
}

/**
 * Titre de page. Dans l'espace projet (`projectId`), la vue est un onglet du
 * workspace qui porte déjà le h1 : pas de second titre de page.
 */
function decisionsPageHeader(projectId: string | undefined): string {
  return projectId === undefined
    ? dsPageHeader("Décisions", "Ce qui attend un examen humain, et l'historique des décisions.")
    : "";
}

export async function renderDecisionsV2(root: HTMLElement, ctx: DecisionsContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML =
      decisionsPageHeader(ctx.projectId) +
      dsEmptyState("Connectez-vous", "Saisissez votre jeton machine pour charger la file d'examen et les décisions.");
    return;
  }

  const projectId = ctx.projectId;
  root.innerHTML = decisionsPageHeader(projectId) + dsSkeleton(4);

  const [reviewResult, decisionsResult] = await Promise.allSettled([
    fetchReviewQueue(ctx.client, projectId),
    fetchDecisions(ctx.client, projectId),
  ]);

  const reviewQueue = reviewResult.status === "fulfilled" ? reviewResult.value : null;
  const reviewError = reviewResult.status === "rejected" ? describeError(reviewResult.reason) : undefined;
  const decisions = decisionsResult.status === "fulfilled" ? decisionsResult.value : [];
  const decisionsError = decisionsResult.status === "rejected" ? describeError(decisionsResult.reason) : undefined;

  // Rendu initial avec onglets
  root.innerHTML =
    decisionsPageHeader(projectId) +
    decisionsTabsHtml("review") +
    `<div id="decision-modal-host"></div>`;

  initDsTabs(root, "decisions-main");

  const reviewPanel = root.querySelector<HTMLElement>("#review-panel");
  const decisionsPanel = root.querySelector<HTMLElement>("#decisions-panel");
  const decisionModalHost = root.querySelector<HTMLElement>("#decision-modal-host");

  // Rendu Review Queue
  if (reviewPanel !== null) {
    reviewPanel.innerHTML = reviewQueueHtml(reviewQueue, ctx.authed, projectId, reviewError);
    bindReviewActions(root, reviewPanel, ctx);
  }

  // Rendu Decisions
  if (decisionsPanel !== null) {
    const proposer = decodeJwtSubject(getToken()) ?? "";
    decisionsPanel.innerHTML = decisionsHtml(decisions, ctx.authed, projectId, decisionsError);
    bindDecisionActions(root, decisionsPanel, ctx, proposer);
  }

  // Créer la modale de création décision (cachée, injectée dans decisionModalHost)
  if (decisionModalHost !== null && ctx.authed) {
    const proposer = decodeJwtSubject(getToken()) ?? "";
    decisionModalHost.innerHTML = dsModalHtml({
      id: "create-decision-modal",
      title: "Créer une décision",
      body: createDecisionFormHtml(ctx.authed, projectId, proposer),
      actions: [],
    });
  }
}

function bindReviewActions(root: HTMLElement, panel: HTMLElement, ctx: DecisionsContext): void {
  const buttons = panel.querySelectorAll<HTMLButtonElement>("[data-review-approve], [data-review-changes]");
  buttons.forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.reviewApprove ?? button.dataset.reviewChanges ?? "";
      const resolution: ReviewResolution = button.dataset.reviewApprove !== undefined ? "approved" : "changes_requested";
      const label = resolution === "approved" ? "Approuver" : "Demander des modifications";

      // Désactiver tous les boutons pendant l'action
      buttons.forEach((b) => (b.disabled = true));
      button.textContent = `${label}…`;

      try {
        await resolveReview(ctx.client, id, resolution);
        dsNotify(`Travail IA ${resolution === "approved" ? "approuvé" : "refusé (modifications demandées)"}.`, "success");
        // Re-rendre la section review
        const reviewQueue = await fetchReviewQueue(ctx.client, ctx.projectId);
        const newPanel = root.querySelector<HTMLElement>("#review-panel");
        if (newPanel !== null) {
          newPanel.innerHTML = reviewQueueHtml(reviewQueue, ctx.authed, ctx.projectId);
          bindReviewActions(root, newPanel, ctx);
        }
      } catch (error) {
        dsNotify(describeError(error), "danger");
        button.textContent = label;
        buttons.forEach((b) => (b.disabled = false));
      }
    });
  });
}

function bindDecisionActions(
  root: HTMLElement,
  panel: HTMLElement,
  ctx: DecisionsContext,
  proposerId: string,
): void {
  // Bouton "Créer une décision" → ouvre la modale
  const createBtn = panel.querySelector<HTMLButtonElement>("#create-decision-btn");
  createBtn?.addEventListener("click", () => {
    openDsDialog(root, "create-decision-modal", createBtn);
  });

  // Soumission du formulaire dans la modale
  const modalHost = root.querySelector<HTMLElement>("#decision-modal-host");
  const form = modalHost?.querySelector<HTMLFormElement>("[data-create-decision]");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const msg = form.querySelector("[data-create-msg]");
    const submitBtn = form.querySelector<HTMLButtonElement>('button[type="submit"]');
    const idempotencyKey = data.get("idempotency_key") as string;

    const proposedById = String(data.get("proposed_by_id") ?? "").trim();
    if (!isUuid(proposedById)) {
      if (msg !== null) {
        msg.textContent = "L'ID du proposant doit être un UUID valide.";
        if (msg instanceof HTMLElement) focusDsErrorBox(msg);
      }
      return;
    }

    if (submitBtn !== null) submitBtn.disabled = true;

    const project = ctx.projectId ?? String(data.get("project_id") ?? "").trim();
    const taskId = String(data.get("task_id") ?? "").trim();
    const title = String(data.get("title") ?? "").trim();
    const body = String(data.get("body") ?? "").trim();
    const proposedByType = String(data.get("proposed_by_type") ?? "user");

    try {
      await createDecision(ctx.client, {
        project_id: project === "" ? null : project,
        task_id: taskId === "" ? null : taskId,
        title,
        body,
        proposed_by_type: proposedByType,
        proposed_by_id: proposedById,
      }, idempotencyKey);

      dsNotify("Décision créée.", "success");
      closeDsDialog(root, "create-decision-modal");

      // Recharger les décisions
      const decisions = await fetchDecisions(ctx.client, ctx.projectId);
      const newPanel = root.querySelector<HTMLElement>("#decisions-panel");
      if (newPanel !== null) {
        newPanel.innerHTML = decisionsHtml(decisions, ctx.authed, ctx.projectId);
        bindDecisionActions(root, newPanel, ctx, proposerId);
        // Le panneau est repeint : refocaliser l'action de création.
        newPanel.querySelector<HTMLElement>("#create-decision-btn")?.focus();
      }
    } catch (error) {
      // Nouvelle tentative indépendante après un échec définitif : clé neuve,
      // jamais réutilisée pour un corps potentiellement modifié.
      const keyInput = form.querySelector<HTMLInputElement>('input[name="idempotency_key"]');
      if (keyInput !== null) keyInput.value = generateIdempotencyKey();
      if (msg !== null) {
        msg.textContent = describeError(error);
        if (msg instanceof HTMLElement) focusDsErrorBox(msg);
      }
      if (submitBtn !== null) submitBtn.disabled = false;
    }
  });
}