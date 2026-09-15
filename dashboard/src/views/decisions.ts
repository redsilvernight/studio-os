/**
 * DASH-5 — Decisions list + creation (write dashboard).
 *
 * Read: `GET /api/v1/decisions?project_id` (existing endpoint). Write:
 * `POST /api/v1/decisions` with a fresh `Idempotency-Key`. The contract
 * requires a proposer (`proposed_by_type`, `proposed_by_id`); the field is
 * prefilled from the dashboard JWT's `sub` claim when the token is a JWT
 * (memory-only, never an authorization decision), and must be entered manually
 * for an opaque machine token. There is no decision transition endpoint
 * (accept/supersede) — the UI never invents one.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import { getToken } from "../auth";
import { createDecision, decodeJwtSubject, isUuid } from "../creationsApi";
import { uiState } from "../store";
import { describeError, esc, fmtTime, idCell, section, statusBlock } from "../ui";
import type { components } from "../openapi-schema";

type Decision = components["schemas"]["Decision"];

export interface DecisionsContext {
  client: StudioClient;
  authed: boolean;
  projectId?: string;
}

async function fetchDecisions(client: StudioClient, projectId?: string): Promise<Decision[]> {
  const result = await client.GET("/api/v1/decisions", {
    params: { query: projectId !== undefined ? { project_id: projectId } : {} },
  });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

const PROPOSER_TYPES = ["user", "agent", "system"] as const;

function createFormHtml(authed: boolean, projectId: string | undefined, proposerId: string): string {
  const projectField =
    projectId !== undefined
      ? `<span class="meta">project ${esc(projectId)}</span>`
      : `<label>Project ID (optional) <input name="project_id" placeholder="uuid" ${authed ? "" : "disabled"} /></label>`;
  return `<form data-create class="inline-form"><h3>New decision</h3>
    ${projectField}
    <label>Task ID (optional) <input name="task_id" placeholder="uuid" ${authed ? "" : "disabled"} /></label>
    <label>Title <input name="title" required ${authed ? "" : "disabled"} /></label>
    <label>Body <textarea name="body" rows="3" required ${authed ? "" : "disabled"}></textarea></label>
    <label>Proposed by type <select name="proposed_by_type" ${authed ? "" : "disabled"}>${PROPOSER_TYPES.map((t) => `<option value="${t}">${t}</option>`).join("")}</select></label>
    <label>Proposed by ID (user UUID) <input name="proposed_by_id" value="${esc(proposerId)}" placeholder="uuid" required ${authed ? "" : "disabled"} /></label>
    <button type="submit" ${authed ? "" : "disabled"}>Create</button>
    <span class="meta">POST /decisions · Idempotency-Key per attempt · no accept/supersede endpoint exists</span>
    <div data-create-msg class="meta"></div></form>`;
}

export async function renderDecisions(root: HTMLElement, ctx: DecisionsContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = section("Decisions", "GET /decisions", statusBlock("empty", "Set a machine token to list decisions."));
    return;
  }
  root.innerHTML = section("Decisions", "GET /decisions", statusBlock("loading"));
  const projectId = ctx.projectId ?? uiState.selectedProjectId ?? undefined;
  let decisions: Decision[] = [];
  try {
    decisions = await fetchDecisions(ctx.client, projectId);
  } catch (error) {
    root.innerHTML = section("Decisions", "GET /decisions", statusBlock("error", describeError(error)));
    return;
  }
  const rows = decisions
    .map(
      (d) =>
        `<tr><td>${idCell(d.id)}</td><td><code class="mono">${esc(d.readable_id)}</code></td><td>${esc(d.title)}</td>` +
        `<td>${esc(d.status)}</td><td>${esc(d.proposed_by_type)}:${idCell(d.proposed_by_id)}</td><td>${idCell(d.project_id)}</td><td>${fmtTime(d.created_at)}</td></tr>`,
    )
    .join("");
  const table =
    decisions.length === 0
      ? statusBlock("empty", "No decisions.")
      : `<table><thead><tr><th>ID</th><th>Readable</th><th>Title</th><th>Status</th><th>Proposed by</th><th>Project</th><th>Created</th></tr></thead><tbody>${rows}</tbody></table>`;
  const proposer = decodeJwtSubject(getToken()) ?? "";
  root.innerHTML = section(
    "Decisions",
    `GET /decisions${projectId !== undefined ? "?project_id" : ""} · ${decisions.length} shown`,
    `${table}${createFormHtml(ctx.authed, projectId, proposer)}<div data-msg class="meta"></div>`,
  );
  bind(root, ctx, projectId);
}

function bind(root: HTMLElement, ctx: DecisionsContext, projectId: string | undefined): void {
  const form = root.querySelector<HTMLFormElement>("[data-create]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const msg = form.querySelector("[data-create-msg]");
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    const proposedById = String(data.get("proposed_by_id") ?? "").trim();
    if (!isUuid(proposedById)) {
      if (msg !== null) msg.textContent = "proposed_by_id must be a UUID.";
      return;
    }
    const project = projectId ?? String(data.get("project_id") ?? "").trim();
    if (submit !== null) submit.disabled = true;
    createDecision(ctx.client, {
      project_id: project === "" ? null : project,
      task_id: String(data.get("task_id") ?? "").trim() === "" ? null : String(data.get("task_id") ?? "").trim(),
      title: String(data.get("title") ?? ""),
      body: String(data.get("body") ?? ""),
      proposed_by_type: String(data.get("proposed_by_type") ?? "user"),
      proposed_by_id: proposedById,
    })
      .then((created) => {
        if (msg !== null) msg.textContent = `Created ${created.readable_id}.`;
        void renderDecisions(root, ctx);
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
}
