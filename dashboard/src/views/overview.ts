/**
 * DASH-1 — read-only Overview.
 *
 * Data sources (all existing endpoints, no invention):
 * - GET /healthz (no auth)
 * - GET /api/v1/projects
 * - GET /api/v1/projects/{id}/state  (active_tasks, active_claims, generated_at)
 * - GET /api/v1/tasks?limit&offset   (statuses: created/in_progress/blocked/completed)
 * - GET /api/v1/events?limit&since   (last 24h; timeline NOT claimed exhaustive —
 *   most event types still require manual emission)
 * - GET /api/v1/agents               (presence below is Derived, never canonical:
 *   no HTTP read of heartbeats/machines exists yet)
 * - GET /api/v1/review-queue         (DASH-3: AI work review_requested +
 *   decisions proposed + recent resource.conflict, server-aggregated, read-only)
 * - GET /api/v1/transfers            (read-only)
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { joinUrl } from "../config";
import { resolveReview, type ReviewResolution } from "../reviewApi";
import { uiState, selectProject } from "../store";
import { TASK_COLUMNS, statusColumn } from "../taskStatus";
import { describeError, esc, fmtTime, idCell, section, shortId, statusBlock } from "../ui";
import type { components } from "../openapi-schema";

type Project = components["schemas"]["Project"];
type Task = components["schemas"]["Task"];
type Agent = components["schemas"]["Agent"];
type Transfer = components["schemas"]["Transfer"];
type EventEnvelope = components["schemas"]["EventEnvelope"];
type ReviewQueue = components["schemas"]["ReviewQueue"];
type ReviewQueueItem = ReviewQueue["items"][number];

export const OVERVIEW_TASK_LIMIT = 100;
export const OVERVIEW_EVENT_LIMIT = 100;
export const OVERVIEW_TRANSFER_LIMIT = 10;

export function sinceIso24h(now: number = Date.now()): string {
  return new Date(now - 24 * 60 * 60 * 1000).toISOString();
}

const REVIEW_KIND_LABEL: Record<ReviewQueueItem["kind"], string> = {
  ai_work_review: "AI work",
  decision_proposal: "Decision",
  resource_conflict: "Conflict",
};

/** Sub-title for a review-queue row: AI work → agent, decision → readable_id,
 * conflict → resource path. */
export function reviewQueueItemDetail(item: ReviewQueueItem): string {
  switch (item.kind) {
    case "ai_work_review":
      return `agent ${shortId(item.agent_id)}`;
    case "decision_proposal":
      return item.readable_id;
    case "resource_conflict":
      return item.resource_path;
  }
}

export function groupTasksByColumn(tasks: Task[]): Record<string, Task[]> {
  const groups: Record<string, Task[]> = { TODO: [], "IN PROGRESS": [], BLOCKED: [], DONE: [], UNKNOWN: [] };
  for (const task of tasks) {
    const column = statusColumn(task.status);
    groups[column]?.push(task);
  }
  return groups;
}

/** Agent ids observed in recent events → "seen recently" marker (Derived). */
export function agentsSeenInEvents(events: EventEnvelope[]): Set<string> {
  const seen = new Set<string>();
  for (const event of events) {
    if (event.actor_type === "agent" && event.actor_id) seen.add(event.actor_id);
    if (event.machine_id) seen.add(event.machine_id);
  }
  return seen;
}

async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await promise;
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

function errMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.message}${error.errorCode ? ` [${error.errorCode}]` : ""}`;
  return error instanceof Error ? error.message : String(error);
}

export interface OverviewContext {
  client: StudioClient;
  baseUrl: string;
  authed: boolean;
}

export async function renderOverview(root: HTMLElement, ctx: OverviewContext): Promise<void> {
  root.innerHTML = `<div class="state loading">Loading overview…</div>`;
  const health = await checkHealth(ctx.baseUrl);
  const sections: string[] = [healthHtml(health)];
  if (!ctx.authed) {
    sections.push(
      section("Overview", "read-only", statusBlock("empty", "Set a machine token above to load projects, tasks and activity.")),
    );
    root.innerHTML = sections.join("");
    return;
  }
  const [projects, tasks, events, agents, transfers] = await Promise.all([
    settle(unwrap(ctx.client.GET("/api/v1/projects"))),
    settle(unwrap(ctx.client.GET("/api/v1/tasks", { params: { query: { limit: OVERVIEW_TASK_LIMIT, offset: 0 } } }))),
    settle(
      unwrap(
        ctx.client.GET("/api/v1/events", {
          params: { query: { limit: OVERVIEW_EVENT_LIMIT, since: sinceIso24h() } },
        }),
      ),
    ),
    settle(unwrap(ctx.client.GET("/api/v1/agents"))),
    settle(unwrap(ctx.client.GET("/api/v1/transfers"))),
  ]);

  sections.push(projectsHtml(projects));
  const selectedId = pickProject(projects, uiState.selectedProjectId);
  if (selectedId !== null) {
    const state = await settle(unwrap(ctx.client.GET("/api/v1/projects/{project_id}/state", { params: { path: { project_id: selectedId } } })));
    sections.push(projectStateHtml(state, projectsValue(projects, selectedId)));
  }
  const reviewQueue = await settle(
    unwrap(
      ctx.client.GET("/api/v1/review-queue", {
        params: { query: selectedId !== null ? { project_id: selectedId } : {} },
      }),
    ),
  );
  sections.push(tasksHtml(tasks));
  sections.push(activityHtml(events));
  sections.push(agentsHtml(agents, events));
  sections.push(reviewsHtml(reviewQueue, ctx.authed));
  sections.push(transfersHtml(transfers));
  root.innerHTML = sections.join("");
  bindProjectSelect(root);
  bindReviewActions(root, ctx);
}

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown };

async function settle<T>(promise: Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    return { ok: false, error };
  }
}

export interface HealthInfo {
  reachable: boolean;
  message: string;
}

export async function checkHealth(baseUrl: string): Promise<HealthInfo> {
  try {
    const response = await fetch(joinUrl(baseUrl, "/healthz"));
    if (response.ok) return { reachable: true, message: "API reachable" };
    return { reachable: false, message: `API HTTP ${response.status}` };
  } catch {
    return { reachable: false, message: "API unreachable" };
  }
}

function healthHtml(health: HealthInfo): string {
  const cls = health.reachable ? "ok" : "bad";
  return `<div class="health ${cls}"><span class="dot"></span>${esc(health.message)}<span class="meta">GET /healthz · no auth</span></div>`;
}

function projectsValue(settled: Settled<Project[]>, id: string): Project | undefined {
  return settled.ok ? settled.value.find((p) => p.id === id) : undefined;
}

function pickProject(settled: Settled<Project[]>, selected: string | null): string | null {
  if (!settled.ok || settled.value.length === 0) return null;
  if (selected !== null && settled.value.some((p) => p.id === selected)) return selected;
  const first = settled.value[0];
  return first ? first.id : null;
}

function bindProjectSelect(root: HTMLElement): void {
  const select = root.querySelector<HTMLSelectElement>("[data-project-select]");
  if (select === null) return;
  select.addEventListener("change", () => {
    selectProject(select.value === "" ? null : select.value);
  });
}

function projectsHtml(settled: Settled<Project[]>): string {
  if (!settled.ok) return section("Projects", "GET /projects", statusBlock("error", errMessage(settled.error)));
  if (settled.value.length === 0) return section("Projects", "GET /projects", statusBlock("empty", "No projects."));
  const options = settled.value
    .map((p) => `<option value="${esc(p.id)}" ${uiState.selectedProjectId === p.id ? "selected" : ""}>${esc(p.name)} (${esc(p.slug)})</option>`)
    .join("");
  const rows = settled.value
    .map(
      (p) =>
        `<tr><td>${esc(p.name)}</td><td><code class="mono">${esc(p.slug)}</code></td><td>${idCell(p.id)}</td><td>${p.archived ? "archived" : "active"}</td><td>${fmtTime(p.updated_at)}</td></tr>`,
    )
    .join("");
  return section(
    "Projects",
    "GET /projects",
    `<div class="row"><label>Project <select data-project-select>${options}</select></label></div>` +
      `<table><thead><tr><th>Name</th><th>Slug</th><th>ID</th><th>State</th><th>Updated</th></tr></thead><tbody>${rows}</tbody></table>`,
  );
}

function projectStateHtml(
  settled: Settled<components["schemas"]["ProjectState"]>,
  project: Project | undefined,
): string {
  const name = project ? `${project.name} (${project.slug})` : shortId(uiState.selectedProjectId);
  if (!settled.ok) return section(`Project · ${name}`, "GET /state", statusBlock("error", errMessage(settled.error)));
  const tasks = settled.value.active_tasks
    .map((t) => `<tr><td>${esc(t.title)}</td><td>${esc(t.status)}</td><td>${idCell(t.id)}</td></tr>`)
    .join("");
  const claims = settled.value.active_claims
    .map((c) => `<tr><td><code class="mono">${esc(c.resource_path)}</code></td><td>${esc(c.resource_type)}</td><td>${fmtTime(c.expires_at)}</td></tr>`)
    .join("");
  return section(
    `Project · ${name}`,
    `GET /state · generated ${fmtTime(settled.value.generated_at)}`,
    `<h3>Active tasks (${settled.value.active_tasks.length})</h3>` +
      (tasks === "" ? statusBlock("empty", "No active tasks.") : `<table><thead><tr><th>Title</th><th>Status</th><th>ID</th></tr></thead><tbody>${tasks}</tbody></table>`) +
      `<h3>Active claims (${settled.value.active_claims.length})</h3>` +
      (claims === "" ? statusBlock("empty", "No active claims.") : `<table><thead><tr><th>Path</th><th>Type</th><th>Expires</th></tr></thead><tbody>${claims}</tbody></table>`),
  );
}

function tasksHtml(settled: Settled<Task[]>): string {
  if (!settled.ok) return section("Active tasks", "GET /tasks", statusBlock("error", errMessage(settled.error)));
  const visible = settled.value.filter((t) => t.status !== "completed");
  if (visible.length === 0) return section("Active tasks", "GET /tasks", statusBlock("empty", "No active tasks."));
  const groups = groupTasksByColumn(visible);
  const columns = TASK_COLUMNS.map(
    (column) =>
      `<div class="col"><h3>${column} (${groups[column]?.length ?? 0})</h3>${(groups[column] ?? [])
        .map((t) => `<div class="card"><div class="title">${esc(t.title)}</div><div class="sub">${idCell(t.id)} · v${t.version}</div></div>`)
        .join("")}</div>`,
  ).join("");
  return section("Active tasks", `GET /tasks · limit ${OVERVIEW_TASK_LIMIT} · completed hidden`, `<div class="kanban">${columns}</div>`);
}

function activityHtml(settled: Settled<EventEnvelope[]>): string {
  if (!settled.ok) return section("Recent activity", "GET /events", statusBlock("error", errMessage(settled.error)));
  if (settled.value.length === 0)
    return section("Recent activity", "GET /events · 24h", statusBlock("empty", "No events in the last 24h."));
  const rows = settled.value
    .map(
      (e) =>
        `<tr><td><code class="mono">${esc(e.event_type)}</code></td><td>${idCell(e.task_id)}</td><td>${esc(e.actor_type)}:${esc(shortId(e.actor_id))}</td><td>${fmtTime(e.server_timestamp)}</td></tr>`,
    )
    .join("");
  return section(
    "Recent activity",
    "GET /events · 24h · not claimed exhaustive",
    `<table><thead><tr><th>Type</th><th>Task</th><th>Actor</th><th>Server time</th></tr></thead><tbody>${rows}</tbody></table>`,
  );
}

function agentsHtml(settledAgents: Settled<Agent[]>, settledEvents: Settled<EventEnvelope[]>): string {
  if (!settledAgents.ok) return section("Agents", "GET /agents", statusBlock("error", errMessage(settledAgents.error)));
  if (settledAgents.value.length === 0) return section("Agents", "GET /agents", statusBlock("empty", "No agents registered."));
  const seen = settledEvents.ok ? agentsSeenInEvents(settledEvents.value) : new Set<string>();
  const rows = settledAgents.value
    .map((a) => {
      const derived = seen.has(a.id) || (a.machine_id !== null && a.machine_id !== undefined && seen.has(a.machine_id));
      return `<tr><td>${esc(a.display_name)}</td><td><code class="mono">${esc(a.agent_kind === "" ? "—" : a.agent_kind)}</code></td><td>${idCell(a.machine_id)}</td><td>${
        derived ? `<span class="tag derived" title="Inferred from recent events — not canonical">seen recently · Derived</span>` : `<span class="tag">—</span>`
      }</td></tr>`;
    })
    .join("");
  return section(
    "Agents",
    "GET /agents · presence Derived, never canonical",
    `<table><thead><tr><th>Display name</th><th>Kind</th><th>Machine</th><th>Presence</th></tr></thead><tbody>${rows}</tbody></table>`,
  );
}

export function reviewActionsHtml(item: ReviewQueueItem, authed: boolean): string {
  if (item.kind !== "ai_work_review") return `<span class="meta">—</span>`;
  return `<button type="button" data-review-approve="${esc(item.id)}" ${authed ? "" : "disabled"}>Approve</button>` +
    `<button type="button" data-review-changes="${esc(item.id)}" ${authed ? "" : "disabled"}>Request changes</button>`;
}

function reviewsHtml(settled: Settled<ReviewQueue>, authed: boolean): string {
  if (!settled.ok) return section("Needs attention", "GET /review-queue", statusBlock("error", errMessage(settled.error)));
  const items = settled.value.items;
  if (items.length === 0)
    return section("Needs attention", "GET /review-queue", statusBlock("empty", "Nothing awaiting a human decision."));
  const rows = items
    .map((item) => {
      const title = item.title.length > 80 ? `${item.title.slice(0, 80)}…` : item.title;
      return `<tr><td><span class="tag">${esc(REVIEW_KIND_LABEL[item.kind])}</span></td><td>${esc(title)}</td><td>${esc(reviewQueueItemDetail(item))}</td><td>${idCell(item.task_id)}</td><td>${fmtTime(item.requested_at)}</td><td class="actions">${reviewActionsHtml(item, authed)}</td></tr>`;
    })
    .join("");
  return section(
    "Needs attention",
    "GET /review-queue · AI work review (resolve via PATCH /ai-work/{id}, admin) + proposed decisions (informational) + recent conflicts",
    `<table><thead><tr><th>Kind</th><th>Summary</th><th>Detail</th><th>Task</th><th>Requested</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table><div data-review-msg class="meta"></div>`,
  );
}

function bindReviewActions(root: HTMLElement, ctx: OverviewContext): void {
  const buttons = root.querySelectorAll<HTMLButtonElement>("[data-review-approve], [data-review-changes]");
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset["reviewApprove"] ?? button.dataset["reviewChanges"] ?? "";
      const resolution: ReviewResolution = button.dataset["reviewApprove"] !== undefined ? "approved" : "changes_requested";
      buttons.forEach((other) => {
        other.disabled = true;
      });
      resolveReview(ctx.client, id, resolution)
        .then(() => void renderOverview(root, ctx))
        .catch((error: unknown) => {
          setReviewMsg(root, describeError(error));
          buttons.forEach((other) => {
            other.disabled = false;
          });
        });
    });
  });
}

function setReviewMsg(root: HTMLElement, text: string): void {
  const node = root.querySelector("[data-review-msg]");
  if (node !== null) node.textContent = text;
}

function transfersHtml(settled: Settled<Transfer[]>): string {
  if (!settled.ok) return section("Transfers", "GET /transfers", statusBlock("error", errMessage(settled.error)));
  const recent = settled.value.slice(0, OVERVIEW_TRANSFER_LIMIT);
  if (recent.length === 0) return section("Transfers", "GET /transfers · read-only", statusBlock("empty", "No transfers visible to this token."));
  const rows = recent
    .map(
      (t) =>
        `<tr><td><code class="mono">${esc(t.transfer_code)}</code></td><td>${esc(t.filename)}</td><td>${esc(t.category)}</td><td>${esc(t.status)}</td><td>${fmtTime(t.created_at)}</td></tr>`,
    )
    .join("");
  return section(
    "Transfers",
    `GET /transfers · read-only · first ${OVERVIEW_TRANSFER_LIMIT} shown`,
    `<table><thead><tr><th>Code</th><th>Filename</th><th>Category</th><th>Status</th><th>Created</th></tr></thead><tbody>${rows}</tbody></table>`,
  );
}
