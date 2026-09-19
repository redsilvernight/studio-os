/**
 * Réservations de ressources d'un projet (onglet du workspace).
 *
 * - Liste : GET /api/v1/claims?project_id (pas de pagination/filtre serveur).
 * - Création : POST /api/v1/claims + Idempotency-Key générée par tentative.
 *   Une réservation avertit sans jamais bloquer : un chevauchement reste
 *   accepté (201, événement resource.conflict) — l'UI n'invente aucun 409.
 * - Renouveler : POST .../renew (détenteur ou admin). Libérer : DELETE → 204
 *   (détenteur ou admin, confirmation demandée).
 *
 * Vocabulaire : « réservation » (claim de ressource), à ne pas confondre avec
 * la prise en charge d'une tâche ni avec un verrou de Bibliothèque.
 */
import type { StudioClient } from "../api";
import { createClaim, listClaims, releaseClaim, renewClaim, type ResourceClaim } from "../claimsApi";
import { dsBadge, dsEmptyState, dsField, dsSectionHeader, focusDsErrorBox } from "../ds/ds";
import { describeError, esc, fmtTime, idCell } from "../ui";

export interface ClaimsContext {
  client: StudioClient;
  projectId: string;
  authed: boolean;
}

type ClaimLiveliness = "active" | "expired" | "released";

const LIVELINESS_LABEL: Record<ClaimLiveliness, string> = {
  active: "Active",
  expired: "Expirée",
  released: "Libérée",
};

const LIVELINESS_TONE: Record<ClaimLiveliness, "success" | "warning" | "neutral"> = {
  active: "success",
  expired: "warning",
  released: "neutral",
};

const RESOURCE_TYPE_LABEL: Record<string, string> = { file: "Fichier", folder: "Dossier" };

function claimLiveliness(claim: ResourceClaim, now: number): ClaimLiveliness {
  if (claim.status === "released") return "released";
  if (claim.status === "expired") return "expired";
  return new Date(claim.expires_at).getTime() <= now ? "expired" : "active";
}

function rowsHtml(claims: ResourceClaim[], authed: boolean): string {
  const now = Date.now();
  return claims
    .map((c) => {
      const state = claimLiveliness(c, now);
      return (
        `<tr><td><code class="mono">${esc(c.resource_path)}</code></td><td>${esc(RESOURCE_TYPE_LABEL[c.resource_type] ?? c.resource_type)}</td>` +
        `<td>${idCell(c.claimed_by_machine_id)}</td><td>${idCell(c.task_id)}</td>` +
        `<td>${dsBadge(LIVELINESS_LABEL[state], LIVELINESS_TONE[state])}</td>` +
        `<td>Expire le ${fmtTime(c.expires_at)}<br /><span class="ds-list-sub">durée ${c.ttl_seconds} s</span></td>` +
        `<td class="actions"><button type="button" class="ds-btn ds-btn--sm" data-renew="${esc(c.id)}" aria-label="Renouveler la réservation ${esc(c.resource_path)}" ${authed ? "" : "disabled"}>Renouveler</button>` +
        `<button type="button" class="ds-btn ds-btn--sm" data-release="${esc(c.id)}" aria-label="Libérer la réservation ${esc(c.resource_path)}" ${authed ? "" : "disabled"}>Libérer</button></td></tr>`
      );
    })
    .join("");
}

function createFormHtml(authed: boolean): string {
  const off = authed ? "" : " disabled";
  return (
    `<form data-create>` +
    dsField("claim-path", "Chemin", `<input class="ds-input" id="FIELD" name="resource_path" required placeholder="godot/scenes/level1.tscn" autocomplete="off"${off} />`) +
    dsField("claim-type", "Type", `<select class="ds-select" id="FIELD" name="resource_type"${off}><option value="file">Fichier</option><option value="folder">Dossier</option></select>`) +
    dsField("claim-ttl", "Durée (secondes)", `<input class="ds-input" id="FIELD" name="ttl_seconds" type="number" min="1" value="3600" required${off} />`, "La réservation expire d'elle-même à l'issue de cette durée.") +
    dsField("claim-task", "Tâche liée (facultatif)", `<input class="ds-input" id="FIELD" name="task_id" placeholder="identifiant de la tâche" autocomplete="off"${off} />`) +
    `<p class="ds-list-sub">Une réservation prévient les autres sans rien bloquer : un chevauchement reste accepté et est signalé. Un envoi répété ne crée pas de doublon.</p>` +
    `<button type="submit" class="ds-btn ds-btn--primary"${off}>Créer la réservation</button>` +
    `<div data-create-msg class="ds-list-sub" role="status"></div></form>`
  );
}

function panelHtml(subtitle: string, body: string): string {
  return `<section class="ds-panel" aria-label="Réservations"><header><h2>Réservations</h2><span class="ds-list-sub">${esc(subtitle)}</span></header><div class="body">${body}</div></section>`;
}

export async function renderClaimsInto(root: HTMLElement, ctx: ClaimsContext): Promise<void> {
  root.innerHTML = panelHtml("", `<div class="ds-list-sub" role="status" aria-busy="true">Chargement…</div>`);
  const reload = async (): Promise<void> => {
    await renderClaimsInto(root, ctx);
  };
  try {
    const claims = await listClaims(ctx.client, ctx.projectId);
    const table =
      claims.length === 0
        ? dsEmptyState("Aucune réservation", "Aucune ressource n'est réservée sur ce projet pour le moment.")
        : `<div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">Réservations du projet</caption><thead><tr><th scope="col">Chemin</th><th scope="col">Type</th><th scope="col">Machine</th><th scope="col">Tâche</th><th scope="col">État</th><th scope="col">Échéance</th><th scope="col">Actions</th></tr></thead><tbody>${rowsHtml(claims, ctx.authed)}</tbody></table></div>`;
    root.innerHTML = panelHtml(
      `${claims.length} réservation(s) · renouvellement et libération réservés au détenteur ou à un administrateur`,
      `${ctx.authed ? "" : `<p class="ds-list-sub">Lecture seule : connectez-vous pour créer, renouveler ou libérer.</p>`}${table}` +
        `<div>${dsSectionHeader("Nouvelle réservation")}${createFormHtml(ctx.authed)}</div>` +
        `<div data-msg class="ds-list-sub" role="status"></div>`,
    );
    bind(root, ctx, reload);
  } catch (error) {
    root.innerHTML = panelHtml(
      "",
      `<div class="ds-notice ds-notice--danger" role="alert"><strong>Réservations indisponibles.</strong> ${esc(describeError(error))}</div>`,
    );
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
      .then(() => reload())
      .catch((error: unknown) => {
        if (msg !== null) {
          msg.textContent = describeError(error);
          if (msg instanceof HTMLElement) focusDsErrorBox(msg);
        }
        if (submit !== null) submit.disabled = false;
      });
  });
}
