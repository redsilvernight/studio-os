/**
 * DASH-2 — Project resource claims.
 *
 * - List: GET /api/v1/claims?project_id (no pagination/filter server-side).
 * - Create: POST /api/v1/claims + client-generated Idempotency-Key.
 *   Soft-lock: overlap still returns 201 (+ resource.conflict event);
 *   the UI never invents a 409. Overlap visibility via REST does not
 *   exist — DASH-3 will surface the event.
 * - Renew: POST .../renew (holder-or-admin). Release: DELETE → 204
 *   (holder-or-admin, confirmation asked).
 */
import type { StudioClient } from "../api";
import { createClaim, listClaims, releaseClaim, renewClaim, type ResourceClaim } from "../claimsApi";
import { describeError, esc, fmtTime, idCell, section, statusBlock } from "../ui";

export interface ClaimsContext {
  client: StudioClient;
  projectId: string;
  authed: boolean;
}

function claimLiveliness(claim: ResourceClaim, now: number): string {
  if (claim.status === "released") return "released";
  if (claim.status === "expired") return "expired";
  return new Date(claim.expires_at).getTime() <= now ? "expired (stored: active)" : "active";
}

function rowsHtml(claims: ResourceClaim[], authed: boolean): string {
  const now = Date.now();
  return claims
    .map(
      (c) =>
        `<tr><td><code class="mono">${esc(c.resource_path)}</code></td><td>${esc(c.resource_type)}</td>` +
        `<td>${idCell(c.claimed_by_machine_id)}</td><td>${idCell(c.task_id)}</td>` +
        `<td>${esc(claimLiveliness(c, now))}</td><td>TTL ${c.ttl_seconds}s · exp ${fmtTime(c.expires_at)}</td>` +
        `<td class="actions"><button type="button" data-renew="${esc(c.id)}" ${authed ? "" : "disabled"}>Renew</button>` +
        `<button type="button" data-release="${esc(c.id)}" ${authed ? "" : "disabled"}>Release</button></td></tr>`,
    )
    .join("");
}

function createFormHtml(authed: boolean): string {
  return `<form data-create class="inline-form"><h3>New claim</h3>
    <label>Path <input name="resource_path" required placeholder="godot/scenes/level1.tscn" ${authed ? "" : "disabled"} /></label>
    <label>Type <select name="resource_type" ${authed ? "" : "disabled"}><option value="file">file</option><option value="folder">folder</option></select></label>
    <label>TTL (s) <input name="ttl_seconds" type="number" min="1" value="3600" required ${authed ? "" : "disabled"} /></label>
    <label>Task ID (optional) <input name="task_id" placeholder="uuid" ${authed ? "" : "disabled"} /></label>
    <button type="submit" ${authed ? "" : "disabled"}>Create</button>
    <span class="meta">soft-lock: overlaps still return 201 · Idempotency-Key generated per attempt</span>
    <div data-create-msg class="meta"></div></form>`;
}

export async function renderClaimsInto(root: HTMLElement, ctx: ClaimsContext): Promise<void> {
  root.innerHTML = section("Claims", "GET /claims?project_id", statusBlock("loading"));
  const reload = async (): Promise<void> => {
    await renderClaimsInto(root, ctx);
  };
  try {
    const claims = await listClaims(ctx.client, ctx.projectId);
    const table =
      claims.length === 0
        ? statusBlock("empty", "No claims for this project.")
        : `<table><thead><tr><th>Path</th><th>Type</th><th>Machine</th><th>Task</th><th>Liveliness</th><th>TTL</th><th>Actions</th></tr></thead><tbody>${rowsHtml(claims, ctx.authed)}</tbody></table>`;
    root.innerHTML = section(
      "Claims",
      `GET /claims?project_id · ${claims.length} shown · renew/release = holder-or-admin`,
      `${ctx.authed ? "" : `<div class="state empty">Read-only: set a token to create, renew or release.</div>`}${table}${createFormHtml(ctx.authed)}<div data-msg class="meta"></div>`,
    );
    bind(root, ctx, reload);
  } catch (error) {
    root.innerHTML = section("Claims", "GET /claims?project_id", statusBlock("error", describeError(error)));
  }
}

function setMsg(root: HTMLElement, text: string): void {
  const node = root.querySelector("[data-msg]");
  if (node !== null) node.textContent = text;
}

function bind(root: HTMLElement, ctx: ClaimsContext, reload: () => Promise<void>): void {
  root.querySelectorAll<HTMLButtonElement>("[data-renew]").forEach((button) => {
    button.addEventListener("click", () => {
      button.disabled = true;
      renewClaim(ctx.client, button.dataset["renew"] ?? "")
        .then(() => reload())
        .catch((error: unknown) => {
          button.disabled = false;
          setMsg(root, describeError(error));
        });
    });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-release]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!window.confirm("Release this resource claim? Other machines will no longer see it as held.")) return;
      button.disabled = true;
      releaseClaim(ctx.client, button.dataset["release"] ?? "")
        .then(() => reload())
        .catch((error: unknown) => {
          button.disabled = false;
          setMsg(root, describeError(error));
        });
    });
  });
  const form = root.querySelector<HTMLFormElement>("[data-create]");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const taskRaw = String(data.get("task_id") ?? "").trim();
    const ttl = Number(data.get("ttl_seconds"));
    const msg = form.querySelector("[data-create-msg]");
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]");
    if (submit !== null) submit.disabled = true;
    createClaim(ctx.client, {
      project_id: ctx.projectId,
      task_id: taskRaw === "" ? null : taskRaw,
      resource_path: String(data.get("resource_path") ?? ""),
      resource_type: String(data.get("resource_type") ?? "file") === "folder" ? "folder" : "file",
      ttl_seconds: Number.isFinite(ttl) ? Math.floor(ttl) : 3600,
    })
      .then((created) => {
        if (msg !== null) msg.textContent = `Created ${created.id} (201 — soft-lock: check overlaps via events in DASH-3).`;
        void reload();
      })
      .catch((error: unknown) => {
        if (msg !== null) msg.textContent = describeError(error);
        if (submit !== null) submit.disabled = false;
      });
  });
}
