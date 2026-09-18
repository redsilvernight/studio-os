/** Tiny HTML helpers — no framework, escaped by default. French user-facing strings (DEC-0078). */

import { ApiError } from "./api";

export function esc(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function fmtTime(iso: string | null | undefined): string {
  if (iso === null || iso === undefined || iso === "") return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return esc(iso);
  return esc(date.toLocaleString("fr-FR"));
}

export function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

export function idCell(id: string | null | undefined): string {
  if (!id) return "—";
  return `<code class="mono" title="${esc(id)}">${esc(shortId(id))}</code>`;
}

export type SectionStatus = "loading" | "error" | "empty" | "ready";

export function statusBlock(status: SectionStatus, message = ""): string {
  if (status === "loading")
    return `<div class="state loading" role="status" aria-busy="true">Chargement…</div>`;
  if (status === "error") return `<div class="state error" role="alert">Erreur : ${esc(message)}</div>`;
  if (status === "empty")
    return `<div class="state empty">${esc(message === "" ? "Rien à afficher." : message)}</div>`;
  return "";
}

export function section(title: string, meta: string, body: string): string {
  return `<section class="panel"><header><h2>${esc(title)}</h2><span class="meta">${meta}</span></header><div class="body">${body}</div></section>`;
}

/** Human-readable mutation error. Never invents a status change. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const parts = [`HTTP ${error.status}`];
    if (error.errorCode !== null) parts.push(error.errorCode);
    parts.push(error.message);
    if (error.errorCode === "version_conflict" && error.serverVersion !== null) {
      parts.push(`server is at version ${error.serverVersion} — re-read, then re-apply`);
    }
    return parts.join(" · ");
  }
  return error instanceof Error ? error.message : String(error);
}
