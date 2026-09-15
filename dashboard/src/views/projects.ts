/**
 * DASH-2/DASH-5 — Projects list + creation.
 * Selection is shared with Overview/Tasks through the store. Creation
 * (`POST /projects`, admin/developer) moved from "provisioning only" to the
 * write dashboard in DASH-5; the server stays the only authority and the list
 * is refetched after every create.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { createProject } from "../creationsApi";
import type { components } from "../openapi-schema";
import { selectProject, uiState } from "../store";
import { describeError, esc, fmtTime, idCell, section, statusBlock } from "../ui";

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
  let projects: Project[];
  try {
    projects = await fetchProjects(ctx.client);
  } catch (error) {
    root.innerHTML = section("Projects", "GET /projects", statusBlock("error", describeError(error)));
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
  const table =
    projects.length === 0
      ? statusBlock("empty", "No projects.")
      : `<table><thead><tr><th>Name</th><th>Slug</th><th>ID</th><th>State</th><th>Version</th><th>Updated</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
  root.innerHTML = section(
    "Projects",
    `GET /projects · ${projects.length} shown`,
    `${table}
     <form data-create class="inline-form"><h3>New project</h3>
       <label>Slug <input name="slug" required placeholder="my-project" /></label>
       <label>Name <input name="name" required /></label>
       <label>Description <input name="description" /></label>
       <button type="submit">Create</button>
       <span class="meta">POST /projects · admin/developer · Idempotency-Key per attempt</span>
       <div data-create-msg class="meta"></div></form>`,
  );
  root.querySelectorAll<HTMLButtonElement>("[data-open]").forEach((button) => {
    button.addEventListener("click", () => {
      selectProject(button.dataset["open"] ?? null);
      location.hash = `#/projects/${button.dataset["open"] ?? ""}`;
    });
  });
  const form = root.querySelector<HTMLFormElement>("[data-create]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const msg = form.querySelector("[data-create-msg]");
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit !== null) submit.disabled = true;
    const description = String(data.get("description") ?? "").trim();
    createProject(ctx.client, {
      slug: String(data.get("slug") ?? "").trim(),
      name: String(data.get("name") ?? "").trim(),
      description: description === "" ? null : description,
    })
      .then((created) => {
        if (msg !== null) msg.textContent = `Created ${created.slug}.`;
        void renderProjects(root, ctx);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
}
