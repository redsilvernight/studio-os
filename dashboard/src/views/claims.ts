/**
 * Réservations de ressources d'un projet (onglet du workspace).
 *
 * - Liste : GET /api/v1/claims?project_id (pas de pagination/filtre serveur) ;
 *   filtre d'état (actives par défaut) et pagination appliqués côté client.
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
import { machineLabel, machineRef } from "../actorNames";
import { describeError, esc, fmtTime } from "../ui";
import { ACTION_LABEL } from "../language";

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

/** Confirmation de libération : nomme le chemin et la machine détentrice. */
export function releaseClaimConfirmText(claim: ResourceClaim): string {
  return (
    `Libérer la réservation « ${claim.resource_path} », détenue par la machine ${machineLabel(claim.claimed_by_machine_id)} ? ` +
    `Les autres machines ne la verront plus comme détenue. Réservé au détenteur ou à un administrateur.`
  );
}

export function rowsHtml(claims: ResourceClaim[], authed: boolean): string {
  const now = Date.now();
  return claims
    .map((c) => {
      const state = claimLiveliness(c, now);
      return (
        `<tr><td><code class="mono">${esc(c.resource_path)}</code></td><td>${esc(RESOURCE_TYPE_LABEL[c.resource_type] ?? c.resource_type)}</td>` +
        `<td>${machineRef(c.claimed_by_machine_id)}</td><td>${c.task_id ? `<a href="#/tasks/${esc(c.task_id)}">${esc(ACTION_LABEL.openTask)}</a>` : "—"}</td>` +
        `<td>${dsBadge(LIVELINESS_LABEL[state], LIVELINESS_TONE[state])}</td>` +
        `<td>Expire le ${fmtTime(c.expires_at)}<br /><span class="ds-list-sub">durée ${c.ttl_seconds} s</span></td>` +
        `<td class="actions"><button type="button" class="ds-btn ds-btn--sm" data-renew="${esc(c.id)}" aria-label="Renouveler la réservation ${esc(c.resource_path)}" ${authed ? "" : "disabled"}>Renouveler</button>` +
        `<button type="button" class="ds-btn ds-btn--sm" data-release="${esc(c.id)}" aria-label="Libérer la réservation ${esc(c.resource_path)}" ${authed && state !== "released" ? "" : "disabled"}>Libérer</button></td></tr>`
      );
    })
    .join("");
}

function createFormHtml(authed: boolean): string {
  const off = authed ? "" : " disabled";
  return (
    `<form data-create class="claims-form">` +
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

/** Filtre d'état : par défaut seules les réservations encore actives sont listées. */
export type ClaimFilter = "active" | "past" | "all";

export const CLAIMS_PAGE_SIZE = 10;

const FILTER_LABEL: Record<ClaimFilter, string> = {
  active: "Actives",
  past: "Expirées et libérées",
  all: "Toutes",
};

export function filterClaims(claims: ResourceClaim[], filter: ClaimFilter, now: number): ResourceClaim[] {
  if (filter === "all") return claims;
  return claims.filter((c) => (claimLiveliness(c, now) === "active") === (filter === "active"));
}

/** Page demandée, bornée à [1, nombre de pages] ; `pages` vaut au moins 1. */
export function paginateClaims<T>(items: T[], page: number, size = CLAIMS_PAGE_SIZE): { items: T[]; page: number; pages: number } {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(1, Math.floor(page) || 1), pages);
  return { items: items.slice((current - 1) * size, current * size), page: current, pages };
}

interface ViewState {
  filter: ClaimFilter;
  page: number;
}

/** L'état de vue survit au rechargement après renouvellement / libération / création. */
const viewStates = new WeakMap<HTMLElement, ViewState>();

function listHtml(claims: ResourceClaim[], state: ViewState, authed: boolean): string {
  const now = Date.now();
  const counts: Record<ClaimFilter, number> = {
    active: filterClaims(claims, "active", now).length,
    past: filterClaims(claims, "past", now).length,
    all: claims.length,
  };
  const options = (Object.keys(FILTER_LABEL) as ClaimFilter[])
    .map((f) => `<option value="${f}"${f === state.filter ? " selected" : ""}>${FILTER_LABEL[f]} (${counts[f]})</option>`)
    .join("");
  const filterBar = `<div class="claims-filter"><label for="claim-filter">Afficher</label> <select class="ds-select" id="claim-filter" data-filter>${options}</select></div>`;
  const visible = filterClaims(claims, state.filter, now);
  const paged = paginateClaims(visible, state.page);
  state.page = paged.page;
  let table: string;
  if (claims.length === 0) {
    return dsEmptyState("Aucune réservation", "Aucune ressource n'est réservée sur ce projet pour le moment.");
  }
  if (visible.length === 0) {
    table = dsEmptyState("Aucune réservation à afficher", "Aucune réservation ne correspond à ce filtre.");
  } else {
    table = `<div class="ds-table-wrap"><table class="ds-table"><caption class="ds-sr-only">Réservations du projet</caption><thead><tr><th scope="col">Chemin</th><th scope="col">Type</th><th scope="col">Machine</th><th scope="col">Tâche</th><th scope="col">État</th><th scope="col">Échéance</th><th scope="col">Actions</th></tr></thead><tbody>${rowsHtml(paged.items, authed)}</tbody></table></div>`;
  }
  const pager =
    paged.pages > 1
      ? `<nav class="claims-pager" aria-label="Pagination des réservations"><button type="button" class="ds-btn ds-btn--sm" data-page="${paged.page - 1}"${paged.page <= 1 ? " disabled" : ""}>Précédent</button>` +
        `<span class="ds-list-sub" aria-live="polite">Page ${paged.page} sur ${paged.pages}</span>` +
        `<button type="button" class="ds-btn ds-btn--sm" data-page="${paged.page + 1}"${paged.page >= paged.pages ? " disabled" : ""}>Suivant</button></nav>`
      : "";
  return filterBar + table + pager;
}

export async function renderClaimsInto(root: HTMLElement, ctx: ClaimsContext): Promise<void> {
  root.innerHTML = panelHtml("", `<div class="ds-list-sub" role="status" aria-busy="true">Chargement…</div>`);
  const reload = async (): Promise<void> => {
    await renderClaimsInto(root, ctx);
  };
  try {
    const claims = await listClaims(ctx.client, ctx.projectId);
    const state = viewStates.get(root) ?? { filter: "active" as ClaimFilter, page: 1 };
    viewStates.set(root, state);
    const activeCount = filterClaims(claims, "active", Date.now()).length;
    root.innerHTML = panelHtml(
      `${claims.length} réservation(s), dont ${activeCount} active(s) · renouvellement et libération réservés au détenteur ou à un administrateur`,
      `${ctx.authed ? "" : `<p class="ds-list-sub">Lecture seule : connectez-vous pour créer, renouveler ou libérer.</p>`}<div data-list></div>` +
        `<div class="claims-create">${dsSectionHeader("Nouvelle réservation")}${createFormHtml(ctx.authed)}</div>` +
        `<div data-msg class="ds-list-sub" role="status"></div>`,
    );
    const renderList = (): void => {
      const list = root.querySelector<HTMLElement>("[data-list]");
      if (list === null) return;
      list.innerHTML = listHtml(claims, state, ctx.authed);
      list.querySelector<HTMLSelectElement>("[data-filter]")?.addEventListener("change", (event) => {
        state.filter = (event.target as HTMLSelectElement).value as ClaimFilter;
        state.page = 1;
        renderList();
        list.querySelector<HTMLSelectElement>("[data-filter]")?.focus();
      });
      list.querySelectorAll<HTMLButtonElement>("[data-page]").forEach((button) => {
        button.addEventListener("click", () => {
          state.page = Number(button.dataset["page"]);
          renderList();
        });
      });
      bindRows(root, ctx, claims, reload);
    };
    renderList();
    bindForm(root, ctx, reload);
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

function bindRows(root: HTMLElement, ctx: ClaimsContext, claims: ResourceClaim[], reload: () => Promise<void>): void {
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
      const claimId = button.dataset["release"] ?? "";
      const claim = claims.find((c) => c.id === claimId);
      if (claim === undefined || !window.confirm(releaseClaimConfirmText(claim))) return;
      button.disabled = true;
      releaseClaim(ctx.client, claimId)
        .then(() => reload())
        .catch((error: unknown) => {
          button.disabled = false;
          setMsg(root, describeError(error));
        });
    });
  });
}

function bindForm(root: HTMLElement, ctx: ClaimsContext, reload: () => Promise<void>): void {
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
