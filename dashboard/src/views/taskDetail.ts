/**
 * DASH-2 — Task detail.
 *
 * - Truth: GET /api/v1/tasks/{id}. Complements (read-only):
 *   GET /sessions?task_id, GET /ai-work?task_id, GET /claims?project_id
 *   (client-filtered on task_id). `sessions.machine_id` is NOT validated
 *   server-side — displayed as informational only, never as identity.
 * - Edit: PATCH {title?, description?, status?} + the displayed
 *   If-Match-Version. 409 version_conflict → banner with server_version,
 *   immediate re-read, NO automatic retry: the user re-applies consciously.
 * - Claim: POST .../claim (caller's machine, agent None, status becomes
 *   in_progress, 409 already_claimed). Release: POST .../release
 *   (holder-or-admin; status is NOT reset — server rule, stated in UI).
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { claimTask, getTask, patchTask, releaseTask, type Task } from "../tasksApi";
import { describeError, esc, fmtTime, idCell, section, statusBlock } from "../ui";

export interface TaskDetailContext {
  client: StudioClient;
  authed: boolean;
}

interface SessionRow {
  id: string;
  machine_id: string;
  agent_id?: string | null;
  started_at: string;
  ended_at?: string | null;
}

interface WorkRow {
  id: string;
  summary: string;
  status: string;
  started_at: string;
}

async function fetchJson<T>(client: StudioClient, path: "/api/v1/sessions" | "/api/v1/ai-work" | "/api/v1/claims", query: Record<string, string>): Promise<T> {
  const result = await client.GET(path, { params: { query } });
  if (result.response.ok && result.data !== undefined) return result.data as T;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

const STATUSES = ["created", "in_progress", "blocked", "completed"] as const;

export async function renderTaskDetail(root: HTMLElement, ctx: TaskDetailContext, taskId: string): Promise<void> {
  root.innerHTML = section("Task", `GET /tasks/${taskId}`, statusBlock("loading"));
  let task: Task;
  try {
    task = await getTask(ctx.client, taskId);
  } catch (error) {
    root.innerHTML = section("Task", `GET /tasks/${taskId}`, statusBlock("error", describeError(error)));
    return;
  }

  let sessions: SessionRow[] = [];
  let worklogs: WorkRow[] = [];
  let taskClaims = 0;
  try {
    const [s, w, c] = await Promise.all([
      fetchJson<SessionRow[]>(ctx.client, "/api/v1/sessions", { task_id: task.id }),
      fetchJson<WorkRow[]>(ctx.client, "/api/v1/ai-work", { task_id: task.id }),
      fetchJson<{ id: string; task_id?: string | null }[]>(ctx.client, "/api/v1/claims", { project_id: task.project_id }),
    ]);
    sessions = s;
    worklogs = w;
    taskClaims = c.filter((claim) => claim.task_id === task.id).length;
  } catch {
    // Complements are best-effort; the task itself is the truth.
  }

  paint(root, ctx, task, sessions, worklogs, taskClaims, "");
}

function paint(
  root: HTMLElement,
  ctx: TaskDetailContext,
  task: Task,
  sessions: SessionRow[],
  worklogs: WorkRow[],
  taskClaims: number,
  notice: string,
): void {
  const held = task.claimed_by_machine_id !== null && task.claimed_by_machine_id !== undefined;
  const statusOptions = STATUSES.map((s) => `<option value="${s}" ${task.status === s ? "selected" : ""}>${s}</option>`).join("");
  const sessionRows =
    sessions.length === 0
      ? statusBlock("empty", "No sessions for this task.")
      : `<table><thead><tr><th>ID</th><th>Machine (unvalidated)</th><th>Agent</th><th>Started</th><th>Ended</th></tr></thead><tbody>${sessions
          .map(
            (s) =>
              `<tr><td>${idCell(s.id)}</td><td>${idCell(s.machine_id)} <span class="tag">unvalidated</span></td><td>${idCell(s.agent_id)}</td><td>${fmtTime(s.started_at)}</td><td>${fmtTime(s.ended_at)}</td></tr>`,
          )
          .join("")}</tbody></table>`;
  const workRows =
    worklogs.length === 0
      ? statusBlock("empty", "No AI work logged for this task.")
      : `<table><thead><tr><th>Summary</th><th>Status</th><th>Started</th></tr></thead><tbody>${worklogs
          .map((w) => `<tr><td>${esc(w.summary.length > 90 ? `${w.summary.slice(0, 90)}…` : w.summary)}</td><td>${esc(w.status)}</td><td>${fmtTime(w.started_at)}</td></tr>`)
          .join("")}</tbody></table>`;

  root.innerHTML = section(
    `Task · ${task.title}`,
    `GET /tasks/{id} · v${task.version} · ${task.status}`,
    `${notice === "" ? "" : `<div class="state ${notice.startsWith("Conflict") ? "error" : ""}">${esc(notice)}</div>`}
    <div class="detail-grid">
      <div>${idCell(task.id)} · project ${idCell(task.project_id)}${task.readable_id ? ` · <code class="mono">${esc(task.readable_id)}</code>` : ""}</div>
      <div>Claim: ${held ? `held by <code class="mono">${esc(task.claimed_by_machine_id ?? "")}</code>` : "unclaimed"}</div>
    </div>
    <form data-edit class="stack-form"><h3>Edit (PATCH + If-Match-Version ${task.version})</h3>
      <label>Title <input name="title" value="${esc(task.title)}" required ${ctx.authed ? "" : "disabled"} /></label>
      <label>Description <textarea name="description" rows="3" ${ctx.authed ? "" : "disabled"}>${esc(task.description ?? "")}</textarea></label>
      <label>Status <select name="status" ${ctx.authed ? "" : "disabled"}>${statusOptions}</select></label>
      <button type="submit" ${ctx.authed ? "" : "disabled"}>Save</button>
      ${ctx.authed ? "" : `<span class="meta">Read-only: set a token to edit.</span>`}
    </form>
    <div class="row"><h3>Task claim</h3>
      <button type="button" data-claim ${ctx.authed ? "" : "disabled"}>Claim for my machine</button>
      <button type="button" data-release ${ctx.authed ? "" : "disabled"}>Release</button>
      <span class="meta">claim sets status in_progress · release keeps status (server rule)</span></div>
    <div data-msg class="meta"></div>
    <h3>Sessions (${sessions.length})</h3>${sessionRows}
    <h3>AI work (${worklogs.length})</h3>${workRows}
    <h3>Resource claims on this task: ${taskClaims} (see project Claims)</h3>`,
  );
  bind(root, ctx, task);
}

function setMsg(root: HTMLElement, text: string): void {
  const node = root.querySelector("[data-msg]");
  if (node !== null) node.textContent = text;
}

function bind(root: HTMLElement, ctx: TaskDetailContext, task: Task): void {
  const form = root.querySelector<HTMLFormElement>("[data-edit]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit !== null) submit.disabled = true;
    patchTask(ctx.client, task.id, {
      title: String(data.get("title") ?? ""),
      description: String(data.get("description") ?? "") === "" ? null : String(data.get("description") ?? ""),
      status: String(data.get("status") ?? task.status) as Task["status"],
    }, task.version)
      .then(() => {
        void importSessionsWork(root, ctx, task.id);
      })
      .catch((error: unknown) => {
        if (submit !== null) submit.disabled = false;
        if (error instanceof ApiError && error.errorCode === "version_conflict") {
          // No auto-retry: re-read server truth, user re-applies consciously.
          getTask(ctx.client, task.id).then(
            (fresh) => {
              paint(root, ctx, fresh, [], [], 0, `Conflict: task changed on the server (now v${fresh.version}). Server values loaded — review and re-apply your change.`);
              void importSessionsWork(root, ctx, fresh.id);
            },
            (reloadError: unknown) => setMsg(root, `Conflict (server v${error.serverVersion ?? "?"}), re-read failed: ${describeError(reloadError)}`),
          );
        } else {
          setMsg(root, describeError(error));
        }
      });
  });

  root.querySelector("[data-claim]")?.addEventListener("click", (event) => {
    (event.target as HTMLButtonElement).disabled = true;
    claimTask(ctx.client, task.id).then(
      () => {
        void importSessionsWork(root, ctx, task.id);
      },
      (error: unknown) => {
        (event.target as HTMLButtonElement).disabled = false;
        setMsg(root, describeError(error));
      },
    );
  });

  root.querySelector("[data-release]")?.addEventListener("click", (event) => {
    (event.target as HTMLButtonElement).disabled = true;
    releaseTask(ctx.client, task.id).then(
      () => {
        getTask(ctx.client, task.id).then(
          (fresh) => {
            paint(root, ctx, fresh, [], [], 0, "");
            setMsg(root, "Released. Status unchanged (server rule) — change it explicitly if needed.");
            void importSessionsWork(root, ctx, fresh.id);
          },
          (error: unknown) => setMsg(root, describeError(error)),
        );
      },
      (error: unknown) => {
        (event.target as HTMLButtonElement).disabled = false;
        setMsg(root, describeError(error));
      },
    );
  });
}

async function importSessionsWork(root: HTMLElement, ctx: TaskDetailContext, taskId: string): Promise<void> {
  let fresh: Task;
  try {
    fresh = await getTask(ctx.client, taskId);
  } catch (error) {
    setMsg(root, describeError(error));
    return;
  }
  try {
    const [sessions, worklogs, claims] = await Promise.all([
      fetchJson<SessionRow[]>(ctx.client, "/api/v1/sessions", { task_id: fresh.id }),
      fetchJson<WorkRow[]>(ctx.client, "/api/v1/ai-work", { task_id: fresh.id }),
      fetchJson<{ id: string; task_id?: string | null }[]>(ctx.client, "/api/v1/claims", { project_id: fresh.project_id }),
    ]);
    paint(root, ctx, fresh, sessions, worklogs, claims.filter((c) => c.task_id === fresh.id).length, "");
  } catch {
    paint(root, ctx, fresh, [], [], 0, "");
  }
}
