/**
 * UI-10 — Transferts : surface Infrastructure d'échange de fichiers.
 *
 * Un TRANSFERT est l'échange d'un fichier identifié entre un expéditeur et,
 * éventuellement, un destinataire (ou une diffusion), rattaché ou non à un
 * projet. Ce n'est PAS un objet de stockage : le bucket, la clé S3 et les URL
 * présignées restent des détails techniques repliés, jamais des concepts
 * proposés à l'utilisateur.
 *
 * Sources réelles (audit UI-10) :
 * - GET  /api/v1/transfers                    (liste filtrée par visibilité)
 * - GET  /api/v1/transfers/consumption        (quota advisory, avant envoi)
 * - POST /api/v1/transfers                    (déclaration + Idempotency-Key)
 * - POST /api/v1/transfers/{id}/upload/initiate|complete  (envoi direct)
 * - POST /api/v1/transfers/{id}/download-url  (URL signée courte, jamais les octets)
 * - GET  /api/v1/projects, /api/v1/tasks       (contexte lisible, secondaire)
 *
 * Actions volontairement ABSENTES (aucun endpoint / autorisation fiable) :
 * annuler, supprimer, réessayer, renvoyer, partager, prolonger, révoquer.
 * `DELETE /transfers/{id}` existe mais est réservé à l'expéditeur/admin — le
 * tableau de bord ne connaît ni l'utilisateur courant ni son rôle : aucun
 * bouton destructif n'est exposé (voir le tiroir, section technique).
 *
 * Statut backend réel : created, uploading, ready, downloaded, expired,
 * deleted. L'expiration encore visible est DÉRIVÉE de `expires_at` (le
 * service marque `deleted`, jamais `expired`) et signalée comme telle.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import {
  createTransfer,
  downloadUrl,
  getConsumption,
  listTransfers,
  uploadTransfer,
  type Transfer,
  type TransferCategory,
  type TransferConsumption,
  type UploadProgress,
} from "../transfersApi";
import {
  effectiveStatus,
  expiryLabelFr,
  humanBytes,
  initialTransfersFilterState,
  isDownloadable,
  isTransfersDefaultState,
  isUuid,
  recipientLabelFr,
  senderLabelFr,
  transferCategoryFr,
  transferErrorMessage,
  transferProjectIds,
  visibleTransfers,
  type StatusLabel,
  type TransfersFilterContext,
  type TransfersFilterState,
  type TransferStatusFilter,
} from "../transfersFormat";
import { listTasks, type Task } from "../tasksApi";
import {
  dsBadge,
  dsDrawerHtml,
  dsField,
  dsModalHtml,
  dsNotify,
  dsPageHeader,
  dsProgress,
  dsSkeleton,
  dsStatus,
  closeDsDialog,
  focusDsErrorBox,
  openDsDialog,
  type DsStatusState,
} from "../ds/ds";
import { describeError, esc, fmtTime, shortId } from "../ui";
import type { components } from "../openapi-schema";
import "./transfers.css";

type Project = components["schemas"]["Project"];

export interface TransfersContext {
  client: StudioClient;
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

async function fetchProjects(client: StudioClient): Promise<Project[]> {
  const result = await client.GET("/api/v1/projects");
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

const TONE_STATE: Record<StatusLabel["tone"], DsStatusState> = {
  neutral: "idle",
  info: "info",
  success: "success",
  warning: "warning",
  danger: "danger",
};

export interface TransferInfo {
  projectName: string | null;
  taskTitle: string | null;
}

export function transferInfo(transfer: Transfer, ctx: TransfersFilterContext): TransferInfo {
  return {
    projectName:
      transfer.project_id !== null && transfer.project_id !== undefined
        ? (ctx.projectNameById?.get(transfer.project_id) ?? null)
        : null,
    taskTitle:
      transfer.task_id !== null && transfer.task_id !== undefined
        ? (ctx.taskTitleById?.get(transfer.task_id) ?? null)
        : null,
  };
}

export function transfersLoadingHtml(): string {
  return (
    `<div class="transfers">` +
    `${dsPageHeader("Transferts", "Échange de fichiers via Studi'OS.")}` +
    `${dsSkeleton(4)}</div>`
  );
}

/* ------------------------------------------------------------------ */
/* Représentation d'un transfert.                                      */
/* ------------------------------------------------------------------ */

/** État : pastille + libellé explicite ; « déduit » quand c'est une expiration. */
export function transferStatusHtml(transfer: Transfer, now: number): string {
  const status = effectiveStatus(transfer, now);
  const derived = status.derivedExpiry ? dsBadge("déduit", "neutral") : "";
  return (
    `<span class="transfer-status" title="${esc(status.hint)}">` +
    `${dsStatus(TONE_STATE[status.tone], status.label)}${derived}</span>`
  );
}

function projectLineHtml(transfer: Transfer, info: TransferInfo): string {
  if (transfer.project_id === null || transfer.project_id === undefined) return "";
  if (info.projectName !== null) {
    return ` · <a href="#/projects/${esc(transfer.project_id)}">${esc(info.projectName)}</a>`;
  }
  return ` · <span title="${esc(transfer.project_id)}">projet non résolu (${esc(shortId(transfer.project_id))})</span>`;
}

function taskLineHtml(transfer: Transfer, info: TransferInfo): string {
  if (transfer.task_id === null || transfer.task_id === undefined) return "";
  const label = info.taskTitle !== null ? info.taskTitle : `Tâche ${shortId(transfer.task_id)}`;
  return ` · <a href="#/tasks/${esc(transfer.task_id)}">${esc(label)}</a>`;
}

export function transferCardHtml(transfer: Transfer, info: TransferInfo, now: number): string {
  const downloadable = isDownloadable(transfer, now);
  const uploaded =
    transfer.uploaded_at !== null && transfer.uploaded_at !== undefined
      ? ` · envoyé le ${fmtTime(transfer.uploaded_at)}`
      : "";
  const download = downloadable
    ? `<button class="ds-btn ds-btn--primary ds-btn--sm" type="button" data-transfer-download="${esc(transfer.id)}">Télécharger</button>`
    : "";
  return (
    `<li class="ds-list-item transfer-row"><div class="grow">` +
    `<h3 class="ds-list-title">${esc(transfer.filename)}</h3>` +
    `<div class="ds-list-sub">${esc(transfer.transfer_code)} · ${esc(transferCategoryFr(transfer.category))} · ${esc(humanBytes(transfer.size_bytes))}${projectLineHtml(transfer, info)}${taskLineHtml(transfer, info)}</div>` +
    `<div class="ds-list-sub">Expéditeur : ${esc(senderLabelFr(transfer))} · Destinataire : ${esc(recipientLabelFr(transfer))}</div>` +
    `<div class="ds-list-sub">Créé le ${fmtTime(transfer.created_at)}${uploaded}</div>` +
    `</div><div class="transfer-side">${transferStatusHtml(transfer, now)}` +
    `<div class="transfer-actions">${download}` +
    `<button class="ds-btn ds-btn--sm" type="button" data-transfer-details="${esc(transfer.id)}">Détails</button>` +
    `</div></div></li>`
  );
}

export function transfersListHtml(
  transfers: Transfer[],
  ctx: TransfersFilterContext,
): string {
  return (
    `<ul class="ds-list transfers-list">` +
    transfers.map((transfer) => transferCardHtml(transfer, transferInfo(transfer, ctx), ctx.now)).join("") +
    `</ul>`
  );
}

/* ------------------------------------------------------------------ */
/* Tiroir de détail (liste déjà complète : aucun endpoint de détail).  */
/* ------------------------------------------------------------------ */

function fact(label: string, value: string): string {
  return `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
}

export function transferDrawerBodyHtml(
  transfer: Transfer,
  ctx: TransfersFilterContext,
): string {
  const status = effectiveStatus(transfer, ctx.now);
  const info = transferInfo(transfer, ctx);
  const downloadable = isDownloadable(transfer, ctx.now);
  const project =
    transfer.project_id === null || transfer.project_id === undefined
      ? "Aucun"
      : info.projectName !== null
        ? `<a href="#/projects/${esc(transfer.project_id)}">${esc(info.projectName)}</a>`
        : `<code class="mono" title="${esc(transfer.project_id)}">${esc(shortId(transfer.project_id))}</code> (nom non résolu)`;
  const task =
    transfer.task_id === null || transfer.task_id === undefined
      ? "Aucune"
      : info.taskTitle !== null
        ? `<a href="#/tasks/${esc(transfer.task_id)}">${esc(info.taskTitle)}</a>`
        : `<a href="#/tasks/${esc(transfer.task_id)}">Tâche ${esc(shortId(transfer.task_id))}</a>`;

  const download = downloadable
    ? `<button class="ds-btn ds-btn--primary ds-btn--sm" type="button" data-transfer-download="${esc(transfer.id)}">Télécharger</button>`
    : `<p class="ds-list-sub">Téléchargement indisponible pour cet état.</p>`;

  const facts =
    `<dl class="transfer-facts">` +
    fact("Code", `<code class="mono">${esc(transfer.transfer_code)}</code>`) +
    fact("Catégorie", esc(transferCategoryFr(transfer.category))) +
    fact("Taille", esc(humanBytes(transfer.size_bytes))) +
    fact("Expéditeur", esc(senderLabelFr(transfer))) +
    fact("Destinataire", esc(recipientLabelFr(transfer))) +
    fact("Projet", project) +
    fact("Tâche", task) +
    fact("Créé le", fmtTime(transfer.created_at)) +
    fact("Envoyé le", fmtTime(transfer.uploaded_at)) +
    fact("Téléchargé le", fmtTime(transfer.downloaded_at)) +
    fact("Expiration", esc(expiryLabelFr(transfer.expires_at, ctx.now))) +
    `</dl>`;

  const technical =
    `<details class="transfer-technical"><summary>Informations techniques</summary>` +
    `<dl class="transfer-facts">` +
    fact("Identifiant", `<code class="mono">${esc(transfer.id)}</code>`) +
    fact("Statut technique", `<code class="mono">${esc(transfer.status)}</code>${status.derivedExpiry ? " (expiration déduite)" : ""}`) +
    fact("Référence de stockage", `<code class="mono">${esc(transfer.object_key)}</code>`) +
    fact("Type MIME", esc(transfer.content_type)) +
    fact("SHA-256", transfer.sha256 === null || transfer.sha256 === undefined ? "Non renseigné" : `<code class="mono">${esc(transfer.sha256)}</code> (déclaré par le client)`) +
    fact("Content-MD5", transfer.content_md5 === null || transfer.content_md5 === undefined ? "Non renseigné" : `<code class="mono">${esc(transfer.content_md5)}</code> (vérifié par le stockage, voie mono-partie)`) +
    fact("Build", transfer.build_id === null || transfer.build_id === undefined ? "Aucun" : `<code class="mono">${esc(transfer.build_id)}</code>`) +
    fact("Supprimé le", fmtTime(transfer.deleted_at)) +
    `</dl><p class="ds-list-sub">Suppression, annulation, prolongation et renvoi ne sont pas proposés : réservés au serveur, à l'expéditeur ou hors interface.</p></details>`;

  return (
    `<h3 class="transfer-drawer-title">${esc(transfer.filename)}</h3>` +
    `<div class="transfer-drawer-summary">${transferStatusHtml(transfer, ctx.now)}` +
    `<p class="ds-list-sub">${esc(status.hint)}</p>${download}</div>` +
    facts +
    technical
  );
}

/* ------------------------------------------------------------------ */
/* Recherche, filtres, liste vide.                                     */
/* ------------------------------------------------------------------ */

const STATUS_OPTIONS: { value: TransferStatusFilter; label: string }[] = [
  { value: "all", label: "Tous les états" },
  { value: "created", label: "En attente d'envoi" },
  { value: "uploading", label: "Envoi en cours" },
  { value: "ready", label: "Disponible" },
  { value: "downloaded", label: "Téléchargé" },
  { value: "expired", label: "Expiré" },
  { value: "deleted", label: "Supprimé" },
];

const CATEGORY_OPTIONS: { value: "all" | TransferCategory; label: string }[] = [
  { value: "all", label: "Toutes les catégories" },
  { value: "temporary", label: "Temporaire" },
  { value: "build", label: "Build" },
  { value: "asset", label: "Ressource" },
  { value: "raw_recording", label: "Enregistrement brut" },
];

function projectOptionsHtml(transfers: Transfer[], state: TransfersFilterState, ctx: TransfersFilterContext): string {
  const options = transferProjectIds(transfers)
    .map((id) => {
      const name = ctx.projectNameById?.get(id) ?? `Projet ${shortId(id)}`;
      return `<option value="${esc(id)}"${state.projectId === id ? " selected" : ""}>${esc(name)}</option>`;
    })
    .join("");
  return (
    `<option value=""${state.projectId === "" ? " selected" : ""}>Tous les projets</option>` +
    options
  );
}

export function transfersToolbarHtml(
  transfers: Transfer[],
  state: TransfersFilterState,
  shown: number,
  ctx: TransfersFilterContext,
): string {
  const statusOptions = STATUS_OPTIONS.map(
    (option) => `<option value="${option.value}"${state.status === option.value ? " selected" : ""}>${esc(option.label)}</option>`,
  ).join("");
  const categoryOptions = CATEGORY_OPTIONS.map(
    (option) => `<option value="${option.value}"${state.category === option.value ? " selected" : ""}>${esc(option.label)}</option>`,
  ).join("");
  return (
    `<div class="transfers-toolbar" role="search" aria-label="Rechercher et filtrer les transferts chargés">` +
    `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span>` +
    `<label class="ds-sr-only" for="transfers-search">Rechercher parmi les transferts chargés</label>` +
    `<input class="ds-input" type="search" id="transfers-search" value="${esc(state.query)}" placeholder="Rechercher un fichier, un code, un projet…" autocomplete="off" /></div>` +
    `<label class="transfers-filter"><span>État</span><select class="ds-select" id="transfers-status">${statusOptions}</select></label>` +
    `<label class="transfers-filter"><span>Catégorie</span><select class="ds-select" id="transfers-category">${categoryOptions}</select></label>` +
    `<label class="transfers-filter"><span>Projet</span><select class="ds-select" id="transfers-project">${projectOptionsHtml(transfers, state, ctx)}</select></label>` +
    `<button class="ds-btn ds-btn--ghost" type="button" data-reset${isTransfersDefaultState(state) ? " disabled" : ""}>Réinitialiser</button>` +
    `<p class="ds-list-sub" role="status" aria-live="polite">${shown} transfert(s) affiché(s) sur ${transfers.length} chargé(s) — recherche et filtres locaux.</p>` +
    `</div>`
  );
}

export function transfersEmptyHtml(): string {
  return (
    `<div class="ds-empty" role="status"><span class="ds-empty-icon" aria-hidden="true">○</span>` +
    `<h3>Aucun transfert</h3>` +
    `<p>Les transferts permettent d'échanger des fichiers via Studi'OS. Aucun transfert n'est visible pour ce jeton pour le moment.</p>` +
    `<button class="ds-btn ds-btn--primary" type="button" data-transfer-upload-open>Envoyer un fichier</button></div>`
  );
}

export function transfersNoMatchHtml(): string {
  return (
    `<div class="ds-empty" role="status"><span class="ds-empty-icon" aria-hidden="true">○</span>` +
    `<h3>Aucun transfert ne correspond</h3>` +
    `<p>Modifiez la recherche ou les filtres pour retrouver vos transferts déjà chargés.</p></div>`
  );
}

/* ------------------------------------------------------------------ */
/* Envoi : modale DS, envoi direct au stockage, quota advisory.        */
/* ------------------------------------------------------------------ */

function projectSelectHtml(projects: Project[], consumptionNote: string): string {
  if (projects.length === 0) {
    return (
      `<p class="ds-list-sub">Aucun projet accessible n'a pu être chargé : le transfert sera déposé dans le bucket partagé.</p>` +
      consumptionNote
    );
  }
  const options =
    `<option value="">Aucun projet (bucket partagé)</option>` +
    projects
      .map((project) => `<option value="${esc(project.id)}">${esc(project.name)}</option>`)
      .join("");
  return (
    dsField("transfer-project", "Projet (optionnel)", `<select class="ds-select" id="FIELD" name="project_id">${options}</select>`, "Lier le transfert à un projet ; le quota du projet s'applique alors.") +
    consumptionNote
  );
}

export function uploadModalBodyHtml(projects: Project[], consumption: TransferConsumption | null): string {
  const quota =
    consumption === null
      ? `<p class="ds-list-sub" data-quota>Quota indisponible pour le moment.</p>`
      : `<p class="ds-list-sub" data-quota>Quota : ${esc(humanBytes(consumption.consumed_bytes))} utilisés sur ${esc(humanBytes(consumption.quota_bytes))} (${esc(humanBytes(consumption.remaining_bytes))} restants).</p>`;
  const categoryOptions = CATEGORY_OPTIONS.filter((option) => option.value !== "all")
    .map((option) => `<option value="${option.value}">${esc(option.label)}</option>`)
    .join("");
  return (
    `<form data-upload class="transfer-upload-form">` +
    dsField("transfer-file", "Fichier", `<input class="ds-input" type="file" id="FIELD" name="file" required />`, "Les octets vont directement au stockage via des URL signées, jamais via l'API.") +
    `<p class="ds-list-sub" data-file-info role="status" aria-live="polite"></p>` +
    projectSelectHtml(projects, quota) +
    dsField("transfer-recipient", "Destinataire (identifiant utilisateur, optionnel)", `<input class="ds-input" type="text" id="FIELD" name="recipient_user_id" placeholder="uuid" autocomplete="off" />`, "Laissez vide pour diffuser aux destinataires autorisés. Aucun annuaire utilisateur n'est consultable ici.") +
    dsField("transfer-category", "Catégorie", `<select class="ds-select" id="FIELD" name="category">${categoryOptions}</select>`, "Temporaire : 7 jours. Build : 30 jours. Ressource et enregistrement brut : conservation manuelle.") +
    `<button class="ds-btn ds-btn--primary" type="submit">Envoyer le fichier</button>` +
    `<div data-upload-progress class="transfer-upload-progress" role="status" aria-live="polite"></div>` +
    `<p data-upload-error class="ds-field-error" role="alert"></p>` +
    `</form>`
  );
}

export function uploadProgressHtml(progress: UploadProgress): string {
  if (progress.phase === "hashing") {
    return `<p class="ds-list-sub">Calcul de l'empreinte du fichier…</p>`;
  }
  const total = progress.totalBytes === 0 ? 1 : progress.totalBytes;
  const percent = Math.round((progress.uploadedBytes / total) * 100);
  const label =
    progress.phase === "uploading"
      ? `Envoi… ${percent} %`
      : progress.phase === "completing"
        ? "Finalisation…"
        : "Envoyé.";
  return dsProgress(progress.uploadedBytes, total, label);
}

/* ------------------------------------------------------------------ */
/* Page complète.                                                      */
/* ------------------------------------------------------------------ */

export interface TransfersPageData {
  transfers: Transfer[];
  state: TransfersFilterState;
  ctx: TransfersFilterContext;
  projects: Project[];
  consumption: TransferConsumption | null;
  problems: string[];
}

export function transfersPageHtml(data: TransfersPageData): string {
  const header = dsPageHeader(
    "Transferts",
    "Échange de fichiers via Studi'OS — chaque transfert relie un fichier à un expéditeur et, éventuellement, à un destinataire ou un projet.",
    [{ label: "Envoyer un fichier", id: "transfer-upload-open", variant: "primary" }],
  );
  const degraded =
    data.problems.length === 0
      ? ""
      : `<div class="transfers-notice transfers-notice--warning" role="status">Données partielles : ${esc(data.problems.join(" · "))} — la liste reste consultable.</div>`;
  const visible = visibleTransfers(data.transfers, data.state, data.ctx);
  const toolbar =
    data.transfers.length === 0 ? "" : transfersToolbarHtml(data.transfers, data.state, visible.length, data.ctx);
  const body =
    data.transfers.length === 0
      ? transfersEmptyHtml()
      : visible.length === 0
        ? transfersNoMatchHtml()
        : transfersListHtml(visible, data.ctx);
  const drawer = dsDrawerHtml({
    id: "transfer-drawer",
    title: "Détail du transfert",
    body: `<div id="transfer-drawer-body"></div>`,
    actions: [{ label: "Fermer", variant: "primary" }],
  });
  const modal = dsModalHtml({
    id: "transfer-upload",
    title: "Envoyer un fichier",
    body: uploadModalBodyHtml(data.projects, data.consumption),
    actions: [{ label: "Annuler" }],
  });
  return (
    `<div class="transfers">${header}${degraded}${toolbar}` +
    `<div id="transfers-list">${body}</div>` +
    `${drawer}${modal}</div>`
  );
}

/* ------------------------------------------------------------------ */
/* Rendu + liaison DOM (aucun handler inline, contrainte CSP).         */
/* ------------------------------------------------------------------ */

export async function renderTransfers(root: HTMLElement, ctx: TransfersContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML =
      `<div class="transfers">${dsPageHeader("Transferts", "Échange de fichiers via Studi'OS.")}` +
      `<div class="ds-empty" role="status"><span class="ds-empty-icon" aria-hidden="true">○</span>` +
      `<h3>Connexion requise</h3><p>Définissez un jeton pour voir les transferts visibles pour ce jeton.</p></div></div>`;
    return;
  }
  root.innerHTML = transfersLoadingHtml();

  const [transfersResult, projectsResult, tasksResult, consumptionResult] = await Promise.all([
    settle(listTransfers(ctx.client)),
    settle(fetchProjects(ctx.client)),
    settle(listTasks(ctx.client, { limit: 100 })),
    settle(getConsumption(ctx.client)),
  ]);

  if (!transfersResult.ok) {
    root.innerHTML =
      `<div class="transfers">${dsPageHeader("Transferts", "Échange de fichiers via Studi'OS.", [{ label: "Actualiser", id: "transfers-reload" }])}` +
      `<div class="state error" role="alert">Impossible de charger les transferts : ${esc(describeError(transfersResult.error))}</div></div>`;
    root.querySelector("#transfers-reload")?.addEventListener("click", () => {
      void renderTransfers(root, ctx);
    });
    return;
  }

  const projects = projectsResult.ok ? projectsResult.value : [];
  const tasks: Task[] = tasksResult.ok ? tasksResult.value : [];
  const problems: string[] = [];
  if (!projectsResult.ok) problems.push(`projets indisponibles (${describeError(projectsResult.error)})`);
  if (!tasksResult.ok) problems.push(`tâches indisponibles (${describeError(tasksResult.error)})`);
  if (!consumptionResult.ok) problems.push(`quota indisponible (${describeError(consumptionResult.error)})`);

  const now = Date.now();
  const ctxFilter: TransfersFilterContext = {
    now,
    projectNameById: new Map(projects.map((project) => [project.id, project.name])),
    taskTitleById: new Map(tasks.map((task) => [task.id, task.title])),
  };
  const data: TransfersPageData = {
    transfers: transfersResult.value,
    state: initialTransfersFilterState(),
    ctx: ctxFilter,
    projects,
    consumption: consumptionResult.ok ? consumptionResult.value : null,
    problems,
  };
  root.innerHTML = transfersPageHtml(data);
  bindTransfers(root, ctx, data);
}

function refreshList(root: HTMLElement, ctx: TransfersContext, data: TransfersPageData): void {
  const visible = visibleTransfers(data.transfers, data.state, data.ctx);
  const list = root.querySelector("#transfers-list");
  if (list !== null) {
    list.innerHTML =
      data.transfers.length === 0
        ? transfersEmptyHtml()
        : visible.length === 0
          ? transfersNoMatchHtml()
          : transfersListHtml(visible, data.ctx);
  }
  const toolbar = root.querySelector(".transfers-toolbar");
  if (toolbar !== null) {
    const fresh = document.createElement("div");
    fresh.innerHTML = transfersToolbarHtml(data.transfers, data.state, visible.length, data.ctx);
    toolbar.replaceWith(...fresh.childNodes);
  }
  bindToolbar(root, ctx, data);
  bindListButtons(root, ctx, data);
}

function setUploadError(root: HTMLElement, message: string): void {
  const node = root.querySelector("[data-upload-error]");
  if (node === null) return;
  node.textContent = message;
  if (message !== "" && node instanceof HTMLElement) focusDsErrorBox(node);
}

function bindToolbar(root: HTMLElement, ctx: TransfersContext, data: TransfersPageData): void {
  const search = root.querySelector<HTMLInputElement>("#transfers-search");
  search?.addEventListener("input", () => {
    data.state.query = search.value;
    refreshList(root, ctx, data);
    const again = root.querySelector<HTMLInputElement>("#transfers-search");
    if (again !== null) {
      again.focus();
      again.setSelectionRange(again.value.length, again.value.length);
    }
  });
  const status = root.querySelector<HTMLSelectElement>("#transfers-status");
  status?.addEventListener("change", () => {
    data.state.status = status.value as TransferStatusFilter;
    refreshList(root, ctx, data);
  });
  const category = root.querySelector<HTMLSelectElement>("#transfers-category");
  category?.addEventListener("change", () => {
    data.state.category = category.value as TransfersFilterState["category"];
    refreshList(root, ctx, data);
  });
  const project = root.querySelector<HTMLSelectElement>("#transfers-project");
  project?.addEventListener("change", () => {
    data.state.projectId = project.value;
    refreshList(root, ctx, data);
  });
  root.querySelector("[data-reset]")?.addEventListener("click", () => {
    data.state = initialTransfersFilterState();
    refreshList(root, ctx, data);
  });
}

function bindDownloadButtons(scope: ParentNode, root: HTMLElement, ctx: TransfersContext): void {
  scope.querySelectorAll<HTMLButtonElement>("[data-transfer-download]").forEach((button) => {
    button.addEventListener("click", () => {
      button.disabled = true;
      const id = button.getAttribute("data-transfer-download") ?? "";
      downloadUrl(ctx.client, id)
        .then(({ download_url }) => {
          window.open(download_url, "_blank", "noopener");
        })
        .catch((error: unknown) => {
          setUploadError(root, transferErrorMessage(error));
        })
        .finally(() => {
          button.disabled = false;
        });
    });
  });
}

function bindListButtons(root: HTMLElement, ctx: TransfersContext, data: TransfersPageData): void {
  root.querySelectorAll<HTMLButtonElement>("[data-transfer-details]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.getAttribute("data-transfer-details") ?? "";
      const transfer = data.transfers.find((candidate) => candidate.id === id);
      if (transfer === undefined) return;
      const body = root.querySelector("#transfer-drawer-body");
      if (body === null) return;
      body.innerHTML = transferDrawerBodyHtml(transfer, data.ctx);
      bindDownloadButtons(body, root, ctx);
      openDsDialog(root, "transfer-drawer", button);
    });
  });
}

function bindUploadOpen(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>("[data-transfer-upload-open], #transfer-upload-open").forEach((button) => {
    button.addEventListener("click", () => openDsDialog(root, "transfer-upload", button));
  });
}

function bindUploadForm(root: HTMLElement, ctx: TransfersContext): void {
  const form = root.querySelector<HTMLFormElement>("[data-upload]");
  if (form === null) return;
  const fileInfo = form.querySelector<HTMLElement>("[data-file-info]");
  const fileInput = form.querySelector<HTMLInputElement>('input[type="file"]');
  const projectSelect = form.querySelector<HTMLSelectElement>('select[name="project_id"]');
  const quotaLine = form.querySelector<HTMLElement>("[data-quota]");

  fileInput?.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (fileInfo === null) return;
    fileInfo.textContent =
      file === undefined
        ? ""
        : file.size === 0
          ? `${file.name} — fichier vide, rien à envoyer.`
          : `${file.name} — ${humanBytes(file.size)}.`;
  });

  projectSelect?.addEventListener("change", () => {
    const projectId = projectSelect.value === "" ? undefined : projectSelect.value;
    if (quotaLine !== null) quotaLine.textContent = "Quota : chargement…";
    void getConsumption(ctx.client, projectId)
      .then((consumption) => {
        if (quotaLine === null) return;
        quotaLine.textContent = `Quota : ${humanBytes(consumption.consumed_bytes)} utilisés sur ${humanBytes(consumption.quota_bytes)} (${humanBytes(consumption.remaining_bytes)} restants).`;
      })
      .catch(() => {
        if (quotaLine !== null) quotaLine.textContent = "Quota indisponible pour ce bucket.";
      });
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    setUploadError(root, "");
    const submit = form.querySelector<HTMLButtonElement>('button[type="submit"]');
    const progress = form.querySelector<HTMLElement>("[data-upload-progress]");
    const file = fileInput?.files?.[0];
    if (file === undefined || file.size === 0) {
      setUploadError(root, "Choisissez un fichier non vide.");
      return;
    }
    const recipient = String(form.querySelector<HTMLInputElement>('input[name="recipient_user_id"]')?.value ?? "").trim();
    if (recipient !== "" && !isUuid(recipient)) {
      setUploadError(root, "L'identifiant du destinataire doit être un UUID valide.");
      return;
    }
    const projectId = projectSelect?.value ?? "";
    const category = (String(form.querySelector<HTMLSelectElement>('select[name="category"]')?.value ?? "temporary") || "temporary") as TransferCategory;

    if (submit !== null) submit.disabled = true;
    if (progress !== null) {
      progress.innerHTML = uploadProgressHtml({ phase: "hashing", uploadedBytes: 0, totalBytes: file.size });
    }

    void (async () => {
      try {
        const transfer = await createTransfer(ctx.client, {
          project_id: projectId === "" ? null : projectId,
          task_id: null,
          recipient_user_id: recipient === "" ? null : recipient,
          category,
          filename: file.name,
          content_type: file.type === "" ? "application/octet-stream" : file.type,
          size_bytes: file.size,
        });
        const done = await uploadTransfer(ctx.client, transfer, file, (state) => {
          if (progress !== null) progress.innerHTML = uploadProgressHtml(state);
        });
        closeDsDialog(root, "transfer-upload");
        dsNotify(`Transfert ${done.transfer_code} envoyé.`, "success");
        await renderTransfers(root, ctx);
        // La liste est repeinte : refocaliser l'envoi, jamais <body>.
        root.querySelector<HTMLElement>("[data-transfer-upload-open], #transfer-upload-open")?.focus();
      } catch (error) {
        setUploadError(root, transferErrorMessage(error));
        if (progress !== null) progress.innerHTML = "";
        if (submit !== null) submit.disabled = false;
      }
    })();
  });
}

function bindTransfers(root: HTMLElement, ctx: TransfersContext, data: TransfersPageData): void {
  root.querySelector("#transfers-reload")?.addEventListener("click", () => {
    void renderTransfers(root, ctx);
  });
  bindToolbar(root, ctx, data);
  bindListButtons(root, ctx, data);
  bindDownloadButtons(root, root, ctx);
  bindUploadOpen(root);
  bindUploadForm(root, ctx);
}
