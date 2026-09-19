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
import { focusDsErrorBox } from "../ds/ds";

export interface ClaimsContext {
  client: StudioClient;
  projectId: string;
  authed: boolean;
}

function claimLiveliness(claim: ResourceClaim, now: number): string {
  if (claim.status === "released") return "libérée";
  if (claim.status === "expired") return "expirée";
  return new Date(claim.expires_at).getTime() <= now ? "expirée" : "active";
}

function rowsHtml(claims: ResourceClaim[], authed: boolean): string {
  const now = Date.now();
  return claims
    .map(
      (c) =>
        `<tr><td><code class="mono">${esc(c.resource_path)}</code></td><td>${esc(c.resource_type)}</td>` +
        `<td>${idCell(c.claimed_by_machine_id)}</td><td>${idCell(c.task_id)}</td>` +
        `<td>${esc(claimLiveliness(c, now))}</td><td>TTL ${c.ttl_seconds} s · expire ${fmtTime(c.expires_at)}</td>` +
        `<td class="actions"><button type="button" class="ds-btn ds-btn--sm" data-renew="${esc(c.id)}" aria-label="Renouveler la réservation ${esc(c.resource_path)}" ${authed ? "" : "disabled"}>Renouveler</button>` +
        `<button type="button" class="ds-btn ds-btn--sm" data-release="${esc(c.id)}" aria-label="Libérer la réservation ${esc(c.resource_path)}" ${authed ? "" : "disabled"}>Libérer</button></td></tr>`,
    )
    .join("");
}

function createFormHtml(authed: boolean): string {
  return `<form data-create class="inline-form"><h3>Nouvelle réservation</h3>
    <label>Chemin <input name="resource_path" required placeholder="godot/scenes/level1.tscn" ${authed ? "" : "disabled"} /></label>
    <label>Type <select name="resource_type" ${authed ? "" : "disabled"}><option value="file">Fichier</option><option value="folder">Dossier</option></select></label>
    <label>TTL (secondes) <input name="ttl_seconds" type="number" min="1" value="3600" required ${authed ? "" : "disabled"} /></label>
    <label>ID de tâche (optionnel) <input name="task_id" placeholder="uuid" ${authed ? "" : "disabled"} /></label>
    <button type="submit" ${authed ? "" : "disabled"}>Créer</button>
    <span class="meta">Verrou souple : un chevauchement reste accepté (201) · clé d'idempotence générée par tentative</span>
    <div data-create-msg class="meta" role="status"></div></form>`;
}

export async function renderClaimsInto(root: HTMLElement, ctx: ClaimsContext): Promise<void> {
  root.innerHTML = section("Réservations", "GET /claims?project_id", statusBlock("loading"));
  const reload = async (): Promise<void> => {
    await renderClaimsInto(root, ctx);
  };
  try {
    const claims = await listClaims(ctx.client, ctx.projectId);
    const table =
      claims.length === 0
        ? statusBlock("empty", "Aucune réservation pour ce projet.")
        : `<table><caption class="ds-sr-only">Réservations du projet</caption><thead><tr><th scope="col">Chemin</th><th scope="col">Type</th><th scope="col">Machine</th><th scope="col">Tâche</th><th scope="col">État</th><th scope="col">TTL</th><th scope="col">Actions</th></tr></thead><tbody>${rowsHtml(claims, ctx.authed)}</tbody></table>`;
    root.innerHTML = section(
      "Réservations",
      `GET /claims?project_id · ${claims.length} affichée(s) · renouveler/libérer = détenteur ou admin`,
      `${ctx.authed ? "" : `<div class="state empty">Lecture seule : définissez un jeton pour créer, renouveler ou libérer.</div>`}${table}${createFormHtml(ctx.authed)}<div data-msg class="meta" role="status"></div>`,
    );
    bind(root, ctx, reload);
  } catch (error) {
    root.innerHTML = section("Réservations", "GET /claims?project_id", statusBlock("error", describeError(error)));
  }
}

function setMsg(root: HTMLElement, text: string): void {
  const node = root.querySelector("[data-msg]");
  if (node === null) return;
  node.textContent = text;
  if (text !== "" && node instanceof HTMLElement) focusDsErrorBox(node);
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
      if (!window.confirm("Libérer cette réservation ? Les autres machines ne la verront plus comme détenue.")) return;
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
        if (msg !== null) msg.textContent = `Réservation ${created.id} créée (201 — verrou souple : vérifiez les chevauchements via les événements).`;
        void reload();
      })
      .catch((error: unknown) => {
        if (msg !== null) {
          msg.textContent = describeError(error);
          if (msg instanceof HTMLElement) focusDsErrorBox(msg);
        }
        if (submit !== null) submit.disabled = false;
      });
  });
}
