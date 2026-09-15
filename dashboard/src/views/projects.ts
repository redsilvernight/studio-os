/**
 * DASH-2 — Projects list (read-only; creation is provisioning, out of scope).
 * Selection is shared with Overview/Tasks through the store.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import type { components } from "../openapi-schema";
import { selectProject, uiState } from "../store";
import { esc, fmtTime, idCell, section, statusBlock } from "../ui";

type Project = components["schemas"]["Project"];

async function fetchProjects(client: StudioClient): Promise<Project[]> {
  const result = await client.GET("/api/v1/projects");
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

export async function renderProjects(root: HTMLElement, ctx: { client: StudioClient; authed: boolean }): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = section("Projects", "GET /projects", statusBlock("empty", "Set a machine token to list projects."));
    return;
  }
  root.innerHTML = section("Projects", "GET /projects", statusBlock("loading"));
  try {
    const projects = await fetchProjects(ctx.client);
    if (projects.length === 0) {
      root.innerHTML = section("Projects", "GET /projects", statusBlock("empty", "No projects."));
      return;
    }
    const rows = projects
      .map(
        (p) =>
          `<tr class="${uiState.selectedProjectId === p.id ? "selected" : ""}"><td>${esc(p.name)}</td>` +
          `<td><code class="mono">${esc(p.slug)}</code></td><td>${idCell(p.id)}</td>` +
          `<td>${p.archived ? "archived" : "active"}</td><td>v${p.version}</td><td>${fmtTime(p.updated_at)}</td>` +
          `<td><button type="button" data-open="${esc(p.id)}">Open</button></td></tr>`,
      )
      .join("");
    root.innerHTML = section(
      "Projects",
      "GET /projects · read-only",
      `<table><thead><tr><th>Name</th><th>Slug</th><th>ID</th><th>State</th><th>Version</th><th>Updated</th><th></th></tr></thead><tbody>${rows}</tbody></table>`,
    );
    root.querySelectorAll<HTMLButtonElement>("[data-open]").forEach((button) => {
      button.addEventListener("click", () => {
        selectProject(button.dataset["open"] ?? null);
        location.hash = `#/projects/${button.dataset["open"] ?? ""}`;
      });
    });
  } catch (error) {
    const message = error instanceof ApiError ? `${error.message}${error.errorCode ? ` [${error.errorCode}]` : ""}` : String(error);
    root.innerHTML = section("Projects", "GET /projects", statusBlock("error", message));
  }
}
