/**
 * P5 — Workspace Manager : liste, détail et parcours de liaison des dossiers
 * locaux. DOM-free : chaînes pures, comme les autres vues.
 *
 * Ce module ne parle jamais à Tauri : il reçoit des données déjà validées par
 * `platform` (commandes `workspace.*` du pont P1) et rend du HTML.
 * Le montage dans la navigation globale est fait par `views/workspacesPage.ts` ;
 * ce module expose seulement une entrée à monter.
 */

import { esc } from "../ui";

export const P5_WORKSPACE_ROUTE = "#/workspaces";

export interface WorkspaceNavEntry {
  hash: string;
  label: string;
}

export function workspaceNavEntry(): WorkspaceNavEntry {
  return { hash: P5_WORKSPACE_ROUTE, label: "Dossiers" };
}

export type WorkspaceHealthView =
  | "valid"
  | "config_missing"
  | "config_invalid"
  | "moved"
  | "inaccessible"
  | "project_unavailable";

export type WorkspaceActionView =
  | "none"
  | "create_config"
  | "repair_config"
  | "confirm_relocation"
  | "grant_access"
  | "detach_workspace";

export interface WorkspaceViewModel {
  workspaceId: string;
  projectName: string;
  folderName: string;
  health: WorkspaceHealthView;
  action: WorkspaceActionView;
  candidateFolder: string | null;
  repoCount: number | null;
  features: ReadonlyArray<{ name: string; on: boolean }>;
  watchSummary: string | null;
}

export const WORKSPACE_HEALTHS: ReadonlyArray<WorkspaceHealthView> = [
  "valid",
  "config_missing",
  "config_invalid",
  "moved",
  "inaccessible",
  "project_unavailable",
];

export const WORKSPACE_ACTIONS: ReadonlyArray<WorkspaceActionView> = [
  "none",
  "create_config",
  "repair_config",
  "confirm_relocation",
  "grant_access",
  "detach_workspace",
];

const FEATURE_LABELS: ReadonlyArray<readonly [string, string]> = [
  ["knowledge", "Connaissances"],
  ["code_graph", "Graphe de code"],
  ["harness", "Assistants"],
  ["watchers", "Surveillance"],
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isHealth(value: unknown): value is WorkspaceHealthView {
  return typeof value === "string" && (WORKSPACE_HEALTHS as ReadonlyArray<string>).includes(value);
}

function isAction(value: unknown): value is WorkspaceActionView {
  return typeof value === "string" && (WORKSPACE_ACTIONS as ReadonlyArray<string>).includes(value);
}

function lastSegment(path: string): string {
  const parts = path.split(/[\\/]+/).filter((part) => part !== "");
  return parts.length === 0 ? path : (parts[parts.length - 1] as string);
}

/**
 * ViewModel dérivé du `WorkspaceStatus` canonique du contrat P1 (snake_case,
 * `contracts/local`). Ce n'est pas un second format de fil : seule la forme
 * canonique est acceptée. Fail-closed : une réponse inattendue donne `null`,
 * jamais un rendu partiel ; les champs inconnus (dont la configuration
 * complète, les références de secrets et les chemins) ne sont jamais recopiés.
 */
export function toWorkspaceViewModel(payload: unknown): WorkspaceViewModel | null {
  if (!isRecord(payload)) return null;
  const { workspace_id: workspaceId, health, action, config, candidate_root: candidate } = payload;
  if (typeof workspaceId !== "string" || workspaceId === "") return null;
  if (!isHealth(health) || !isAction(action)) return null;
  if (config !== null && config !== undefined && !isRecord(config)) return null;
  let projectName = "Projet";
  let folderName = "Dossier local";
  let repoCount: number | null = null;
  let features: Array<{ name: string; on: boolean }> = [];
  let watchers = false;
  if (isRecord(config)) {
    if (typeof config.project_slug === "string" && config.project_slug !== "") {
      projectName = config.project_slug;
    }
    const roots = config.roots;
    if (isRecord(roots)) {
      if (typeof roots.workspace_root === "string" && roots.workspace_root !== "") {
        folderName = lastSegment(roots.workspace_root);
      }
      if (Array.isArray(roots.repo_roots)) repoCount = roots.repo_roots.length;
    }
    const flags = isRecord(config.features) ? config.features : {};
    features = FEATURE_LABELS.map(([key, name]) => ({ name, on: flags[key] === true }));
    watchers = flags.watchers === true;
  }
  return {
    workspaceId,
    projectName,
    folderName,
    health,
    action,
    candidateFolder: typeof candidate === "string" ? candidate : null,
    repoCount,
    features,
    watchSummary: watchers ? "La surveillance des dépôts est activée pour ce dossier." : null,
  };
}

export function workspaceHealthLabel(health: WorkspaceHealthView): string {
  switch (health) {
    case "valid":
      return "Prêt";
    case "config_missing":
      return "À configurer";
    case "config_invalid":
      return "À réparer";
    case "moved":
      return "Dossier déplacé";
    case "inaccessible":
      return "Inaccessible";
    case "project_unavailable":
      return "Projet retiré du serveur";
  }
}

export function workspaceActionLabel(action: WorkspaceActionView): string {
  switch (action) {
    case "none":
      return "";
    case "create_config":
      return "Choisissez un dossier pour commencer.";
    case "repair_config":
      return "Vérifiez la configuration, puis réessayez.";
    case "confirm_relocation":
      return "Confirmez le nouvel emplacement du dossier.";
    case "grant_access":
      return "Rétablissez l'accès au dossier, ou dissociez-le.";
    case "detach_workspace":
      return "Dissociez cet espace : rien ne sera supprimé.";
  }
}

function healthChip(health: WorkspaceHealthView): string {
  return `<span class="ws-chip ws-chip--${esc(health)}">${esc(workspaceHealthLabel(health))}</span>`;
}

export function workspaceListHtml(items: ReadonlyArray<WorkspaceViewModel>): string {
  if (items.length === 0) {
    return (
      `<section class="ws-list"><p class="ws-empty">` +
      `Aucun dossier lié pour l'instant. Ajoutez votre premier dossier pour relier ` +
      `un projet à ce poste.</p></section>`
    );
  }
  const rows = items
    .map(
      (item) =>
        `<li class="ws-row"><a href="${esc(P5_WORKSPACE_ROUTE)}/${esc(item.workspaceId)}">` +
        `<span class="ws-name">${esc(item.projectName)}</span>` +
        `<span class="ws-folder">${esc(item.folderName)}</span>` +
        `${healthChip(item.health)}</a></li>`,
    )
    .join("");
  return `<section class="ws-list"><ul>${rows}</ul></section>`;
}

function reposSection(repoCount: number | null): string {
  if (repoCount === null || repoCount === 0) {
    return `<details class="ws-details"><summary>Dépôts</summary><p>Sans dépôt : ce dossier reste utilisable tel quel.</p></details>`;
  }
  const label = repoCount === 1 ? "1 dépôt suivi" : `${repoCount} dépôts suivis`;
  return `<details class="ws-details"><summary>Dépôts</summary><p>${esc(label)}.</p></details>`;
}

function featuresSection(features: ReadonlyArray<{ name: string; on: boolean }>): string {
  if (features.length === 0) {
    return `<details class="ws-details"><summary>Fonctions locales</summary><p>Tout est coupé : le projet reste consultable.</p></details>`;
  }
  const rows = features
    .map((f) => `<li>${esc(f.name)} : ${f.on ? "activé" : "coupé"}</li>`)
    .join("");
  return `<details class="ws-details"><summary>Fonctions locales</summary><ul>${rows}</ul></details>`;
}

export function workspaceDetailHtml(view: WorkspaceViewModel): string {
  const next = workspaceActionLabel(view.action);
  const candidate =
    view.candidateFolder !== null
      ? `<p class="ws-candidate">Emplacement probable : ${esc(view.candidateFolder)}</p>`
      : "";
  const watch =
    view.watchSummary !== null ? `<p class="ws-watch">${esc(view.watchSummary)}</p>` : "";
  return (
    `<article class="ws-detail">` +
    `<header><h2>${esc(view.projectName)}</h2>${healthChip(view.health)}</header>` +
    `<p class="ws-folder">${esc(view.folderName)}</p>` +
    (next === "" ? "" : `<p class="ws-next">${esc(next)}</p>`) +
    candidate +
    reposSection(view.repoCount) +
    featuresSection(view.features) +
    watch +
    `</article>`
  );
}

export type WorkspaceFlowKind =
  | "new_project_with_folder"
  | "existing_project_with_folder"
  | "existing_project_without_folder"
  | "associate_local_folder"
  | "existing_git_repo"
  | "non_git_folder"
  | "workspace_moved"
  | "workspace_gone";

export function workspaceFlowTitle(kind: WorkspaceFlowKind): string {
  switch (kind) {
    case "new_project_with_folder":
      return "Nouveau projet + dossier";
    case "existing_project_with_folder":
      return "Projet existant + dossier";
    case "existing_project_without_folder":
      return "Projet sans dossier";
    case "associate_local_folder":
      return "Associer un dossier";
    case "existing_git_repo":
      return "Dépôt existant";
    case "non_git_folder":
      return "Dossier simple";
    case "workspace_moved":
      return "Dossier déplacé";
    case "workspace_gone":
      return "Dossier indisponible";
  }
}

export function workspaceFlowStepsHtml(
  kind: WorkspaceFlowKind,
  steps: ReadonlyArray<string>,
): string {
  const items = steps.map((step) => `<li>${esc(step)}</li>`).join("");
  return (
    `<section class="ws-flow"><h3>${esc(workspaceFlowTitle(kind))}</h3>` +
    (items === "" ? "" : `<ol>${items}</ol>`) +
    `</section>`
  );
}
