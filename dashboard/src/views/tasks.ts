/**
 * DASH-2/DASH-5 — Tasks list + Kanban.
 *
 * - Source: GET /api/v1/tasks?project_id&limit&offset (real pagination;
 *   no server total/status-filter/sort/search — extras are client-side).
 * - Kanban columns mirror the canonical statuses 1:1; `blocked` is never
 *   merged into `in_progress`.
 * - DASH-5 drag & drop: dropping a card on a column calls
 *   PATCH /tasks/{id} {status} + If-Match-Version (the version last read),
 *   then a server refetch. Never an optimistic reorder: a 409 re-reads the
 *   server truth and says so. The explicit per-card <select>+Move control is
 *   kept as the accessible fallback.
 * - DASH-5 create: POST /tasks with a fresh Idempotency-Key, then refetch.
 */
import type { StudioClient } from "../api";
import { listTasks, patchTask, TASK_PAGE_LIMIT, type Task } from "../tasksApi";
import { createTask, isUuid, type Project } from "../creationsApi";
import { selectTask } from "../store";
import { columnToStatus, statusColumn, TASK_COLUMNS } from "../taskStatus";
import { describeError, esc, idCell, section, statusBlock } from "../ui";

export interface TasksContext {
  client: StudioClient;
  authed: boolean;
  projectId?: string;
  scopeLabel: string;
}

type StatusFilter = "all" | "created" | "in_progress" | "blocked" | "completed";

const STATUSES = ["created", "in_progress", "blocked", "completed"] as const;

function visibleTasks(tasks: Task[], filter: StatusFilter): Task[] {
  return filter === "all" ? tasks : tasks.filter((t) => t.status === filter);
}

function cardHtml(task: Task, authed: boolean): string {
  const held = task.claimed_by_machine_id !== null && task.claimed_by_machine_id !== undefined;
  const options = STATUSES.map(
    (s) => `<option value="${s}" ${task.status === s ? "selected" : ""}>${s}</option>`,
  ).join("");
  return `<div class="card" data-card="${esc(task.id)}" data-version="${task.version}" data-status-current="${esc(task.status)}" ${authed ? 'draggable="true"' : ""}>
    <div class="title">${esc(task.title)}</div>
    <div class="sub">${idCell(task.id)} · v${task.version} · ${held ? `held ${esc(task.claimed_by_machine_id?.slice(0, 8) ?? "")}…` : "unclaimed"}</div>
    <div class="card-actions">
      <button type="button" data-open="${esc(task.id)}">Open</button>
      <select data-status="${esc(task.id)}" ${authed ? "" : "disabled"} title="Move column (PATCH status)">${options}</select>
      <button type="button" data-move="${esc(task.id)}" data-version="${task.version}" ${authed ? "" : "disabled"}>Move</button>
    </div></div>`;
}

function createFormHtml(authed: boolean, projectId: string | undefined, projects: Project[]): string {
  const projectField =
    projectId !== undefined
      ? `<span class="meta">project ${esc(projectId)}</span>`
      : `<label>Project <select name="project_id" required ${authed ? "" : "disabled"}>${projects
          .map((p) => `<option value="${esc(p.id)}">${esc(p.name)} (${esc(p.slug)})</option>`)
          .join("")}</select></label>`;
  return `<form data-create class="inline-form"><h3>New task</h3>
    ${projectField}
    <label>Title <input name="title" required ${authed ? "" : "disabled"} /></label>
    <label>Description <input name="description" ${authed ? "" : "disabled"} /></label>
    <button type="submit" ${authed ? "" : "disabled"}>Create</button>
    <span class="meta">POST /tasks · Idempotency-Key per attempt</span>
    <div data-create-msg class="meta"></div></form>`;
}

export async function renderTasksInto(root: HTMLElement, ctx: TasksContext): Promise<void> {
  let limit = TASK_PAGE_LIMIT;
  let filter: StatusFilter = "all";
  let tasks: Task[] = [];
  let exhausted = false;
  let projects: Project[] = ctx.projectId === undefined ? await loadProjects(ctx) : [];

  const reload = async (): Promise<void> => {
    paint(statusBlock("loading"));
    if (ctx.projectId === undefined && projects.length === 0) projects = await loadProjects(ctx);
    try {
      tasks = await listTasks(ctx.client, { projectId: ctx.projectId, limit, offset: 0 });
      exhausted = tasks.length < limit;
      paint("");
    } catch (error) {
      paint(statusBlock("error", describeError(error)));
    }
  };

  const paint = (inner: string): void => {
    if (inner !== "") {
      root.innerHTML = section("Tasks", meta(), inner);
      return;
    }
    const visible = visibleTasks(tasks, filter);
    const groups: Record<string, Task[]> = { TODO: [], "IN PROGRESS": [], BLOCKED: [], DONE: [] };
    for (const task of visible) {
      const column = statusColumn(task.status);
      if (column !== "UNKNOWN") groups[column]?.push(task);
    }
    const filterOptions = [`<option value="all">all (client-side)</option>`]
      .concat(STATUSES.map((s) => `<option value="${s}" ${filter === s ? "selected" : ""}>${s}</option>`))
      .join("");
    const columns = TASK_COLUMNS.map(
      (column) =>
        `<div class="col" data-column="${column}"><h3>${column} (${groups[column]?.length ?? 0})</h3>${(groups[column] ?? []).map((t) => cardHtml(t, ctx.authed)).join("")}</div>`,
    ).join("");
    root.innerHTML = section(
      "Tasks",
      meta(),
      `${ctx.authed ? "" : `<div class="state empty">Read-only: set a token to move cards or open editing.</div>`}
       <div class="row"><label>Status filter <select data-filter>${filterOptions}</select></label>
       <button type="button" data-reload>Reload</button>
       ${exhausted ? `<span class="meta">all loaded</span>` : `<button type="button" data-more>Load more</button>`}
       ${ctx.authed ? `<span class="meta">drag a card onto a column to change its status</span>` : ""}</div>
       <div class="kanban">${columns}</div>${createFormHtml(ctx.authed, ctx.projectId, projects)}<div data-msg class="meta"></div>`,
    );
    bind();
  };

  const meta = (): string =>
    `${ctx.scopeLabel} · GET /tasks · limit ${limit} offset 0 · no server total/filter/sort`;

  const setMsg = (text: string): void => {
    const node = root.querySelector("[data-msg]");
    if (node !== null) node.textContent = text;
  };

  const move = (id: string, version: number, next: Task["status"], current: Task["status"]): void => {
    if (next === current) {
      setMsg(`Already ${next} — no change.`);
      return;
    }
    setMsg(`Moving ${id.slice(0, 8)}… → ${next}`);
    patchTask(ctx.client, id, { status: next }, version)
      .then(() => reload())
      .catch((error: unknown) => {
        setMsg(describeError(error));
        void reload();
      });
  };

  const bind = (): void => {
    root.querySelector("[data-filter]")?.addEventListener("change", (event) => {
      filter = (event.target as HTMLSelectElement).value as StatusFilter;
      paint("");
    });
    root.querySelector("[data-reload]")?.addEventListener("click", () => {
      limit = TASK_PAGE_LIMIT;
      void reload();
    });
    root.querySelector("[data-more]")?.addEventListener("click", () => {
      limit += TASK_PAGE_LIMIT;
      void reload();
    });
    root.querySelectorAll("[data-open]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = (button as HTMLElement).dataset["open"] ?? "";
        selectTask(id);
        location.hash = `#/tasks/${id}`;
      });
    });
    root.querySelectorAll("[data-move]").forEach((button) => {
      button.addEventListener("click", () => {
        const element = button as HTMLElement;
        const id = element.dataset["move"] ?? "";
        const version = Number(element.dataset["version"] ?? "0");
        const select = root.querySelector<HTMLSelectElement>(`[data-card="${CSS.escape(id)}"] select[data-status]`);
        const next = (select?.value ?? "") as Task["status"];
        const current = (element.closest<HTMLElement>("[data-card]")?.dataset["statusCurrent"] ?? "") as Task["status"];
        (button as HTMLButtonElement).disabled = true;
        move(id, version, next, current);
      });
    });
    bindDragAndDrop(root, move);
    const form = root.querySelector<HTMLFormElement>("[data-create]");
    form?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const projectId = ctx.projectId ?? String(data.get("project_id") ?? "");
      const msg = form.querySelector("[data-create-msg]");
      const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
      if (!isUuid(projectId)) {
        if (msg !== null) msg.textContent = "A project is required to create a task.";
        return;
      }
      if (submit !== null) submit.disabled = true;
      const description = String(data.get("description") ?? "").trim();
      createTask(ctx.client, {
        project_id: projectId,
        title: String(data.get("title") ?? ""),
        description: description === "" ? null : description,
      })
        .then((created) => {
          if (msg !== null) msg.textContent = `Created ${created.readable_id ?? created.id}.`;
          void reload();
        })
        .catch((error: unknown) => {
          if (msg !== null) msg.textContent = describeError(error);
          if (submit !== null) submit.disabled = false;
        });
    });
  };

  await reload();
}

export function bindDragAndDrop(
  root: HTMLElement,
  move: (id: string, version: number, status: Task["status"], current: Task["status"]) => void,
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
      if (columnName !== "TODO" && columnName !== "IN PROGRESS" && columnName !== "BLOCKED" && columnName !== "DONE") return;
      const version = Number(card.dataset["version"] ?? "0");
      const current = (card.dataset["statusCurrent"] ?? "") as Task["status"];
      move(dragged, version, columnToStatus(columnName), current);
    });
  });
}

async function loadProjects(ctx: TasksContext): Promise<Project[]> {
  const result = await ctx.client.GET("/api/v1/projects");
  return result.response.ok && result.data !== undefined ? result.data : [];
}
