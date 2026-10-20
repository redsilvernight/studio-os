import type { StudioClient } from "../api";
import { getPlatform, type PickResult, type Platform } from "../platform";
import type { IdentityView, LocalWorkspaceConfig, WorkspaceStatus } from "../platform/generated/local-contracts.generated";
import { describeError, esc, newUuid } from "../ui";
import { dsPageHeader } from "../ds/ds";
import { confirmRoots, listWorkspaces, saveWorkspaceConfig, workspaceErrorMessage } from "../workspaces/api";
import { toWorkspaceViewModel, workspaceDetailHtml, workspaceListHtml } from "../workspaces/workspaces";

export type FolderPickOutcome =
  | { kind: "selected"; path: string; displayName: string }
  | { kind: "cancelled" }
  | { kind: "unavailable" }
  | { kind: "error"; code: string };

type Project = { id: string; name: string; slug: string };
export interface WorkspacesContext { client: StudioClient; authed: boolean }
interface PageState {
  items: WorkspaceStatus[];
  projects: Project[];
  identity: IdentityView | null;
  outcome: FolderPickOutcome | null;
  selectedProject: string;
  error: string;
  notice: string;
  busy: boolean;
  editing: string | null;
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
        `<p class="ds-list-sub">Le suivi observe les dépôts Git existants lorsque l'assistant local est démarré. Un dossier sans dépôt reste utilisable.</p><p><button type="submit" class="ds-btn ds-btn--primary"${state.busy ? " disabled" : ""}>Enregistrer le suivi</button> <button type="button" class="ds-btn" data-workspace-move="${esc(item.workspace_id)}"${state.busy ? " disabled" : ""}>Choisir le nouvel emplacement</button></p></form>` : "") + `</li>`;
  }).join("")}</ul>`;
}

export function workspacesPageHtml(mode: "web" | "desktop", outcome: FolderPickOutcome | null, state?: PageState): string {
  const header = `<p class="ds-hero-eyebrow">Administration / Espaces de travail</p>` + dsPageHeader("Espaces de travail", "Projets, dossiers locaux et poste.");
  if (mode === "web") return `${header}<section class="ds-card" data-testid="workspaces-web"><p>Les dossiers locaux sont gérés dans Studi'OS Desktop.</p><p class="ds-list-sub">Le navigateur permet de consulter les projets ; l'association d'un dossier, son suivi et son ouverture restent propres à chaque poste Desktop.</p><a class="ds-btn" href="#/projects">Ouvrir les projets</a></section>`;
  const message = outcomeMessage(outcome);
  const status = message === "" ? "" : `<p role="status" data-testid="workspaces-outcome" data-outcome="${esc(outcome?.kind ?? "")}">${esc(message)}</p>`;
  const projects = state?.projects ?? [];
  const options = projects.map((project) => `<option value="${esc(project.id)}"${state?.selectedProject === project.id ? " selected" : ""}>${esc(project.name)}</option>`).join("");
  const canSave = outcome?.kind === "selected" && state?.identity && state.selectedProject !== "" && !state.busy;
  return `${header}<section class="ds-card" data-testid="workspaces-desktop">` +
    `${state?.error ? `<p class="ds-notice ds-notice--danger" role="alert">${esc(state.error)}</p>` : ""}` +
    `${state?.notice ? `<p role="status">${esc(state.notice)}</p>` : ""}` +
    `${state ? cardsHtml(state) : workspaceListHtml([])}` +
    `<form data-workspace-add><h2>Associer un dossier à un projet</h2><p class="ds-list-sub">L'association et le chemin sont enregistrés uniquement sur ce poste. Le même projet peut avoir un autre dossier sur votre autre ordinateur.</p>` +
    (options ? `<label for="workspace-project">Projet</label><select class="ds-select" id="workspace-project" name="project_id">${options}</select>` : `<p class="ds-list-sub">Connectez-vous et créez un projet pour pouvoir associer un dossier.</p>`) +
    `<p><button class="ds-btn" type="button" id="workspace-add"${state?.busy ? " disabled" : ""}>Choisir un dossier</button></p>${status}` +
    `<button class="ds-btn ds-btn--primary" type="submit"${canSave ? "" : " disabled"}>Associer le dossier au projet</button></form>` +
    `<details class="ds-tech"><summary>Détails techniques</summary><p>Les chemins, les associations et la configuration du suivi restent locaux à ce poste et à ce profil serveur.</p></details></section>`;
}

export async function renderWorkspaces(root: HTMLElement, platform: Platform = getPlatform(), ctx: WorkspacesContext | null = null): Promise<void> {
  if (platform.mode === "web") { root.innerHTML = workspacesPageHtml("web", null); return; }
  const state: PageState = { items: [], projects: [], identity: null, outcome: null, selectedProject: "", error: "", notice: "", busy: false, editing: null };
  const paint = (): void => {
    root.innerHTML = workspacesPageHtml("desktop", state.outcome, state);
    root.querySelector<HTMLSelectElement>("#workspace-project")?.addEventListener("change", (event) => { state.selectedProject = (event.target as HTMLSelectElement).value; });
    root.querySelector("#workspace-add")?.addEventListener("click", () => {
      void pickWorkspaceFolder(platform).then((picked) => { state.outcome = picked; paint(); });
    });
    root.querySelector("[data-workspace-add]")?.addEventListener("submit", (event) => { event.preventDefault(); void save(); });
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
  };
  const refresh = async (): Promise<void> => {
    const result = await listWorkspaces(platform);
    if (!result.ok) { state.error = workspaceErrorMessage(result.error); return; }
    state.items = result.value;
  };
  const save = async (existing?: LocalWorkspaceConfig, replacement: Extract<FolderPickOutcome, { kind: "selected" }> | null = null, watchers?: boolean): Promise<void> => {
    if (state.busy) return;
    const picked = replacement ?? (state.outcome?.kind === "selected" ? state.outcome : null);
    const project = state.projects.find((item) => item.id === state.selectedProject);
    if (!existing && (!picked || !project || !state.identity)) return;
    state.busy = true; state.error = ""; state.notice = ""; paint();
    try {
      const now = new Date().toISOString();
      const roots = replacement || !existing ? { workspace_root: picked!.path, repo_roots: [] } : existing.roots;
      const changedRoots = !existing || JSON.stringify(existing.roots) !== JSON.stringify(roots);
      let confirmation: string | undefined;
      if (changedRoots) {
        const confirmed = await confirmRoots(platform, roots);
        if (!confirmed.ok) throw new Error(workspaceErrorMessage(confirmed.error));
        confirmation = confirmed.value.root_confirmation_id;
      }
      const config = existing ? { ...existing, roots, updated_at: now, ...(watchers === undefined ? {} : { features: { ...existing.features, watchers }, watchers: watchers ? existing.watchers ?? {} : null }) } : {
        schema_version: 1, workspace_id: newUuid(), profile: state.identity!.profile, project_id: project!.id, project_slug: project!.slug,
        roots, features: { watchers: true, knowledge: false, code_graph: false, harness: false }, secret_references: [], created_at: now, updated_at: now,
      };
      const result = await saveWorkspaceConfig(platform, { config, current_roots: existing?.roots ?? null,
        ...(confirmation ? { root_confirmation_id: confirmation } : {}), ...(existing ? { expected_updated_at: existing.updated_at } : {}) });
      if (!result.ok) throw new Error(workspaceErrorMessage(result.error));
      state.outcome = null; state.notice = existing ? "Configuration enregistrée sur ce poste." : "Dossier associé au projet sur ce poste.";
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
    ]);
    if (identity.ok) state.identity = identity.response.payload as unknown as IdentityView;
    else if (!state.error) state.error = workspaceErrorMessage(identity.error);
  } catch (error) { state.error = describeError(error); }
  paint();
}
