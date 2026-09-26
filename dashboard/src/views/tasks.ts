/**
 * UI-5 — Tâches : véritable surface de travail quotidienne.
 *
 * - Deux présentations des MÊMES données et actions : Liste (trouver,
 *   filtrer, parcourir — vue par défaut, la plus accessible) et Tableau
 *   (comprendre et modifier les états rapidement).
 * - Source : GET /api/v1/tasks?project_id&limit&offset (pagination réelle,
 *   sans total/filtre/tri/recherche serveur — tout le reste est un filtre
 *   client honnête sur les tâches déjà chargées, dans l'ordre du serveur).
 * - Clés backend inchangées (created/in_progress/blocked/completed), seuls
 *   les libellés visibles sont français (taskStatus.ts).
 * - Changement de statut : drag & drop + alternative clavier explicite
 *   « Déplacer vers… ». PATCH + If-Match-Version, 409 → relecture serveur,
 *   AUCUN retry automatique silencieux.
 * - Création : POST /tasks + Idempotency-Key fraîche par tentative, en
 *   modale DS (focus, Échap, retour focus, double soumission empêchée).
 */
import type { StudioClient } from "../api";
import { ApiError } from "../api";
import { listTasks, patchTask, TASK_PAGE_LIMIT, type Task } from "../tasksApi";
import { createTask, isUuid, type Project } from "../creationsApi";
import { newIdempotencyKey } from "../claimsApi";
import {
  closeDsDialog,
  dsBadge,
  dsEmptyState,
  dsField,
  focusDsErrorBox,
  dsModalHtml,
  dsNotify,
  dsPageHeader,
  dsSkeleton,
  openDsDialog,
} from "../ds/ds";
import {
  columnToStatus,
  statusColumn,
  TASK_COLUMNS,
  taskClaimHint,
  taskClaimTitle,
  taskStatusLabel,
  taskStatusTone,
  type TaskStatus,
} from "../taskStatus";
import { describeError, esc } from "../ui";
// Styles colocalisés : la page reste autonome sans toucher au bloc
// d'imports CSS de main.ts.
import "./tasks.css";

export interface TasksContext {
  client: StudioClient;
  authed: boolean;
  projectId?: string;
  scopeLabel: string;
  /** 2 lorsque le bloc est embarqué (Workspace) : titre en h2, un seul h1 par page. */
  headingLevel?: 1 | 2;
}

export type TasksView = "list" | "board";

export type TasksStatusFilter = "all" | TaskStatus;

export interface TasksPageState {
  view: TasksView;
  filter: TasksStatusFilter;
  query: string;
}

export interface TasksPageMessage {
  human: string;
  technical?: string;
}

const STATUSES: TaskStatus[] = ["created", "in_progress", "blocked", "completed"];

/** État initial : Liste par défaut (meilleure accessibilité et lisibilité). */
export function initialTasksState(): TasksPageState {
  return { view: "list", filter: "all", query: "" };
}

/** Rien de saisi, rien de filtré : le bouton de réinitialisation dort. */
export function isTasksDefaultState(state: TasksPageState): boolean {
  return state.filter === "all" && state.query.trim() === "";
}

/**
 * Filtre client honnête sur les tâches déjà chargées : statut exact, puis
 * sous-chaîne insensible à la casse sur titre, description et nom de projet.
 * L'ordre du serveur est toujours conservé (aucun tri inventé).
 */
export function filterTasks(
  tasks: Task[],
  state: TasksPageState,
  projectNames: Record<string, string> = {},
): Task[] {
  const query = state.query.trim().toLowerCase();
  return tasks.filter((task) => {
    if (state.filter !== "all" && task.status !== state.filter) return false;
    if (query === "") return true;
    const haystack = `${task.title}\n${task.description ?? ""}\n${projectNames[task.project_id] ?? ""}`.toLowerCase();
    return haystack.includes(query);
  });
}

export function tasksLoadingHtml(scopeLabel: string, headingLevel: 1 | 2 = 1): string {
  return `${tasksHeaderHtml(scopeLabel, false, headingLevel)}${dsSkeleton(4)}`;
}

/**
 * En-tête : h1 en page pleine, h2 lorsque le bloc est embarqué dans le
 * Workspace projet (qui porte déjà son propre h1) — un seul h1 par page.
 */
export function tasksHeaderHtml(scopeLabel: string, authed: boolean, headingLevel: 1 | 2 = 1): string {
  if (headingLevel === 1) {
    return dsPageHeader("Tâches", scopeLabel, authed ? [{ label: "+ Nouvelle tâche", id: "task-new", variant: "primary" }] : []);
  }
  const action = authed
    ? `<p><button class="ds-btn ds-btn--primary" type="button" id="task-new">+ Nouvelle tâche</button></p>`
    : "";
  return `<div class="ds-section-header"><h2>Tâches</h2></div><p class="ds-list-sub">${esc(scopeLabel)}</p>${action}`;
}

function viewToggleHtml(view: TasksView): string {
  const pressed = (value: TasksView): string => (view === value ? ` aria-pressed="true"` : ` aria-pressed="false"`);
  const cls = (value: TasksView): string =>
    view === value ? "ds-btn ds-btn--primary" : "ds-btn";
  return `<div class="tasks-view-toggle" role="group" aria-label="Présentation des tâches">` +
    `<button class="${cls("list")}" type="button" data-view="list"${pressed("list")}>Liste</button>` +
    `<button class="${cls("board")}" type="button" data-view="board"${pressed("board")}>Tableau</button>` +
    `</div>`;
}

export function tasksToolbarHtml(
  state: TasksPageState,
  shown: number,
  total: number,
): string {
  const statusOptions = [`<option value="all"${state.filter === "all" ? " selected" : ""}>Tous les statuts</option>`]
    .concat(
      STATUSES.map(
        (status) =>
          `<option value="${status}"${state.filter === status ? " selected" : ""}>${esc(taskStatusLabel(status))}</option>`,
      ),
    )
    .join("");
  return `<div class="tasks-toolbar" role="search" aria-label="Filtrer les tâches chargées">` +
    `${viewToggleHtml(state.view)}` +
    `<div class="ds-search"><span class="ds-search-icon" aria-hidden="true">⌕</span>` +
    `<label class="ds-sr-only" for="tasks-search">Filtrer les tâches déjà chargées</label>` +
    `<input class="ds-input" type="search" id="tasks-search" value="${esc(state.query)}" placeholder="Filtrer par titre, description ou projet…" autocomplete="off" /></div>` +
    `<label class="tasks-status-filter"><span>Statut</span>` +
    `<select class="ds-select" id="tasks-status">${statusOptions}</select></label>` +
    `<button class="ds-btn ds-btn--ghost" type="button" data-reset${isTasksDefaultState(state) ? " disabled" : ""}>Réinitialiser</button>` +
    `<p class="ds-list-sub" role="status" aria-live="polite">${shown} tâche(s) affichée(s) sur ${total} chargée(s) — recherche et filtre locaux.</p>` +
    `</div>`;
}

function taskDescriptionExcerpt(task: Task, max = 140): string {
  const raw = (task.description ?? "").trim().replace(/\s+/g, " ");
  if (raw === "") return "";
  return raw.length > max ? `${raw.slice(0, max)}…` : raw;
}

/**
 * Contrôle de changement de statut au clavier (alternative explicite au
 * drag & drop, présente dans les deux vues). Même PATCH versionné, même
 * sémantique 409 que le drop.
 */
export function taskMoveControlHtml(task: Task, authed: boolean): string {
  const options = STATUSES.map(
    (status) =>
      `<option value="${status}"${task.status === status ? " selected" : ""}>${esc(taskStatusLabel(status))}</option>`,
  ).join("");
  return `<div class="task-move"><label for="move-${esc(task.id)}">Déplacer vers…</label>` +
    `<div class="task-move-row"><select class="ds-select" id="move-${esc(task.id)}" data-status="${esc(task.id)}"${authed ? "" : " disabled"}>${options}</select>` +
    `<button class="ds-btn ds-btn--sm" type="button" data-move="${esc(task.id)}" data-version="${task.version}"${authed ? "" : " disabled"}>Déplacer</button></div></div>`;
}

export interface TasksRenderOptions {
  authed: boolean;
  showProject: boolean;
  projectNames?: Record<string, string>;
}

function taskContextLine(task: Task, options: TasksRenderOptions): string {
  const parts: string[] = [];
  if (options.showProject) {
    const name = options.projectNames?.[task.project_id] ?? null;
    parts.push(name === null || name === "" ? "Projet inconnu" : name);
  }
  const excerpt = taskDescriptionExcerpt(task);
  if (excerpt !== "") parts.push(excerpt);
  parts.push(taskClaimHint(task));
  return parts.map((part) => esc(part)).join(" · ");
}

/** Liste : titre + statut, puis projet · prise, puis extrait (secondaires). */
function taskListRowHtml(task: Task, options: TasksRenderOptions): string {
  const meta: string[] = [];
  if (options.showProject) {
    const name = options.projectNames?.[task.project_id] ?? null;
    meta.push(`<span class="task-project">${esc(name === null || name === "" ? "Projet inconnu" : name)}</span>`);
  }
  const claimTitle = taskClaimTitle(task);
  meta.push(claimTitle === "" ? esc(taskClaimHint(task)) : `<span title="${esc(claimTitle)}">${esc(taskClaimHint(task))}</span>`);
  const excerpt = taskDescriptionExcerpt(task);
  return `<li class="ds-list-item task-row"><div class="grow task-main">` +
    `<div class="task-head"><div class="ds-list-title"><a href="#/tasks/${esc(task.id)}">${esc(task.title)}</a></div>` +
    `${dsBadge(taskStatusLabel(task.status), taskStatusTone(task.status))}</div>` +
    `<div class="ds-list-sub task-meta">${meta.join(" · ")}</div>` +
    `${excerpt === "" ? "" : `<div class="ds-list-sub task-excerpt">${esc(excerpt)}</div>`}` +
    `</div>${taskMoveControlHtml(task, options.authed)}</li>`;
}

export function tasksListHtml(tasks: Task[], options: TasksRenderOptions): string {
  if (tasks.length === 0) return "";
  return `<ul class="ds-list ds-list--card tasks-list">` +
    tasks.map((task) => taskListRowHtml(task, options)).join("") +
    `</ul>`;
}

export function tasksBoardHtml(tasks: Task[], options: TasksRenderOptions): string {
  const groups: Record<string, Task[]> = { TODO: [], "IN PROGRESS": [], BLOCKED: [], DONE: [] };
  for (const task of tasks) {
    const column = statusColumn(task.status);
    if (column !== "UNKNOWN") groups[column]?.push(task);
  }
  return `<div class="kanban tasks-board">` +
    TASK_COLUMNS.map((column) => {
      const cards = groups[column] ?? [];
      const label = taskStatusLabel(columnToStatus(column));
      const items = cards
        .map(
          (task) =>
            `<li class="ds-card task-card" data-card="${esc(task.id)}" data-version="${task.version}" data-status-current="${esc(task.status)}"${options.authed ? ` draggable="true"` : ""}>` +
            `<div class="ds-list-title task-card-title"><a href="#/tasks/${esc(task.id)}">${esc(task.title)}</a></div>` +
            `<p class="ds-list-sub">${taskContextLine(task, options)}</p>` +
            `${taskMoveControlHtml(task, options.authed)}</li>`,
        )
        .join("");
      return `<section class="task-col" data-column="${column}" aria-label="${esc(label)}, ${cards.length} tâche(s)">` +
        `<h3 class="task-col-title">${esc(label)} <span class="ds-list-sub">(${cards.length})</span></h3>` +
        (items === "" ? `<p class="ds-list-sub">Aucune tâche ici.</p>` : `<ul class="task-col-list">${items}</ul>`) +
        `</section>`;
    }).join("") +
    `</div>`;
}

/** Corps de la modale de création : projet, titre, description. */
export function taskCreateFormHtml(
  projectId: string | undefined,
  projects: Project[],
  scopeLabel: string,
): string {
  const projectField =
    projectId !== undefined
      ? `<p class="ds-list-sub">Projet : ${esc(scopeLabel)}</p>`
      : `<div>${dsField("task-project", "Projet", `<select class="ds-select" id="FIELD" name="project_id" required>${projects.map((project) => `<option value="${esc(project.id)}">${esc(project.name)} (${esc(project.slug)})</option>`).join("")}</select>`, "La tâche sera créée dans ce projet.")}</div>`;
  return `<form id="task-create-form" novalidate>` +
    projectField +
    dsField("task-title", "Titre", `<input class="ds-input" id="FIELD" name="title" required autocomplete="off" />`) +
    dsField(
      "task-desc",
      "Description (facultative)",
      `<textarea class="ds-textarea" id="FIELD" name="description" rows="3"></textarea>`,
    ) +
    `<p class="ds-list-sub">Un envoi répété ne crée pas de doublon.</p>` +
    `<div class="ds-field-error" id="task-create-error" role="alert" hidden></div>` +
    `<div class="ds-dialog-actions"><button class="ds-btn" type="button" data-ds-close>Annuler</button>` +
    `<button class="ds-btn ds-btn--primary" type="submit" id="task-create-submit">Créer la tâche</button></div>` +
    `</form>`;
}

export interface TasksPageData {
  tasks: Task[];
  state: TasksPageState;
  limit: number;
  exhausted: boolean;
  authed: boolean;
  scopeLabel: string;
  headingLevel?: 1 | 2;
  projectId?: string;
  projects: Project[];
  projectNames: Record<string, string>;
  msg: TasksPageMessage;
}

export function tasksPageHtml(data: TasksPageData): string {
  const visible = filterTasks(data.tasks, data.state, data.projectNames);
  const showProject = data.projectId === undefined;
  const options: TasksRenderOptions = { authed: data.authed, showProject, projectNames: data.projectNames };
  const header = tasksHeaderHtml(data.scopeLabel, data.authed, data.headingLevel ?? 1);
  const toolbar = tasksToolbarHtml(data.state, visible.length, data.tasks.length);
  let body: string;
  if (data.tasks.length === 0) {
    body = dsEmptyState(
      "Aucune tâche",
      data.projectId === undefined
        ? "Créez votre première tâche pour commencer à travailler."
        : "Ce projet ne contient aucune tâche pour le moment.",
    );
  } else if (visible.length === 0) {
    body =
      dsEmptyState(
        "Aucune tâche ne correspond aux filtres",
        "Modifiez ou réinitialisez les filtres pour retrouver vos tâches déjà chargées.",
      ) + `<p><button class="ds-btn" type="button" data-reset>Réinitialiser les filtres</button></p>`;
  } else {
    body = data.state.view === "list" ? tasksListHtml(visible, options) : tasksBoardHtml(visible, options);
  }
  const more = data.exhausted
    ? `<p class="ds-list-sub">Toutes les tâches chargées.</p>`
    : `<button class="ds-btn" type="button" data-more>Afficher plus</button>`;
  const footer =
    `<div class="tasks-footer"><button class="ds-btn ds-btn--ghost" type="button" data-reload>Actualiser</button>${more}` +
    `<p class="ds-list-sub">Chargement par pages de ${TASK_PAGE_LIMIT} — les filtres s'appliquent aux tâches chargées, dans l'ordre du serveur.</p></div>`;
  const msg =
    data.msg.human === ""
      ? `<div data-msg class="ds-list-sub" role="status" aria-live="polite"></div>`
      : `<div data-msg class="ds-list-sub" role="status" aria-live="polite">${esc(data.msg.human)}${data.msg.technical === undefined || data.msg.technical === "" ? "" : ` <span class="tasks-msg-tech">${esc(data.msg.technical)}</span>`}</div>`;
  const readonlyNote = data.authed
    ? ""
    : `<p class="ds-list-sub">Lecture seule : connectez-vous pour déplacer les cartes, modifier ou créer des tâches.</p>`;
  const modal = data.authed
    ? dsModalHtml({ id: "task-create-dialog", title: "Nouvelle tâche", body: taskCreateFormHtml(data.projectId, data.projects, data.scopeLabel) })
    : "";
  const boardHint =
    data.state.view === "board" && data.authed
      ? `<p class="ds-list-sub">Glissez une carte vers une colonne pour changer son statut — ou utilisez « Déplacer vers… » au clavier.</p>`
      : "";
  return `<div class="tasks">${header}${toolbar}${readonlyNote}${boardHint}${body}${footer}${msg}${modal}</div>`;
}

export async function renderTasksInto(root: HTMLElement, ctx: TasksContext): Promise<void> {
  const headingLevel = ctx.headingLevel ?? 1;
  root.innerHTML = tasksLoadingHtml(ctx.scopeLabel, headingLevel);
  const state = initialTasksState();
  let limit = TASK_PAGE_LIMIT;
  let tasks: Task[] = [];
  let exhausted = false;
  let projects: Project[] = [];
  let projectNames: Record<string, string> = {};
  let msg: TasksPageMessage = { human: "" };
  let painted = false;
  let movePending = false;
  let createPending = false;

  const reload = async (keepMsg?: TasksPageMessage): Promise<void> => {
    if (painted) paint(keepMsg ?? { human: "" });
    if (ctx.projectId === undefined) {
      projects = await loadProjects(ctx);
      projectNames = Object.fromEntries(projects.map((project) => [project.id, project.name]));
    }
    try {
      tasks = await listTasks(ctx.client, { projectId: ctx.projectId, limit, offset: 0 });
      exhausted = tasks.length < limit;
      msg = keepMsg ?? { human: "" };
      paint();
    } catch (error) {
      root.innerHTML =
        `${tasksHeaderHtml(ctx.scopeLabel, false, headingLevel)}` +
        `<div class="ds-notice ds-notice--danger" role="alert"><strong>Tâches indisponibles.</strong> ${esc(describeError(error))} <button class="ds-btn ds-btn--sm" type="button" data-reload>Réessayer</button></div>`;
      root.querySelector("[data-reload]")?.addEventListener("click", () => {
        limit = TASK_PAGE_LIMIT;
        void reload();
      });
    }
    movePending = false;
  };

  const paint = (nextMsg?: TasksPageMessage, focusSelector?: string): void => {
    if (nextMsg !== undefined) msg = nextMsg;
    const existingDialog = root.querySelector<HTMLElement>("#task-create-dialog");
    existingDialog?.remove();
    root.innerHTML = tasksPageHtml({
      tasks,
      state,
      limit,
      exhausted,
      authed: ctx.authed,
      scopeLabel: ctx.scopeLabel,
      headingLevel,
      projectId: ctx.projectId,
      projects,
      projectNames,
      msg,
    });
    if (existingDialog !== null) {
      root.querySelector("#task-create-dialog")?.remove();
      root.querySelector(".tasks")?.append(existingDialog);
    }
    bind();
    painted = true;
    if (focusSelector !== undefined) {
      const target = root.querySelector<HTMLElement>(focusSelector);
      if (target !== null) {
        target.focus();
        if (target instanceof HTMLInputElement && target.type === "search") {
          target.setSelectionRange(target.value.length, target.value.length);
        }
      }
    }
  };

  const setMsg = (message: TasksPageMessage): void => {
    msg = message;
    const node = root.querySelector("[data-msg]");
    if (node === null) return;
    node.innerHTML =
      message.human === ""
        ? ""
        : `${esc(message.human)}${message.technical === undefined || message.technical === "" ? "" : ` <span class="tasks-msg-tech">${esc(message.technical)}</span>`}`;
  };

  const findTask = (id: string): Task | undefined => tasks.find((task) => task.id === id);

  const move = (id: string, version: number, next: TaskStatus, current: TaskStatus): void => {
    if (movePending) return;
    const title = findTask(id)?.title ?? id.slice(0, 8);
    if (next === current) {
      setMsg({ human: `« ${title} » est déjà « ${taskStatusLabel(next)} » — aucune modification.` });
      return;
    }
    movePending = true;
    setMsg({ human: `Déplacement de « ${title} » vers « ${taskStatusLabel(next)} »…` });
    patchTask(ctx.client, id, { status: next }, version)
      .then(() => reload({ human: `« ${title} » déplacée vers « ${taskStatusLabel(next)} ».` }))
      .catch((error: unknown) => {
        // Pas de retry automatique : on relit la vérité serveur, l'utilisateur réessaie consciemment.
        // Le message survit à la relecture (reload(keepMsg)).
        if (error instanceof ApiError && error.errorCode === "version_conflict") {
          void reload({
            human: "Cette tâche a changé ailleurs. Les données ont été actualisées — vérifiez puis réessayez.",
            technical: describeError(error),
          });
        } else {
          void reload({ human: "Déplacement impossible.", technical: describeError(error) });
        }
      });
  };

  const setCreateError = (message: string): void => {
    const node = root.querySelector("#task-create-error");
    if (node === null) return;
    if (message === "") {
      node.setAttribute("hidden", "");
      node.textContent = "";
    } else {
      node.removeAttribute("hidden");
      node.textContent = message;
      if (node instanceof HTMLElement) focusDsErrorBox(node);
    }
  };

  const bind = (): void => {
    root.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => {
      button.addEventListener("click", () => {
        state.view = (button.dataset["view"] ?? "list") as TasksView;
        paint(undefined, `[data-view="${state.view}"]`);
      });
    });
    const search = root.querySelector<HTMLInputElement>("#tasks-search");
    search?.addEventListener("input", () => {
      state.query = search.value;
      paint(undefined, "#tasks-search");
    });
    root.querySelector<HTMLSelectElement>("#tasks-status")?.addEventListener("change", (event) => {
      state.filter = (event.target as HTMLSelectElement).value as TasksStatusFilter;
      paint(undefined, "#tasks-status");
    });
    root.querySelectorAll("[data-reset]").forEach((button) => {
      button.addEventListener("click", () => {
        state.filter = "all";
        state.query = "";
        paint(undefined, "#tasks-search");
      });
    });
    root.querySelector("[data-reload]")?.addEventListener("click", () => {
      limit = TASK_PAGE_LIMIT;
      void reload();
    });
    root.querySelector("[data-more]")?.addEventListener("click", () => {
      limit += TASK_PAGE_LIMIT;
      void reload();
    });
    root.querySelectorAll("[data-move]").forEach((button) => {
      button.addEventListener("click", () => {
        const element = button as HTMLElement;
        const id = element.dataset["move"] ?? "";
        const version = Number(element.dataset["version"] ?? "0");
        const card = element.closest<HTMLElement>("[data-card], .task-row");
        const select = card?.querySelector<HTMLSelectElement>("select[data-status]") ?? null;
        const next = (select?.value ?? "") as TaskStatus;
        const current = (findTask(id)?.status ?? "") as TaskStatus;
        if (next === current) {
          move(id, version, next, current);
          return;
        }
        (button as HTMLButtonElement).disabled = true;
        move(id, version, next, current);
      });
    });
    bindDragAndDrop(root, move);
    const resetCreateForm = (): void => {
      createPending = false;
      root.querySelector<HTMLFormElement>("#task-create-form")?.reset();
      setCreateError("");
      const submit = root.querySelector<HTMLButtonElement>("#task-create-submit");
      if (submit !== null) {
        submit.disabled = false;
        submit.classList.remove("ds-btn--loading");
        submit.textContent = "Créer la tâche";
      }
    };
    const openButton = root.querySelector<HTMLElement>("#task-new");
    openButton?.addEventListener("click", () => {
      resetCreateForm();
      openDsDialog(root, "task-create-dialog", openButton);
      root.querySelector<HTMLElement>("#task-title")?.focus();
    });
    const form = root.querySelector<HTMLFormElement>("#task-create-form");
    if (form !== null && form.dataset["bound"] !== "yes") {
      form.dataset["bound"] = "yes";
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (createPending) return;
        const data = new FormData(form);
        const projectId = ctx.projectId ?? String(data.get("project_id") ?? "");
        const title = String(data.get("title") ?? "").trim();
        if (!isUuid(projectId)) {
          setCreateError("Un projet est nécessaire pour créer une tâche.");
          root.querySelector<HTMLElement>("#task-project")?.focus();
          return;
        }
        if (title === "") {
          setCreateError("Le titre est obligatoire.");
          root.querySelector<HTMLElement>("#task-title")?.focus();
          return;
        }
        createPending = true;
        const submit = root.querySelector<HTMLButtonElement>("#task-create-submit");
        if (submit !== null) {
          submit.disabled = true;
          submit.classList.add("ds-btn--loading");
          submit.textContent = "Création en cours…";
        }
        setCreateError("");
        const description = String(data.get("description") ?? "").trim();
        // Clé fraîche par tentative logique : la double soumission est empêchée
        // par le bouton désactivé, une nouvelle tentative après erreur rejoue
        // un corps identique sous une clé neuve.
        createTask(
          ctx.client,
          { project_id: projectId, title, description: description === "" ? null : description },
          newIdempotencyKey(),
        )
          .then((created) => {
            closeDsDialog(root, "task-create-dialog");
            dsNotify(`Tâche « ${created.title} » créée.`, "success");
            // Le rechargement remplace le déclencheur : le refocaliser après,
            // jamais <body> sans raison.
            void reload().then(() => {
              root.querySelector<HTMLElement>("#task-new")?.focus();
            });
          })
          .catch((error: unknown) => {
            createPending = false;
            setCreateError(describeError(error));
            if (submit !== null) {
              submit.disabled = false;
              submit.classList.remove("ds-btn--loading");
              submit.textContent = "Créer la tâche";
            }
          });
      });
    }
  };

  await reload();
}

export function bindDragAndDrop(
  root: HTMLElement,
  move: (id: string, version: number, status: TaskStatus, current: TaskStatus) => void,
): void {
  root.querySelectorAll<HTMLElement>("[data-card]").forEach((card) => {
    card.addEventListener("dragstart", (event) => {
      const id = card.dataset["card"] ?? "";
      event.dataTransfer?.setData("text/plain", id);
      if (event.dataTransfer !== null) event.dataTransfer.effectAllowed = "move";
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));
  });
  root.querySelectorAll<HTMLElement>("[data-column]").forEach((column) => {
    column.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer !== null) event.dataTransfer.dropEffect = "move";
      column.classList.add("drop-target");
    });
    column.addEventListener("dragleave", () => column.classList.remove("drop-target"));
    column.addEventListener("drop", (event) => {
      event.preventDefault();
      column.classList.remove("drop-target");
      const dragged = event.dataTransfer?.getData("text/plain") ?? "";
      const card = root.querySelector<HTMLElement>(`[data-card="${CSS.escape(dragged)}"]`);
      if (dragged === "" || card === null) return;
      const columnName = column.dataset["column"];
      if (!TASK_COLUMNS.includes(columnName as (typeof TASK_COLUMNS)[number])) return;
      const version = Number(card.dataset["version"] ?? "0");
      const current = (card.dataset["statusCurrent"] ?? "") as TaskStatus;
      move(dragged, version, columnToStatus(columnName as (typeof TASK_COLUMNS)[number]), current);
    });
  });
}

async function loadProjects(ctx: TasksContext): Promise<Project[]> {
  const result = await ctx.client.GET("/api/v1/projects");
  return result.response.ok && result.data !== undefined ? result.data : [];
}
