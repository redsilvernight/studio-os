/**
 * UI-4 — Page Projets : trouver, comprendre et ouvrir rapidement un projet.
 *
 * - Cartes à densité confortable : nom, description courte, état + slug
 *   discret. UUID / version / horodatages relégués dans un <details>
 *   secondaire. Aucun indicateur de progression ou score inventé.
 * - Filtre CLIENT-SIDE sur les projets déjà chargés (nom, description,
 *   slug) + filtre d'état. Aucun nouvel endpoint, aucun comportement de
 *   recherche globale. Maintenu en mémoire pendant la session de la page.
 * - Création (POST /projects, admin/developer, Idempotency-Key par tentative)
 *   dans une modale du Design System : focus initial, Échap, retour focus,
 *   erreurs accessibles, état de chargement, double soumission empêchée.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { createProject, type Project, type ProjectCreate } from "../creationsApi";
import { newIdempotencyKey } from "../claimsApi";
import {
  closeDsDialog,
  dsBadge,
  dsEmptyState,
  dsField,
  dsModalHtml,
  dsNotify,
  dsPageHeader,
  dsSkeleton,
  openDsDialog,
} from "../ds/ds";
import { selectProject } from "../store";
import { describeError, esc, fmtTime } from "../ui";

export type ProjectStateFilter = "all" | "active" | "archived";

export interface ProjectsPageState {
  query: string;
  stateFilter: ProjectStateFilter;
}

/** Filtre client honnête : sous-chaîne insensible à la casse sur les données déjà chargées. */
export function filterProjects(projects: Project[], state: ProjectsPageState): Project[] {
  const query = state.query.trim().toLowerCase();
  return projects.filter((project) => {
    if (state.stateFilter === "active" && project.archived) return false;
    if (state.stateFilter === "archived" && !project.archived) return false;
    if (query === "") return true;
    const haystack = `${project.name}\n${project.description ?? ""}\n${project.slug}`.toLowerCase();
    return haystack.includes(query);
  });
}

export function projectsLoadingHtml(): string {
  return `${dsPageHeader("Projets", "Trouvez un projet pour l'ouvrir dans son espace de travail.")}${dsSkeleton(4)}`;
}

export function projectsUnauthenticatedHtml(): string {
  return (
    `${dsPageHeader("Projets", "Trouvez un projet pour l'ouvrir dans son espace de travail.")}` +
    dsEmptyState(
      "Connectez-vous pour voir les projets",
      "Saisissez votre jeton machine pour charger la liste des projets.",
    )
  );
}

function toolbarHtml(state: ProjectsPageState, shown: number, total: number): string {
  const selected = (value: ProjectStateFilter): string => (state.stateFilter === value ? " selected" : "");
  return `<div class="projects-toolbar" role="search" aria-label="Filtrer les projets chargés">` +
    `<div class="ds-search">${'<span class="ds-search-icon" aria-hidden="true">⌕</span>'}<label class="ds-sr-only" for="projects-filter">Filtrer les projets déjà chargés</label>` +
    `<input class="ds-input" type="search" id="projects-filter" name="q" value="${esc(state.query)}" placeholder="Filtrer par nom, description ou slug…" autocomplete="off" /></div>` +
    `<label class="projects-state-filter"><span>État</span><select class="ds-select" id="projects-state">` +
    `<option value="all"${selected("all")}>Tous</option>` +
    `<option value="active"${selected("active")}>Actifs</option>` +
    `<option value="archived"${selected("archived")}>Archivés</option>` +
    `</select></label>` +
    `<p class="ds-list-sub" role="status" aria-live="polite">${shown} projet(s) affiché(s) sur ${total} chargé(s) — filtre local.</p>` +
    `</div>`;
}

function cardHtml(project: Project): string {
  const rawDesc = (project.description ?? "").trim();
  const desc =
    rawDesc === "" ? `<p class="ds-list-sub">Sans description.</p>` : `<p class="project-card-desc">${esc(rawDesc)}</p>`;
  const badge = project.archived ? dsBadge("Archivé", "warning") : dsBadge("Actif", "success");
  return `<li class="ds-card project-card"><div class="project-card-top"><h2 class="project-card-title"><a href="#/projects/${esc(project.id)}" data-open="${esc(project.id)}">${esc(project.name)}</a></h2>${badge}</div>` +
    `${desc}` +
    `<p class="ds-list-sub"><code class="mono">${esc(project.slug)}</code></p>` +
    `<details class="project-card-tech"><summary>Détails techniques</summary><dl>` +
    `<div><dt>Identifiant</dt><dd><code class="mono">${esc(project.id)}</code></dd></div>` +
    `<div><dt>Version</dt><dd>${project.version}</dd></div>` +
    `<div><dt>Créé le</dt><dd>${fmtTime(project.created_at)}</dd></div>` +
    `<div><dt>Mis à jour le</dt><dd>${fmtTime(project.updated_at)}</dd></div>` +
    `</dl></details>` +
    `</li>`;
}

/** Corps de la modale de création : champs labellisés, aide et zone d'erreur. */
export function projectCreateFormHtml(): string {
  return `<form id="project-create-form" novalidate>` +
    dsField("project-slug", "Slug", `<input class="ds-input" id="FIELD" name="slug" required placeholder="mon-projet" autocomplete="off" />`, "Identifiant lisible, sans espaces.") +
    dsField("project-name", "Nom", `<input class="ds-input" id="FIELD" name="name" required autocomplete="off" />`) +
    dsField("project-desc", "Description (facultative)", `<textarea class="ds-textarea" id="FIELD" name="description" rows="3"></textarea>`) +
    `<p class="ds-list-sub">POST /projects · admin/developer · clé d'idempotence générée par tentative.</p>` +
    `<div class="ds-field-error" id="project-create-error" role="alert" hidden></div>` +
    `<div class="ds-dialog-actions"><button class="ds-btn" type="button" data-ds-close>Annuler</button>` +
    `<button class="ds-btn ds-btn--primary" type="submit" id="project-create-submit">Créer le projet</button></div>` +
    `</form>`;
}

export interface ProjectsPageData {
  projects: Project[];
  state: ProjectsPageState;
  authed: boolean;
}

export function projectsPageHtml(data: ProjectsPageData): string {
  const header = dsPageHeader("Projets", "Trouvez un projet pour l'ouvrir dans son espace de travail.", [
    { label: "+ Nouveau projet", id: "project-new", variant: "primary" },
  ]);
  const visible = filterProjects(data.projects, data.state);
  const toolbar = toolbarHtml(data.state, visible.length, data.projects.length);
  let body: string;
  if (data.projects.length === 0) {
    body = dsEmptyState("Aucun projet", "Créez votre premier projet pour commencer à travailler.");
  } else if (visible.length === 0) {
    body = dsEmptyState(
      "Aucun projet ne correspond au filtre",
      "Modifiez ou effacez le filtre pour retrouver vos projets déjà chargés.",
    );
  } else {
    body = `<ul class="projects-grid">${visible.map(cardHtml).join("")}</ul>`;
  }
  return `<div class="projects">${header}${toolbar}${body}${dsModalHtml({ id: "project-create-dialog", title: "Nouveau projet", body: projectCreateFormHtml() })}</div>`;
}

async function fetchProjects(client: StudioClient): Promise<Project[]> {
  const result = await client.GET("/api/v1/projects");
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

function setCreateError(root: HTMLElement, message: string): void {
  const node = root.querySelector("#project-create-error");
  if (node === null) return;
  if (message === "") {
    node.setAttribute("hidden", "");
    node.textContent = "";
  } else {
    node.removeAttribute("hidden");
    node.textContent = message;
  }
}

function bindCreateDialog(root: HTMLElement, client: StudioClient, refresh: () => Promise<void>): void {
  const dialogId = "project-create-dialog";
  const openButton = root.querySelector<HTMLElement>("#project-new");
  openButton?.addEventListener("click", () => {
    setCreateError(root, "");
    openDsDialog(root, dialogId, openButton);
    root.querySelector<HTMLElement>("#project-slug")?.focus();
  });
  const form = root.querySelector<HTMLFormElement>("#project-create-form");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const input: ProjectCreate = {
      slug: String(data.get("slug") ?? "").trim(),
      name: String(data.get("name") ?? "").trim(),
      description: (() => {
        const raw = String(data.get("description") ?? "").trim();
        return raw === "" ? null : raw;
      })(),
    };
    if (input.slug === "" || input.name === "") {
      setCreateError(root, "Le slug et le nom sont obligatoires.");
      root.querySelector<HTMLElement>(input.slug === "" ? "#project-slug" : "#project-name")?.focus();
      return;
    }
    const submit = root.querySelector<HTMLButtonElement>("#project-create-submit");
    if (submit !== null) {
      submit.disabled = true;
      submit.classList.add("ds-btn--loading");
      submit.textContent = "Création en cours…";
    }
    setCreateError(root, "");
    // Une clé fraîche par tentative logique : la double soumission est
    // empêchée par le bouton désactivé, une nouvelle tentative après erreur
    // rejoue un corps identique sous une clé neuve.
    createProject(client, input, newIdempotencyKey())
      .then((created) => {
        closeDsDialog(root, dialogId);
        dsNotify(`Projet « ${created.name} » créé.`, "success");
        void refresh();
      })
      .catch((error: unknown) => {
        setCreateError(root, describeError(error));
        if (submit !== null) {
          submit.disabled = false;
          submit.classList.remove("ds-btn--loading");
          submit.textContent = "Créer le projet";
        }
      });
  });
}

export async function renderProjects(root: HTMLElement, ctx: { client: StudioClient; authed: boolean }): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = projectsUnauthenticatedHtml();
    return;
  }
  root.innerHTML = projectsLoadingHtml();
  let projects: Project[];
  try {
    projects = await fetchProjects(ctx.client);
  } catch (error) {
    root.innerHTML =
      `${dsPageHeader("Projets", "Trouvez un projet pour l'ouvrir dans son espace de travail.")}` +
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Projets indisponibles.</strong>${esc(describeError(error))}</div>`;
    return;
  }
  const state: ProjectsPageState = { query: "", stateFilter: "all" };

  const paint = (): void => {
    root.innerHTML = projectsPageHtml({ projects, state, authed: ctx.authed });
    bind();
  };

  const refresh = async (): Promise<void> => {
    try {
      projects = await fetchProjects(ctx.client);
    } catch {
      return;
    }
    paint();
  };

  const bind = (): void => {
    root.querySelectorAll<HTMLAnchorElement>("[data-open]").forEach((link) => {
      link.addEventListener("click", () => {
        selectProject(link.dataset["open"] ?? null);
      });
    });
    const filter = root.querySelector<HTMLInputElement>("#projects-filter");
    filter?.addEventListener("input", () => {
      state.query = filter.value;
      paint();
      const next = root.querySelector<HTMLInputElement>("#projects-filter");
      if (next !== null) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    });
    root.querySelector<HTMLSelectElement>("#projects-state")?.addEventListener("change", (event) => {
      state.stateFilter = (event.target as HTMLSelectElement).value as ProjectStateFilter;
      paint();
      root.querySelector<HTMLSelectElement>("#projects-state")?.focus();
    });
    bindCreateDialog(root, ctx.client, refresh);
  };

  paint();
}
