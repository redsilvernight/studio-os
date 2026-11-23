/**
 * Mesures d'infrastructure (phase M) : tableau des derniers relevés et courbe
 * par série, lus sur GET /api/v1/internal/infra-measurements (admin).
 * Agrégats seulement : aucun titre, nom de fichier ni contenu n'existe dans la
 * source. Vue jetable dans sa forme ; la source de données, elle, est partagée
 * avec l'écran Usage et la console opérateur.
 */
import type { StudioClient } from "../api";
import { ApiError, parseErrorBody } from "../api";
import type { components } from "../openapi-schema";
import { dsEmptyState, dsErrorState, dsPageHeader, dsSkeleton } from "../ds/ds";
import { humanBytes } from "../transfersFormat";
import { describeError, esc, fmtTime } from "../ui";
import { sfx } from "../format";
import { UI_LABEL } from "../language";

export type InfraReport = components["schemas"]["InfraMeasurementsReport"];
export type InfraSeries = components["schemas"]["InfraSeries"];

export async function getInfraMeasurements(client: StudioClient, days = 7): Promise<InfraReport> {
  const result = await client.GET("/api/v1/internal/infra-measurements", { params: { query: { days } } });
  if (result.response.ok && result.data !== undefined) return result.data;
  throw new ApiError(parseErrorBody(result.response.status, result.error));
}

const LABELS: Record<string, string> = {
  pg_table_bytes: "Table PostgreSQL",
  storage_bytes: "Stockage du projet",
  sse_connections: "Connexions SSE",
  process_rss_bytes: "Mémoire du processus",
  backup_bytes: "Sauvegardes",
};

export function seriesLabel(series: InfraSeries): string {
  const base = LABELS[series.metric] ?? series.metric;
  if (series.subject !== "") return `${base} · ${series.subject}`;
  if (series.project_id !== null && series.project_id !== undefined) return `${base} · projet ${series.project_id.slice(0, 8)}`;
  return base;
}

function formatValue(series: InfraSeries, value: number): string {
  return series.metric === "sse_connections" ? String(value) : humanBytes(value);
}

/** Courbe SVG normalisée sur [min, max] de la série ; points déjà triés. */
export function sparkline(series: InfraSeries): string {
  const values = series.points.map((point) => point.value);
  const label = `${seriesLabel(series)} : de ${formatValue(series, values[0] ?? 0)} à ${formatValue(series, values[values.length - 1] ?? 0)} sur ${values.length} relevé${sfx(values.length)}`;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const step = values.length > 1 ? 120 / (values.length - 1) : 0;
  const coords = values.map((value, index) => `${(index * step).toFixed(1)},${(28 - ((value - min) / span) * 26 - 1).toFixed(1)}`).join(" ");
  return `<svg class="infra-spark" viewBox="0 0 120 28" width="120" height="28" role="img" aria-label="${esc(label)}"><polyline points="${coords}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}

export function infraMeasuresHtml(report?: InfraReport, error?: string): string {
  const header = dsPageHeader("Mesures d'infrastructure", "Coût réel de l'instance : tailles et comptes, jamais de contenu.");
  if (error !== undefined) return `<div class="admin">${header}${dsErrorState("Mesures indisponibles", error)}</div>`;
  if (report === undefined) return `<div class="admin">${header}${dsSkeleton(4)}</div>`;
  if (report.series.length === 0) return `<div class="admin">${header}${dsEmptyState("Aucun relevé", `Aucune mesure sur les ${report.window_days} derniers jours.`)}</div>`;
  const rows = report.series.map((series) => `<tr><th scope="row">${esc(seriesLabel(series))}</th><td>${esc(formatValue(series, series.latest.value))}</td><td>${esc(fmtTime(series.latest.measured_at))}</td><td>${sparkline(series)}</td></tr>`).join("");
  return `<div class="admin">${header}<section class="ds-panel" aria-label="Relevés"><p class="ds-list-sub" role="status">Fenêtre de ${report.window_days} jour${sfx(report.window_days)}, consultée le ${esc(fmtTime(report.generated_at))}.</p><div class="body"><table class="ds-table"><thead><tr><th scope="col">Mesure</th><th scope="col">Dernier relevé</th><th scope="col">Mesuré le</th><th scope="col">Évolution</th></tr></thead><tbody>${rows}</tbody></table></div></section></div>`;
}

export async function renderInfraMeasures(root: HTMLElement, ctx?: { client: StudioClient; authed: boolean }): Promise<void> {
  if (ctx === undefined || !ctx.authed) {
    root.innerHTML = dsPageHeader("Mesures d'infrastructure") + dsEmptyState(UI_LABEL.signIn, "Connectez-vous avec un compte administrateur pour consulter les mesures.");
    return;
  }
  root.innerHTML = infraMeasuresHtml();
  try {
    root.innerHTML = infraMeasuresHtml(await getInfraMeasurements(ctx.client));
  } catch (error) {
    root.innerHTML = infraMeasuresHtml(undefined, error instanceof ApiError && error.status === 403 ? "Réservé aux administrateurs." : describeError(error));
  }
}
