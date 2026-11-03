/**
 * Historique des configurations — vue descriptive d'un projet
 * (P06-history-option, DEC-0221).
 *
 * - Source unique : GET /api/v1/usage/configuration-history. Les groupes sont
 *   affichés dans l'ordre reçu : jamais retriés, aucun « meilleur », aucune
 *   couleur de classement.
 * - Un groupe décrit des lancements, il ne les compare pas. Le bandeau
 *   permanent le rappelle : tests réussis ≠ garantie de qualité, aucun
 *   effectif minimum, groupes non comparables.
 * - Un taux n'est jamais affiché sans son `n`, sa définition et sa couverture ;
 *   `value === null` (dénominateur nul) devient « non calculable (n = 0) »,
 *   jamais 0 %.
 * - Les faits sans lancement vivent dans « Non attribué », jamais répartis
 *   dans un groupe.
 * - Aucun UUID visible hors dsTechDetails replié.
 */
import type { StudioClient } from "../api";
import { ApiError } from "../api";
import { dsSectionHeader, dsSkeleton, dsTechDetails, type DsTechRow } from "../ds/ds";
import { describeError, esc, fmtTime } from "../ui";
import {
  fetchConfigurationHistory,
  type ConfigurationHistory,
  type ConfigurationHistoryGroup,
  type ConfigurationRate,
} from "../usageApi";
import { USAGE_PERIODS, costValueHtml, tokensValueHtml } from "./usage";
import "./usage.css";

const RATE_LABEL: Record<string, string> = {
  succeeded: "Tests réussis",
  session_linked: "Session liée",
  usage_measured: "Consommation mesurée",
};

const STATUS_LABEL: Record<string, string> = {
  requested: "demandé",
  accepted: "accepté",
  preparing: "en préparation",
  running: "en cours",
  succeeded: "terminé (code 0)",
  failed: "échec",
  cancelled: "annulé",
  rejected: "refusé",
  expired: "expiré",
};

/** Borne basse de « Tout l'historique » : la route exige `since` et `until`. */
export const HISTORY_ALL_SINCE = "1970-01-01T00:00:00.000Z";

export function historyWindow(periodId: string, now: number): { since: string; until: string } {
  const days = USAGE_PERIODS.find((period) => period.id === periodId)?.days ?? null;
  return {
    since: days === null ? HISTORY_ALL_SINCE : new Date(now - days * 86_400_000).toISOString(),
    until: new Date(now).toISOString(),
  };
}

/** `null` = jamais rapporté ; `"mixed"` = les lancements ne s'accordent pas. */
export function keyValue(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "inconnu";
  if (value === "mixed") return "mixte";
  return value;
}

export function rateValueText(rate: ConfigurationRate): string {
  if (rate.value === null || rate.value === undefined) return "non calculable (n = 0)";
  const percent = (rate.value * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 });
  return `${rate.numerator}/${rate.denominator} (${percent} %)`;
}

function statusCountsText(counts: Record<string, number>): string {
  const parts = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([status, count]) => `${count} ${STATUS_LABEL[status] ?? status}`);
  return parts.length === 0 ? "aucun statut rapporté" : parts.join(" · ");
}

function groupHeading(group: ConfigurationHistoryGroup): string {
  const key = group.key;
  const harness = keyValue(key.harness);
  const version = keyValue(key.harness_version);
  const profile =
    key.profile_key === null || key.profile_key === undefined || key.profile_key === ""
      ? "inconnu"
      : key.profile_contract_version === null || key.profile_contract_version === undefined
        ? key.profile_key
        : `${key.profile_key} (v${key.profile_contract_version})`;
  return (
    `<h3>${esc(harness)} · ${esc(version)}</h3>` +
    `<p class="ds-list-sub">Fournisseur : ${esc(keyValue(key.provider))} · Modèle : ${esc(keyValue(key.model))} · Profil : ${esc(profile)}</p>` +
    `<p class="ds-list-sub" data-history-group-meta>${esc(String(group.launches))} lancement(s) · ${esc(statusCountsText(group.status_counts ?? {}))}</p>`
  );
}

function ratesTableHtml(group: ConfigurationHistoryGroup): string {
  const rows = (group.rates ?? [])
    .map(
      (rate) =>
        `<tr data-history-rate="${esc(rate.key)}"><th scope="row">${esc(RATE_LABEL[rate.key] ?? rate.key)}</th>` +
        `<td data-history-rate-value="${esc(rateValueText(rate))}">${esc(rateValueText(rate))}</td>` +
        `<td class="ds-list-sub">${esc(rate.definition)}</td>` +
        `<td>couverture ${esc(String(rate.covered))}/${esc(String(rate.launches))}</td></tr>`,
    )
    .join("");
  return (
    `<p class="ds-list-sub" data-history-period>Période : du ${esc(fmtTime(group.first_requested_at))} au ${esc(fmtTime(group.last_requested_at))}</p>` +
    `<div class="ds-table-wrap"><table class="ds-table usage-table" data-history-rates>` +
    `<caption>Taux descriptifs — chaque taux garde son dénominateur et sa définition</caption>` +
    `<thead><tr><th scope="col">Taux</th><th scope="col">Valeur</th><th scope="col">Définition</th><th scope="col">Couverture</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>`
  );
}

function groupUsageHtml(group: ConfigurationHistoryGroup): string {
  return (
    `<div class="ds-table-wrap"><table class="ds-table usage-table" data-history-usage>` +
    `<caption>Jetons et coût mesurés (aucun recalcul côté client)</caption>` +
    `<thead><tr><th scope="col">Mesure</th><th scope="col">Valeur</th></tr></thead><tbody>` +
    `<tr><th scope="row">Jetons</th><td>${tokensValueHtml(group.total_tokens)}</td></tr>` +
    `<tr><th scope="row">Coût</th><td>${costValueHtml(group.cost)}</td></tr>` +
    `</tbody></table></div>` +
    `<p class="ds-list-sub">Entrées du ledger : ${esc(String(group.ledger_entries))} · Travail IA : ${esc(String(group.ai_work_entries))}</p>`
  );
}

function groupHtml(group: ConfigurationHistoryGroup): string {
  return (
    `<article class="workspace-section" data-history-group>` +
    groupHeading(group) +
    ratesTableHtml(group) +
    groupUsageHtml(group) +
    `</article>`
  );
}

function unattributedHtml(history: ConfigurationHistory): string {
  const unattributed = history.unattributed ?? { ledger_entries: 0, ai_work_entries: 0 };
  const ledgerEntries = unattributed.ledger_entries ?? 0;
  const aiWorkEntries = unattributed.ai_work_entries ?? 0;
  const total = ledgerEntries + aiWorkEntries;
  const body =
    total === 0
      ? `<p class="ds-list-sub">Aucune entrée non attribuée sur la période.</p>`
      : `<p class="ds-list-sub">Entrées du ledger sans lancement : ${esc(String(ledgerEntries))} · Travail IA sans lancement : ${esc(String(aiWorkEntries))}.</p>` +
        `<p class="ds-list-sub">Ces faits sont affichés séparément, jamais répartis dans un groupe.</p>`;
  return `<section class="workspace-section" aria-label="Non attribué" data-history-unattributed>${dsSectionHeader("Non attribué")}${body}</section>`;
}

/** Bandeau permanent : la vue décrit, elle ne classe ni ne garantit. */
export function historyCaveatBannerHtml(): string {
  return (
    `<div class="ds-notice ds-notice--info" role="note" data-history-banner>` +
    `<strong>Groupes non comparables, non classés.</strong> ` +
    `Tests réussis ≠ garantie de qualité. Aucun effectif minimum.</div>`
  );
}

function techRows(history: ConfigurationHistory): DsTechRow[] {
  return [
    { label: "Projet", value: history.project_id, mono: true },
    { label: "Depuis (inclus)", value: history.since, mono: true },
    { label: "Jusqu'à (exclu)", value: history.until, mono: true },
    { label: "Calculé le", value: fmtTime(history.generated_at) },
    { label: "Population (code)", value: history.population, mono: true },
    { label: "Classement (code)", value: history.ranking, mono: true },
    { label: "Lancements", value: String(history.launches) },
  ];
}

export function configurationHistoryHtml(history: ConfigurationHistory): string {
  const historyGroups = history.groups ?? [];
  const groups =
    historyGroups.length === 0
      ? `<p class="ds-list-sub" data-history-empty>Aucune configuration sur cette période.</p>`
      : historyGroups.map(groupHtml).join("");
  const truncated = history.truncated
    ? `<p class="ds-list-sub" data-history-truncated>Liste limitée aux ${historyGroups.length} configurations ; les totaux de chaque groupe restent ceux du serveur.</p>`
    : "";
  return (
    `${groups}${truncated}` +
    unattributedHtml(history) +
    dsTechDetails(techRows(history), "Détails techniques · période et identifiants")
  );
}

export function historyUnavailableHtml(error: unknown): string {
  const text =
    error instanceof ApiError && error.status === 403
      ? "Votre compte n'a pas accès à l'historique des configurations de ce projet."
      : `Historique des configurations indisponible. ${describeError(error)}`;
  return `<p class="ds-list-sub" data-history-unavailable>${esc(text)}</p>`;
}

export interface ConfigurationHistoryViewContext {
  client: StudioClient;
  projectId: string;
  authed: boolean;
  /** Horloge injectable (tests). */
  now?: () => number;
}

function controlsHtml(periodId: string): string {
  const periods = USAGE_PERIODS.map(
    (period) => `<option value="${period.id}"${period.id === periodId ? " selected" : ""}>${esc(period.label)}</option>`,
  ).join("");
  return `<div class="usage-controls"><label>Période <select class="ds-select" data-history-period>${periods}</select></label></div>`;
}

/** Onglet projet : choix de période, bandeau permanent, groupes dans l'ordre reçu. */
export async function renderConfigurationHistoryInto(
  root: HTMLElement,
  ctx: ConfigurationHistoryViewContext,
): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = "";
    return;
  }
  const now = ctx.now ?? Date.now;
  let periodId = "30d";
  let generation = 0;
  root.innerHTML =
    `<section data-configuration-history aria-label="Historique des configurations">` +
    `${dsSectionHeader("Historique des configurations")}${controlsHtml(periodId)}${historyCaveatBannerHtml()}` +
    `<div data-history-body aria-live="polite">${dsSkeleton(3)}</div></section>`;

  const load = async (): Promise<void> => {
    generation += 1;
    const current = generation;
    const body = root.querySelector<HTMLElement>("[data-history-body]");
    if (body === null) return;
    body.innerHTML = dsSkeleton(3);
    let html: string;
    try {
      const window = historyWindow(periodId, now());
      const history = await fetchConfigurationHistory(ctx.client, ctx.projectId, window);
      html = configurationHistoryHtml(history);
    } catch (error) {
      html = historyUnavailableHtml(error);
    }
    if (current === generation) body.innerHTML = html;
  };

  root.querySelector<HTMLSelectElement>("[data-history-period]")?.addEventListener("change", (event) => {
    periodId = (event.currentTarget as HTMLSelectElement).value;
    void load();
  });
  await load();
}
