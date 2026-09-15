/** Tiny HTML helpers — no framework, escaped by default. */

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
  return esc(date.toLocaleString());
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
  if (status === "loading") return `<div class="state loading">Loading…</div>`;
  if (status === "error") return `<div class="state error">Error: ${esc(message)}</div>`;
  if (status === "empty") return `<div class="state empty">${esc(message === "" ? "Nothing to show." : message)}</div>`;
  return "";
}

export function section(title: string, meta: string, body: string): string {
  return `<section class="panel"><header><h2>${esc(title)}</h2><span class="meta">${meta}</span></header><div class="body">${body}</div></section>`;
}
