/**
 * DASH-2 — Project detail (central per-project space).
 *
 * Bootstrap: GET /api/v1/projects/{id} + GET .../state (active_tasks,
 * active_claims, generated_at) for the first paint; tabs deepen with the
 * specialized lists, which stay the detailed truth. Tabs: overview (state),
 * tasks (embedded project-scoped list+Kanban), claims (embedded panel).
 * No realtime timeline here — DASH-3.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import type { components } from "../openapi-schema";
import { describeError, esc, fmtTime, idCell, section, statusBlock } from "../ui";
import { renderClaimsInto } from "./claims";
import { renderTasksInto } from "./tasks";

type Project = components["schemas"]["Project"];
type ProjectState = components["schemas"]["ProjectState"];

export type ProjectTab = "overview" | "tasks" | "claims";

export interface ProjectDetailContext {
  client: StudioClient;
  authed: boolean;
}

async function fetchProject(client: StudioClient, id: string): Promise<Project> {
  const result = await client.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: id } } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

async function fetchState(client: StudioClient, id: string): Promise<ProjectState> {
  const result = await client.GET("/api/v1/projects/{project_id}/state", { params: { path: { project_id: id } } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

function tabsHtml(projectId: string, tab: ProjectTab): string {
  const link = (name: ProjectTab, label: string): string => {
    const suffix = name === "overview" ? "" : `/${name}`;
    const cls = tab === name ? "tab active" : "tab";
    return `<a class="${cls}" href="#/projects/${esc(projectId)}${suffix}">${label}</a>`;
  };
  return `<nav class="tabs">${link("overview", "Overview")}${link("tasks", "Tasks")}${link("claims", "Claims")}</nav>`;
}

export async function renderProjectDetail(
  root: HTMLElement,
  ctx: ProjectDetailContext,
  projectId: string,
  tab: ProjectTab,
): Promise<void> {
  root.innerHTML = section("Project", `GET /projects/${projectId}`, statusBlock("loading"));
  let project: Project;
  let state: ProjectState;
  try {
    [project, state] = await Promise.all([fetchProject(ctx.client, projectId), fetchState(ctx.client, projectId)]);
  } catch (error) {
    root.innerHTML = section("Project", `GET /projects/${projectId}`, statusBlock("error", describeError(error)));
    return;
  }
  const header = section(
    `Project · ${project.name}`,
    `GET /projects/{id} + /state · generated ${fmtTime(state.generated_at)}`,
    `<div class="detail-grid"><div><code class="mono">${esc(project.slug)}</code> · ${idCell(project.id)} · v${project.version}</div>` +
      `<div>${project.description ? esc(project.description) : "<span class=\"meta\">no description</span>"} · ${project.archived ? "archived" : "active"}</div></div>` +
      `<div class="row stats"><span>Active tasks: <strong>${state.active_tasks.length}</strong></span><span>Active claims: <strong>${state.active_claims.length}</strong></span></div>` +
      tabsHtml(project.id, tab),
  );
  if (tab === "overview") {
    const taskRows = state.active_tasks
      .map((t) => `<tr><td>${esc(t.title)}</td><td>${esc(t.status)}</td><td>${idCell(t.id)}</td><td><a href="#/tasks/${esc(t.id)}">Open</a></td></tr>`)
      .join("");
    const claimRows = state.active_claims
      .map((c) => `<tr><td><code class="mono">${esc(c.resource_path)}</code></td><td>${esc(c.resource_type)}</td><td>${fmtTime(c.expires_at)}</td></tr>`)
      .join("");
    root.innerHTML =
      header +
      section(
        "State bootstrap",
        "GET /state · first paint only, lists are the detailed truth",
        `<h3>Active tasks (${state.active_tasks.length})</h3>` +
          (taskRows === "" ? statusBlock("empty", "No active tasks.") : `<table><thead><tr><th>Title</th><th>Status</th><th>ID</th><th></th></tr></thead><tbody>${taskRows}</tbody></table>`) +
          `<h3>Active claims (${state.active_claims.length})</h3>` +
          (claimRows === "" ? statusBlock("empty", "No active claims.") : `<table><thead><tr><th>Path</th><th>Type</th><th>Expires</th></tr></thead><tbody>${claimRows}</tbody></table>`),
      );
    return;
  }
  const slot = document.createElement("div");
  root.innerHTML = header;
  root.appendChild(slot);
  if (tab === "tasks") {
    await renderTasksInto(slot, {
      client: ctx.client,
      authed: ctx.authed,
      projectId: project.id,
      scopeLabel: `project ${project.slug}`,
    });
  } else {
    await renderClaimsInto(slot, { client: ctx.client, projectId: project.id, authed: ctx.authed });
  }
}
