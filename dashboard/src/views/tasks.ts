/**
 * DASH-2 — Tasks list + Kanban.
 *
 * - Source: GET /api/v1/tasks?project_id&limit&offset (real pagination;
 *   no server total/status-filter/sort/search — extras are client-side).
 * - Kanban columns mirror the canonical statuses 1:1; `blocked` is never
 *   merged into `in_progress`.
 * - No drag & drop (deliberate): column moves go through an explicit
 *   status control per card (accessible, reliable), each emitting
 *   PATCH {status} + If-Match-Version, followed by a server refetch.
 *   No irreversible optimistic update; 409 keeps server truth on screen.
 */
import type { StudioClient } from "../api";
import { listTasks, patchTask, TASK_PAGE_LIMIT, type Task } from "../tasksApi";
import { selectTask } from "../store";
import { TASK_COLUMNS, statusColumn } from "../taskStatus";
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
  return `<div class="card" data-card="${esc(task.id)}">
    <div class="title">${esc(task.title)}</div>
    <div class="sub">${idCell(task.id)} · v${task.version} · ${held ? `held ${esc(task.claimed_by_machine_id?.slice(0, 8) ?? "")}…` : "unclaimed"}</div>
    <div class="card-actions">
      <button type="button" data-open="${esc(task.id)}">Open</button>
      <select data-status="${esc(task.id)}" ${authed ? "" : "disabled"} title="Move column (PATCH status)">${options}</select>
      <button type="button" data-move="${esc(task.id)}" data-version="${task.version}" ${authed ? "" : "disabled"}>Move</button>
    </div></div>`;
}

export async function renderTasksInto(root: HTMLElement, ctx: TasksContext): Promise<void> {
  let limit = TASK_PAGE_LIMIT;
  let filter: StatusFilter = "all";
  let tasks: Task[] = [];
  let exhausted = false;

  const reload = async (): Promise<void> => {
    paint(statusBlock("loading"));
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
        `<div class="col"><h3>${column} (${groups[column]?.length ?? 0})</h3>${(groups[column] ?? []).map((t) => cardHtml(t, ctx.authed)).join("")}</div>`,
    ).join("");
    root.innerHTML = section(
      "Tasks",
      meta(),
      `${ctx.authed ? "" : `<div class="state empty">Read-only: set a token to move cards or open editing.</div>`}
       <div class="row"><label>Status filter <select data-filter>${filterOptions}</select></label>
       <button type="button" data-reload>Reload</button>
       ${exhausted ? `<span class="meta">all loaded</span>` : `<button type="button" data-more>Load more</button>`}</div>
       <div class="kanban">${columns}</div><div data-msg class="meta"></div>`,
    );
    bind();
  };

  const meta = (): string =>
    `${ctx.scopeLabel} · GET /tasks · limit ${limit} offset 0 · no server total/filter/sort`;

  const setMsg = (text: string): void => {
    const node = root.querySelector("[data-msg]");
    if (node !== null) node.textContent = text;
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
        const select = root.querySelector<HTMLSelectElement>(`[data-status="${CSS.escape(id)}"]`);
        const next = (select?.value ?? "") as Task["status"];
        (button as HTMLButtonElement).disabled = true;
        patchTask(ctx.client, id, { status: next }, version)
          .then(() => reload())
          .catch((error: unknown) => {
            (button as HTMLButtonElement).disabled = false;
            setMsg(describeError(error));
          });
      });
    });
  };

  await reload();
}
