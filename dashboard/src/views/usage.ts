/**
 * Consommation — durée, coût et qualité de mesure (P03-usage-ui).
 *
 * - Source unique : GET /api/v1/usage/summary. Les valeurs serveur sont
 *   affichées telles quelles, jamais additionnées ni recalculées ici.
 * - Honnêteté : seul un statut `exact` s'affiche comme un total. `estimated`
 *   → « ≈ … (estimé) », `partial` → « au moins … » + entrées inconnues,
 *   `unknown` → « inconnu », `mixed_currency` → pas de total, détail par
 *   devise. Un statut inconnu du client n'est jamais présenté comme exact.
 * - Aucun prompt (le ledger n'en porte pas) ; aucun UUID visible hors
 *   dsTechDetails replié.
 */
import type { StudioClient } from "../api";
import { ApiError } from "../api";
import { dsBadge, dsSectionHeader, dsSkeleton, dsTechDetails, type DsTechRow, type DsTone } from "../ds/ds";
import { describeError, esc, fmtTime } from "../ui";
import { fetchUsageSummary, type UsageAggregate, type UsageGroupBy, type UsageSummary } from "../usageApi";
import "./usage.css";

type CostTotal = UsageAggregate["cost"];
type DurationTotal = UsageAggregate["duration"];
type TokenTotal = UsageAggregate["total_tokens"];
type Coverage = Pick<CostTotal, "measured_entries" | "estimated_entries" | "unknown_entries">;

export const USAGE_PERIODS: ReadonlyArray<{ id: string; label: string; days: number | null }> = [
  { id: "7d", label: "7 derniers jours", days: 7 },
  { id: "30d", label: "30 derniers jours", days: 30 },
  { id: "90d", label: "90 derniers jours", days: 90 },
  { id: "all", label: "Tout l'historique", days: null },
];

export const USAGE_GROUPINGS: ReadonlyArray<{ id: UsageGroupBy; label: string }> = [
  { id: "task", label: "Par tâche" },
  { id: "configuration", label: "Par configuration" },
  { id: "day", label: "Par jour" },
  { id: "none", label: "Total seul" },
];

const STATUS_LABEL: Record<string, string> = {
  exact: "mesuré",
  estimated: "estimé",
  partial: "partiel",
  unknown: "inconnu",
  mixed_currency: "devises mélangées",
  none: "aucune mesure",
};

const STATUS_TONE: Record<string, DsTone> = {
  exact: "success",
  estimated: "info",
  partial: "warning",
  unknown: "neutral",
  mixed_currency: "warning",
  none: "neutral",
};

function statusLabel(status: string): string {
  return Object.prototype.hasOwnProperty.call(STATUS_LABEL, status) ? (STATUS_LABEL[status] as string) : `inconnu (${status})`;
}

function statusTone(status: string): DsTone {
  return Object.prototype.hasOwnProperty.call(STATUS_TONE, status) ? (STATUS_TONE[status] as DsTone) : "neutral";
}

function plural(count: number, singular: string, pluralForm: string): string {
  return `${count} ${count > 1 ? pluralForm : singular}`;
}

/** Durée lisible à partir des secondes serveur (conversion d'unité, aucune somme). */
export function formatSeconds(raw: string): string {
  const seconds = Number(raw);
  if (!Number.isFinite(seconds)) return `${raw} s`;
  if (seconds < 60) return `${raw.replace(".", ",")} s`;
  const whole = Math.round(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(rest).padStart(2, "0");
  return hours > 0 ? `${hours} h ${mm} min ${ss} s` : `${minutes} min ${ss} s`;
}

function formatTokens(value: number): string {
  return value.toLocaleString("fr-FR");
}

function formatAmount(raw: string, currency: string | null | undefined): string {
  return `${raw.replace(".", ",")} ${currency ?? "(devise inconnue)"}`;
}

/**
 * Valeur honnête d'une métrique selon son statut serveur. `data-usage-status`
 * porte le code ; `data-usage-value` la somme connue brute (jamais totalisée ici).
 */
function honestValueHtml(status: string, raw: string | null, display: string | null, coverage: Coverage, kind: string): string {
  const attrs = `data-usage-metric="${esc(kind)}" data-usage-status="${esc(status)}"${raw === null ? "" : ` data-usage-value="${esc(raw)}"`}`;
  return `<span ${attrs}>${esc(honestText(status, display, coverage))}</span>`;
}

function honestText(status: string, known: string | null, coverage: Coverage): string {
  const unknownPart = coverage.unknown_entries > 0 ? ` · inconnu pour ${plural(coverage.unknown_entries, "entrée", "entrées")}` : "";
  switch (status) {
    case "exact":
      return known ?? "inconnu";
    case "estimated":
      return known === null ? "inconnu" : `≈ ${known} (estimé)`;
    case "partial":
      return known === null ? `inconnu${unknownPart}` : `au moins ${known}${unknownPart}`;
    case "none":
      return "Aucune mesure";
    case "mixed_currency":
      return "Devises mélangées : pas de total";
    case "unknown":
      return "inconnu";
    default:
      return known === null ? `inconnu (${status})` : `au moins ${known} · statut inconnu (${status})`;
  }
}

export function costValueHtml(cost: CostTotal): string {
  if (cost.status === "mixed_currency") {
    const parts = (cost.by_currency ?? [])
      .map(
        (amount) =>
          `<li data-usage-currency="${esc(amount.currency)}" data-usage-value="${esc(amount.known_sum)}">` +
          `${esc(formatAmount(amount.known_sum, amount.currency))} (${esc(plural(amount.entries, "entrée", "entrées"))})</li>`,
      )
      .join("");
    return `${honestValueHtml(cost.status, null, null, cost, "cost")}${parts === "" ? "" : `<ul class="usage-currencies">${parts}</ul>`}`;
  }
  const raw = cost.known_sum ?? null;
  return honestValueHtml(cost.status, raw, raw === null ? null : formatAmount(raw, cost.currency), cost, "cost");
}

export function durationValueHtml(duration: DurationTotal): string {
  const raw = duration.known_sum ?? null;
  return honestValueHtml(duration.status, raw, raw === null ? null : formatSeconds(raw), duration, "duration");
}

export function tokensValueHtml(tokens: TokenTotal): string {
  const raw = tokens.known_sum ?? null;
  return honestValueHtml(tokens.status, raw === null ? null : String(raw), raw === null ? null : formatTokens(raw), tokens, "tokens");
}

/** Total en une ligne de texte, mêmes règles d'honnêteté que le tableau. */
export function usageTotalText(total: UsageAggregate): string {
  const { duration, cost, total_tokens: tokens } = total;
  const costKnown = cost.known_sum ?? null;
  const durationKnown = duration.known_sum ?? null;
  const tokensKnown = tokens.known_sum ?? null;
  return [
    `durée ${honestText(duration.status, durationKnown === null ? null : formatSeconds(durationKnown), duration)}`,
    `coût ${honestText(cost.status, costKnown === null ? null : formatAmount(costKnown, cost.currency), cost)}`,
    `jetons ${honestText(tokens.status, tokensKnown === null ? null : formatTokens(tokensKnown), tokens)}`,
  ].join(" · ");
}

function coverageText(coverage: Coverage): string {
  const parts = [
    coverage.measured_entries > 0 ? `${coverage.measured_entries} mesurée(s)` : "",
    coverage.estimated_entries > 0 ? `${coverage.estimated_entries} estimée(s)` : "",
    coverage.unknown_entries > 0 ? `${coverage.unknown_entries} inconnue(s)` : "",
  ].filter((part) => part !== "");
  return parts.length === 0 ? "—" : parts.join(" · ");
}

function metricRowHtml(label: string, status: string, value: string, coverage: Coverage): string {
  return (
    `<tr><th scope="row">${esc(label)}</th><td>${value}</td>` +
    `<td>${dsBadge(statusLabel(status), statusTone(status))}</td><td class="ds-list-sub">${esc(coverageText(coverage))}</td></tr>`
  );
}

function sourcesText(aggregate: UsageAggregate): string {
  const sources = aggregate.sources ?? [];
  if (sources.length === 0) return "aucune";
  return sources.map((source) => `${source.collector} (${source.entries})`).join(" · ");
}

/** Bloc total : durée, coût, jetons avec leur qualité, puis les sources. */
export function usageTotalHtml(total: UsageAggregate): string {
  if (total.entries === 0) {
    return `<p class="ds-list-sub" data-usage-empty>Aucune mesure de consommation sur cette période.</p>`;
  }
  const span =
    total.first_period_start && total.last_period_end
      ? ` · du ${fmtTime(total.first_period_start)} au ${fmtTime(total.last_period_end)}`
      : "";
  return (
    `<div data-usage-total><p class="ds-list-sub">${esc(plural(total.entries, "mesure", "mesures"))}${span}</p>` +
    `<div class="ds-table-wrap"><table class="ds-table usage-table"><caption>Durée, coût et qualité de mesure</caption>` +
    `<thead><tr><th scope="col">Mesure</th><th scope="col">Valeur</th><th scope="col">Qualité</th><th scope="col">Couverture</th></tr></thead><tbody>` +
    metricRowHtml("Durée", total.duration.status, durationValueHtml(total.duration), total.duration) +
    metricRowHtml("Coût", total.cost.status, costValueHtml(total.cost), total.cost) +
    metricRowHtml("Jetons", total.total_tokens.status, tokensValueHtml(total.total_tokens), total.total_tokens) +
    `</tbody></table></div>` +
    `<p class="ds-list-sub" data-usage-sources>Sources : ${esc(sourcesText(total))}</p></div>`
  );
}

function groupLabelHtml(groupBy: string, group: UsageAggregate): string {
  const key = group.key ?? {};
  if (groupBy === "task") {
    if (key.task_id === null || key.task_id === undefined) return "Sans tâche";
    const title = key.task_title !== null && key.task_title !== undefined && key.task_title !== "" ? key.task_title : "Tâche sans titre";
    return `<a href="#/tasks/${esc(key.task_id)}">${esc(title)}</a>`;
  }
  if (groupBy === "configuration") {
    const parts = [key.harness, key.provider, key.model].map((part) => (part === null || part === undefined || part === "" ? "inconnu" : part));
    return esc(parts.join(" · "));
  }
  if (groupBy === "day") {
    return key.day === null || key.day === undefined ? "Jour inconnu" : esc(new Date(`${key.day}T00:00:00Z`).toLocaleDateString("fr-FR", { timeZone: "UTC" }));
  }
  return "Total";
}

const GROUP_HEADER: Record<string, string> = { task: "Tâche", configuration: "Outil · fournisseur · modèle", day: "Jour (UTC)" };

export function usageGroupsHtml(summary: UsageSummary): string {
  const groups = summary.groups ?? [];
  if (summary.group_by === "none" || groups.length === 0) return "";
  const rows = groups
    .map(
      (group) =>
        `<tr data-usage-group><th scope="row">${groupLabelHtml(summary.group_by, group)}</th>` +
        `<td>${group.entries}</td><td>${durationValueHtml(group.duration)}</td><td>${costValueHtml(group.cost)}</td>` +
        `<td>${tokensValueHtml(group.total_tokens)}</td></tr>`,
    )
    .join("");
  const truncated = summary.truncated
    ? `<p class="ds-list-sub" data-usage-truncated>Liste limitée aux ${groups.length} groupes les plus récents ; le total couvre toute la période.</p>`
    : "";
  return (
    `<div class="ds-table-wrap"><table class="ds-table usage-table" data-usage-groups><caption>Détail ${esc((USAGE_GROUPINGS.find((g) => g.id === summary.group_by)?.label ?? "").toLowerCase())}</caption>` +
    `<thead><tr><th scope="col">${esc(GROUP_HEADER[summary.group_by] ?? "Groupe")}</th><th scope="col">Mesures</th><th scope="col">Durée</th><th scope="col">Coût</th><th scope="col">Jetons</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>${truncated}`
  );
}

function techRows(summary: UsageSummary): DsTechRow[] {
  const rows: DsTechRow[] = [
    { label: "Projet", value: summary.project_id, mono: true },
    { label: "Regroupement (code)", value: summary.group_by, mono: true },
    { label: "Calculé le", value: fmtTime(summary.generated_at) },
  ];
  if (summary.task_id) rows.push({ label: "Tâche", value: summary.task_id, mono: true });
  if (summary.since) rows.push({ label: "Depuis (inclus)", value: summary.since, mono: true });
  if (summary.until) rows.push({ label: "Jusqu'à (exclu)", value: summary.until, mono: true });
  rows.push({ label: "Statut coût (code)", value: summary.total.cost.status, mono: true });
  return rows;
}

export function usageSummaryHtml(summary: UsageSummary): string {
  return `${usageTotalHtml(summary.total)}${usageGroupsHtml(summary)}${dsTechDetails(techRows(summary), "Détails techniques · période et identifiants")}`;
}

export function usageUnavailableHtml(error: unknown): string {
  const text =
    error instanceof ApiError && error.status === 403
      ? "Votre compte n'a pas accès à la consommation de ce projet."
      : `Consommation indisponible. ${describeError(error)}`;
  return `<p class="ds-list-sub" data-usage-unavailable>${esc(text)}</p>`;
}

/** Section de la fiche tâche : total de la tâche, toute période. */
export function taskUsageSectionHtml(usage: UsageSummary | null | undefined): string {
  if (usage === undefined) return "";
  const body =
    usage === null
      ? `<p class="ds-list-sub" data-usage-unavailable>Consommation indisponible pour le moment.</p>`
      : `${usageTotalHtml(usage.total)}${dsTechDetails(techRows(usage), "Détails techniques · période et identifiants")}`;
  return `<section class="task-detail-section" aria-label="Consommation" data-usage>${dsSectionHeader("Consommation")}${body}</section>`;
}

export interface UsageViewContext {
  client: StudioClient;
  projectId: string;
  authed: boolean;
  /** Horloge injectable (tests). */
  now?: () => number;
}

export function usageSince(periodId: string, now: number): string | undefined {
  const days = USAGE_PERIODS.find((period) => period.id === periodId)?.days ?? null;
  return days === null ? undefined : new Date(now - days * 86_400_000).toISOString();
}

function controlsHtml(periodId: string, groupBy: UsageGroupBy): string {
  const periods = USAGE_PERIODS.map(
    (period) => `<option value="${period.id}"${period.id === periodId ? " selected" : ""}>${esc(period.label)}</option>`,
  ).join("");
  const groupings = USAGE_GROUPINGS.map(
    (grouping) => `<option value="${grouping.id}"${grouping.id === groupBy ? " selected" : ""}>${esc(grouping.label)}</option>`,
  ).join("");
  return (
    `<div class="usage-controls">` +
    `<label>Période <select class="ds-select" data-usage-period>${periods}</select></label> ` +
    `<label>Regroupement <select class="ds-select" data-usage-group-by>${groupings}</select></label></div>`
  );
}

function projectSectionHtml(controls: string, body: string): string {
  return `<section data-usage aria-label="Consommation">${dsSectionHeader("Consommation")}${controls}<div data-usage-body aria-live="polite">${body}</div></section>`;
}

/** Section de la vue d'ensemble projet : période et regroupement au choix. */
export async function renderProjectUsageInto(root: HTMLElement, ctx: UsageViewContext): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = "";
    return;
  }
  const now = ctx.now ?? Date.now;
  let periodId = "30d";
  let groupBy: UsageGroupBy = "task";
  let generation = 0;
  root.innerHTML = projectSectionHtml(controlsHtml(periodId, groupBy), dsSkeleton(3));

  const load = async (): Promise<void> => {
    generation += 1;
    const current = generation;
    const body = root.querySelector<HTMLElement>("[data-usage-body]");
    if (body === null) return;
    body.innerHTML = dsSkeleton(3);
    let html: string;
    try {
      const since = usageSince(periodId, now());
      const summary = await fetchUsageSummary(ctx.client, {
        projectId: ctx.projectId,
        groupBy,
        ...(since === undefined ? {} : { since }),
      });
      html = usageSummaryHtml(summary);
    } catch (error) {
      html = usageUnavailableHtml(error);
    }
    if (current === generation) body.innerHTML = html;
  };

  root.querySelector<HTMLSelectElement>("[data-usage-period]")?.addEventListener("change", (event) => {
    periodId = (event.currentTarget as HTMLSelectElement).value;
    void load();
  });
  root.querySelector<HTMLSelectElement>("[data-usage-group-by]")?.addEventListener("change", (event) => {
    groupBy = (event.currentTarget as HTMLSelectElement).value as UsageGroupBy;
    void load();
  });
  await load();
}
