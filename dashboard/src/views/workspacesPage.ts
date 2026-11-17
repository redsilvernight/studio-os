import type { StudioClient } from "../api";
import { getPlatform, type PickResult, type Platform } from "../platform";
import type {
  DetectedRepositoryView,
  IdentityView,
  LocalWorkspaceConfig,
  WorkspaceStatus,
} from "../platform/generated/local-contracts.generated";
import { fetchIdentity } from "../identityApi";
import { describeError, esc } from "../ui";
import { dsPageHeader } from "../ds/ds";
import {
  confirmRoots,
  detectedFolderName,
  findLinkedWorkspace,
  linkDetectedRepository,
  listDetectedRepositories,
  listWorkspaces,
  saveWorkspaceConfig,
  workspaceErrorMessage,
} from "../workspaces/api";
import { toWorkspaceViewModel, workspaceDetailHtml, workspaceListHtml } from "../workspaces/workspaces";

export type FolderPickOutcome =
  | { kind: "selected"; path: string; displayName: string }
  | { kind: "cancelled" }
  | { kind: "unavailable" }
  | { kind: "error"; code: string };

type Project = { id: string; name: string; slug: string };
export interface WorkspacesContext { client: StudioClient; authed: boolean }
export interface PageState {
  items: WorkspaceStatus[];
  detected: DetectedRepositoryView[];
  projects: Project[];
  identity: IdentityView | null;
  role: string | null;
  outcome: FolderPickOutcome | null;
  selectedProject: string;
  error: string;
  notice: string;
  busy: boolean;
  linking: string | null;
  editing: string | null;
}

/** La liaison est un geste d'écriture serveur : admin/developer uniquement, jamais viewer. */
export function canLinkDetected(role: string | null): boolean {
  return role === "admin" || role === "developer";
}

/** Motif d'enregistrement en phrase FR fixe, jamais de jargon machine. */
export function detectedReasonLabel(reason: string): string {
  switch (reason) {
    case "not_found": return "Dépôt inconnu du serveur";
    case "ambiguous": return "Dépôt lié à plusieurs projets";
    case "server_unreachable": return "Serveur injoignable lors de la détection";
    case "server_error": return "Erreur serveur lors de la détection";
    default: return "Dépôt non suivi";
  }
}

export function toFolderOutcome(result: PickResult): FolderPickOutcome {
  switch (result.status) {
    case "selected": {
      const path = typeof result.path === "string" ? result.path : "";
      if (path === "" || path.length > 4096 || !/^(?:[a-z]:[\\/]|\/(?!\/))/i.test(path)) return { kind: "error", code: "invalid_selection" };
      return { kind: "selected", path, displayName: result.display_name };
    }
    case "cancelled": return { kind: "cancelled" };
    case "unavailable": return { kind: "unavailable" };
    default: return { kind: "error", code: typeof result.code === "string" ? result.code : "error" };
  }
}

export async function pickWorkspaceFolder(platform: Platform = getPlatform()): Promise<FolderPickOutcome> {
  try { return toFolderOutcome(await platform.chooseFolder({ title: "Choisir le dossier du projet" })); }
  catch { return { kind: "error", code: "picker_failed" }; }
}

export function outcomeMessage(outcome: FolderPickOutcome | null): string {
  if (outcome === null) return "";
  switch (outcome.kind) {
    case "selected": return `Dossier choisi : ${outcome.displayName}. Confirmez son association au projet.`;
    case "cancelled": return "Sélection annulée. Aucun dossier n'a été modifié.";
    case "unavailable": return "Le sélecteur de dossier natif n'est pas disponible ici.";
    default: return "Le dossier n'a pas pu être sélectionné. Aucun dossier n'a été modifié.";
  }
}

/**
 * P3-detected — « Dépôts détectés non suivis » : la liste du pont local, pas
 * un formulaire manuel. Chaque dépôt propose « Lier à un projet »
 * (admin/developer : le remote rejoint les `repositories` du projet choisi
 * puis le dossier est suivi, sans autre action ; dépôt sans remote : lien
 * manuel direct) ou, pour un viewer, le seul texte « Demander l'accès »,
 * sans action réseau. Jamais de chemin brut : seul le nom du dossier et le
 * remote normalisé sont affichés.
 */
export function detectedSectionHtml(state: PageState, outcome: FolderPickOutcome | null): string {
  const message = outcomeMessage(outcome);
  const status = message === "" ? "" : `<p role="status" data-testid="workspaces-outcome" data-outcome="${esc(outcome?.kind ?? "")}">${esc(message)}</p>`;
  const options = state.projects.map((project) => `<option value="${esc(project.id)}"${state.selectedProject === project.id ? " selected" : ""}>${esc(project.name)}</option>`).join("");
  const canLink = canLinkDetected(state.role);
  const rows = state.detected.map((entry, index) => {
    const folder = detectedFolderName(entry.root);
    const remote = entry.remotes?.[0] ?? null;
    const busy = state.busy && state.linking === entry.root;
    const action = canLink
      ? `<button type="button" class="ds-btn ds-btn--primary" data-detected-link="${index}"${state.busy ? " disabled" : ""} aria-label="${esc(remote ? `Lier ${folder} au projet sélectionné` : `Lier manuellement ${folder} au projet sélectionné`)}">${busy ? "Liaison…" : remote ? "Lier à un projet" : "Lier manuellement"}</button>`
      : `<p class="ds-list-sub">Demander l'accès : la liaison est réservée aux admins et developers. Demandez à un administrateur de rattacher ce dépôt.</p>`;
    return `<li class="ds-card"><h3>${esc(folder)}</h3>` +
      `<p class="ds-list-sub">${remote ? `Dépôt : ${esc(remote)}` : "Dépôt sans remote : lien manuel au projet choisi."} · ${esc(detectedReasonLabel(entry.reason))} · Vu le ${esc(entry.last_seen_at.slice(0, 10))}</p>` +
      action + `</li>`;
  }).join("");
  return `<section aria-labelledby="detected-repos-title" data-testid="detected-repos"><h2 id="detected-repos-title">Dépôts détectés non suivis</h2>` +
    `<p class="ds-list-sub">Ces dépôts existent sur ce poste mais ne sont suivis par aucun dossier. L'association et le chemin sont enregistrés uniquement sur ce poste.</p>` +
    (state.projects.length > 0
      ? `<label for="workspace-project">Projet</label><select class="ds-select" id="workspace-project" name="project_id">${options}</select>`
      : `<p class="ds-list-sub">Connectez-vous et créez un projet pour pouvoir lier un dépôt.</p>`) +
    (state.detected.length === 0
      ? `<p class="ds-list-sub">Aucun dépôt détecté non suivi sur ce poste.</p>`
      : `<ul class="ds-list">${rows}</ul>`) +
    status + `</section>`;
}

function cardsHtml(state: PageState): string {
  if (state.items.length === 0) return workspaceListHtml([]);
  return `<ul class="ds-list">${state.items.map((item) => {
    const view = toWorkspaceViewModel(item);
    if (!view) return "";
    const config = item.config;
    const project = state.projects.find((candidate) => candidate.id === config?.project_id);
    if (project) view.projectName = project.name;
    const machine = state.identity?.machine?.machine_name ?? state.identity?.workstation_name ?? "Poste non enregistré";
    const edit = state.editing === item.workspace_id && config;
    return `<li class="ds-card" data-workspace="${esc(item.workspace_id)}">${workspaceDetailHtml(view)}` +
      `<p>Poste : ${esc(machine)} · Dossier vérifié sur ce poste</p>` +
      `<div class="settings-actions">${config ? `<a class="ds-btn" href="#/projects/${esc(config.project_id)}">Ouvrir le projet</a> <button type="button" class="ds-btn" data-workspace-edit="${esc(item.workspace_id)}">Configurer le dossier</button> <a class="ds-btn" href="#/configuration/integrations/${esc(item.workspace_id)}">Configurer les outils</a>` : ""}</div>` +
      (edit ? `<form data-workspace-config="${esc(item.workspace_id)}"><h3>Configuration de ce dossier</h3><label><input name="watchers" type="checkbox"${config.features?.watchers !== false ? " checked" : ""}> Activer le suivi Git de ce dossier</label>` +
        `<p class="ds-list-sub">Le suivi observe les dépôts Git existants lorsque l'assistant local est démarré. Un dossier sans dépôt reste utilisable.</p><p><button type="submit" class="ds-btn ds-btn--primary"${state.busy ? " disabled" : ""}>Enregistrer le suivi</button> <button type="button" class="ds-btn" data-workspace-move="${esc(item.workspace_id)}"${state.busy ? " disabled" : ""}>Choisir le nouvel emplacement</button></p></form>` +
        // P3 : la mémoire, l'environnement et l'assistant IA du dossier sont
        // montés ici (module dédié, chargement différé) ; le travailleur B y
        // ajoute sa propre section « Dépôts détectés » sans conflit.
        `<div data-folder-setup="${esc(item.workspace_id)}"><p role="status">Chargement de la configuration du dossier…</p></div>` : "") + `</li>`;
  }).join("")}</ul>`;
}

export function workspacesPageHtml(mode: "web" | "desktop", outcome: FolderPickOutcome | null, state?: PageState): string {
  const header = `<p class="ds-hero-eyebrow">Administration / Espaces de travail</p>` + dsPageHeader("Espaces de travail", "Projets, dossiers locaux et poste.");
  if (mode === "web") return `${header}<section class="ds-card" data-testid="workspaces-web"><p>Les dossiers locaux sont gérés dans Studi'OS Desktop.</p><p class="ds-list-sub">Le navigateur permet de consulter les projets ; l'association d'un dossier, son suivi et son ouverture restent propres à chaque poste Desktop.</p><a class="ds-btn" href="#/projects">Ouvrir les projets</a></section>`;
  return `${header}<section class="ds-card" data-testid="workspaces-desktop">` +
    `${state?.error ? `<p class="ds-notice ds-notice--danger" role="alert">${esc(state.error)}</p>` : ""}` +
    `${state?.notice ? `<p role="status">${esc(state.notice)}</p>` : ""}` +
    `${state ? cardsHtml(state) : workspaceListHtml([])}` +
    `${state ? detectedSectionHtml(state, outcome) : ""}` +
    `<details class="ds-tech"><summary>Détails techniques</summary><p>Les chemins, les associations et la configuration du suivi restent locaux à ce poste et à ce profil serveur.</p></details></section>`;
}

export async function renderWorkspaces(root: HTMLElement, platform: Platform = getPlatform(), ctx: WorkspacesContext | null = null): Promise<void> {
  if (platform.mode === "web") { root.innerHTML = workspacesPageHtml("web", null); return; }
  const state: PageState = { items: [], detected: [], projects: [], identity: null, role: null, outcome: null, selectedProject: "", error: "", notice: "", busy: false, linking: null, editing: null };
  const paint = (): void => {
    root.innerHTML = workspacesPageHtml("desktop", state.outcome, state);
    root.querySelector<HTMLSelectElement>("#workspace-project")?.addEventListener("change", (event) => { state.selectedProject = (event.target as HTMLSelectElement).value; });
    root.querySelectorAll<HTMLButtonElement>("[data-detected-link]").forEach((button) => button.addEventListener("click", () => {
      const index = Number(button.dataset["detectedLink"]);
      if (Number.isInteger(index)) void linkDetected(index);
    }));
    root.querySelectorAll<HTMLButtonElement>("[data-workspace-edit]").forEach((button) => button.addEventListener("click", () => { state.editing = button.dataset["workspaceEdit"] ?? null; paint(); root.querySelector<HTMLElement>("[data-workspace-config] h3")?.scrollIntoView({ block: "nearest" }); }));
    root.querySelectorAll<HTMLFormElement>("[data-workspace-config]").forEach((form) => form.addEventListener("submit", (event) => {
      event.preventDefault();
      const config = state.items.find((item) => item.workspace_id === form.dataset["workspaceConfig"])?.config;
      if (config) void save(config, null, form.querySelector<HTMLInputElement>('[name="watchers"]')?.checked ?? false);
    }));
    root.querySelectorAll<HTMLButtonElement>("[data-workspace-move]").forEach((button) => button.addEventListener("click", () => {
      const config = state.items.find((item) => item.workspace_id === button.dataset["workspaceMove"])?.config;
      if (!config) return;
      button.disabled = true;
      void pickWorkspaceFolder(platform).then((picked) => {
        if (picked.kind === "selected") return save(config, picked);
        state.outcome = picked; paint(); return undefined;
      });
    }));
    // Branchement P3 minimal : la configuration par dossier (mémoire,
    // environnement, harnais) vit dans son propre module.
    const setupHost = state.editing ? root.querySelector<HTMLElement>(`[data-folder-setup="${state.editing}"]`) : null;
    if (setupHost && state.editing) {
      const workspaceId = state.editing;
      void import("./workspaceFolderSetup").then((module) => module.renderFolderSetup(setupHost, platform, workspaceId));
    }
  };
  const refresh = async (): Promise<void> => {
    const result = await listWorkspaces(platform);
    if (!result.ok) { state.error = workspaceErrorMessage(result.error); return; }
    state.items = result.value;
    const detected = await listDetectedRepositories(platform);
    if (!detected.ok) { state.error = workspaceErrorMessage(detected.error); return; }
    state.detected = detected.value;
  };
  const linkDetected = async (entryIndex: number): Promise<void> => {
    if (state.busy || !canLinkDetected(state.role)) return;
    const entry = state.detected[entryIndex];
    const project = state.projects.find((item) => item.id === state.selectedProject);
    if (!entry || !project || !state.identity || !ctx) return;
    if (findLinkedWorkspace(state.items, project.id, entry.root)) {
      state.error = ""; state.notice = "Ce dossier est déjà associé à ce projet sur ce poste."; paint();
      return;
    }
    state.busy = true; state.linking = entry.root; state.error = ""; state.notice = ""; paint();
    try {
      const result = await linkDetectedRepository(ctx.client, platform, {
        root: entry.root,
        remote: entry.remotes?.[0] ?? null,
        projectId: project.id,
        projectSlug: project.slug,
        profile: state.identity.profile,
      });
      if (!result.ok) throw new Error(result.message);
      state.notice = "Dépôt lié au projet sur ce poste.";
      await refresh();
    } catch (error) { state.error = describeError(error); }
    state.busy = false; state.linking = null; paint();
  };
  const save = async (existing: LocalWorkspaceConfig, replacement: Extract<FolderPickOutcome, { kind: "selected" }> | null = null, watchers?: boolean): Promise<void> => {
    if (state.busy) return;
    const picked = replacement ?? (state.outcome?.kind === "selected" ? state.outcome : null);
    if (!picked) return;
    state.busy = true; state.error = ""; state.notice = ""; paint();
    try {
      const now = new Date().toISOString();
      const roots = { workspace_root: picked.path, repo_roots: [] };
      const changedRoots = JSON.stringify(existing.roots) !== JSON.stringify(roots);
      let confirmation: string | undefined;
      if (changedRoots) {
        const confirmed = await confirmRoots(platform, roots);
        if (!confirmed.ok) throw new Error(workspaceErrorMessage(confirmed.error));
        confirmation = confirmed.value.root_confirmation_id;
      }
      const config = { ...existing, roots, updated_at: now, ...(watchers === undefined ? {} : { features: { ...existing.features, watchers }, watchers: watchers ? existing.watchers ?? {} : null }) };
      const result = await saveWorkspaceConfig(platform, { config, current_roots: existing.roots,
        ...(confirmation ? { root_confirmation_id: confirmation } : {}), expected_updated_at: existing.updated_at });
      if (!result.ok) throw new Error(workspaceErrorMessage(result.error));
      state.outcome = null; state.notice = "Configuration enregistrée sur ce poste.";
      await refresh();
    } catch (error) { state.error = describeError(error); }
    state.busy = false; paint();
  };
  root.innerHTML = `<p role="status">Chargement des espaces de travail de ce poste…</p>`;
  try {
    const [identity] = await Promise.all([
      platform.request("identity.get_view"),
      refresh(),
      ctx?.authed ? ctx.client.GET("/api/v1/projects").then((result) => {
        if (!result.response.ok || !result.data) throw new Error("Les projets ne sont pas disponibles. Réessayez après reconnexion.");
        state.projects = result.data.filter((project) => !project.archived);
        state.selectedProject = state.projects[0]?.id ?? "";
      }) : Promise.resolve(),
      ctx?.authed ? fetchIdentity(ctx.client).then((me) => {
        state.role = me?.role ?? null;
      }).catch(() => undefined) : Promise.resolve(),
    ]);
    if (identity.ok) state.identity = identity.response.payload as unknown as IdentityView;
    else if (!state.error) state.error = workspaceErrorMessage(identity.error);
  } catch (error) { state.error = describeError(error); }
  paint();
}
