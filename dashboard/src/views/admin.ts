import type { StudioClient } from "../api";
import { ApiError, apiBaseUrl, parseErrorBody } from "../api";
import type { components } from "../openapi-schema";
import { getToken } from "../auth";
import { dsBadge, dsEmptyState, dsHeroCard, dsPageHeader, dsSkeleton, type DsTone } from "../ds/ds";
import { fetchCanonicalMachines, isDashboardIdentity, type Machine } from "../machinesApi";
import { listRuntimes, type RuntimeRegistration } from "../runtimesApi";
import { listRuntimeBindings, type RuntimeBinding } from "../bindingsApi";
import { getConsumption, type TransferConsumption } from "../transfersApi";
import { humanBytes } from "../transfersFormat";
import { getDesktopShell, refreshDaemon } from "../desktopShell";
import { conditionLabel, daemonLabel, type DaemonSummary } from "../shellStatus";
import { icon } from "../shell";
import { describeError, esc, fmtTime } from "../ui";
import "./admin.css";

export interface AdminFamily {
  href: string;
  title: string;
  hint: string;
  icon: string;
}

export const ADMIN_FAMILIES: readonly AdminFamily[] = [
  { href: "#/machines", title: "Postes", hint: "Environnements où le travail s'exécute", icon: "machines" },
  { href: "#/accounts", title: "Comptes et membres", hint: "Comptes, sessions et accès par projet", icon: "person" },
  { href: "#/transfers", title: "Transferts", hint: "Fichiers échangés entre postes", icon: "transfers" },
  { href: "#/library", title: "Bibliothèque", hint: "Règles, savoir-faire et configurations", icon: "book" },
  { href: "#/configuration/runtimes", title: "Configuration", hint: "Runtimes, liaisons, projet, appli, IA", icon: "settings" },
  { href: "#/workspaces", title: "Espaces de travail", hint: "Dossiers suivis sur ce poste", icon: "folder" },
];

function familyCardHtml(family: AdminFamily): string {
  return (
    `<li><a class="admin-fam" href="${esc(family.href)}">` +
    `<span class="admin-fam-pic" aria-hidden="true">${icon(family.icon)}</span>` +
    `<span class="admin-fam-body"><strong>${esc(family.title)}</strong>` +
    `<span class="ds-list-sub">${esc(family.hint)}</span></span>` +
    `<span class="admin-fam-chev" aria-hidden="true">›</span></a></li>`
  );
}

export type AdminResult<T> = { data: T; error?: never } | { data?: never; error: string };

export interface AdminOverviewData {
  checkedAt: string;
  machines: AdminResult<Machine[]>;
  runtimes: AdminResult<RuntimeRegistration[]>;
  bindings: AdminResult<RuntimeBinding[]>;
  queue: AdminResult<components["schemas"]["ReviewQueue"]>;
  storage: AdminResult<TransferConsumption>;
  daemon: AdminResult<DaemonSummary> | null;
}

export interface AdminIndicator {
  title: string;
  value: string;
  detail: string;
  href: string;
  action: string;
  tone: DsTone;
  attention: boolean;
}

export function adminIndicators(data: AdminOverviewData): AdminIndicator[] {
  const unavailable = (title: string, error: string, href: string, action: string): AdminIndicator => ({ title, value: "État inconnu", detail: error, href, action, tone: "warning", attention: true });
  const cards: AdminIndicator[] = [];
  if (data.machines.error !== undefined) cards.push(unavailable("Postes", data.machines.error, "#/machines", "Vérifier les postes"));
  else {
    const machines = data.machines.data.filter((machine) => !isDashboardIdentity(machine.display_name));
    const offline = machines.filter((machine) => machine.status === "offline");
    const idle = machines.filter((machine) => machine.status === "idle");
    cards.push({ title: "Postes", value: `${offline.length} hors ligne`, detail: `${machines.length} poste(s) accessible(s), ${idle.length} inactif(s). ${offline.length === 0 ? "Présence remontée par le serveur." : offline.slice(0, 3).map((machine) => machine.display_name).join(", ")}`, href: "#/machines", action: "Vérifier les postes", tone: offline.length > 0 ? "warning" : "success", attention: offline.length > 0 });
  }
  const configErrors = [data.runtimes.error, data.bindings.error].filter((value): value is string => value !== undefined);
  if (configErrors.length > 0) cards.push(unavailable("Configuration", configErrors.join(" · "), "#/configuration/runtimes", "Ouvrir la configuration"));
  else if (data.runtimes.data !== undefined && data.bindings.data !== undefined) {
    const active = data.runtimes.data.filter((runtime) => runtime.status === "active");
    const incomplete = active.filter((runtime) => !runtime.harness_ref || !runtime.provider_ref || !runtime.model_ref);
    const broken = data.bindings.data.filter((binding) => binding.target.runtime_id && !active.some((runtime) => runtime.id === binding.target.runtime_id));
    const missing = active.length === 0 || data.bindings.data.length === 0;
    const attention = missing || incomplete.length > 0 || broken.length > 0;
    const details = [active.length === 0 ? "Aucun runtime actif." : `${active.length} runtime(s) actif(s), ${incomplete.length} avec des références à compléter.`, data.bindings.data.length === 0 ? "Aucune liaison définie." : `${broken.length} liaison(s) vers un runtime absent ou révoqué.`];
    cards.push({ title: "Configuration", value: attention ? "À compléter" : "Références renseignées", detail: details.join(" "), href: broken.length > 0 || data.bindings.data.length === 0 ? "#/configuration/bindings" : "#/configuration/runtimes", action: "Ouvrir la configuration", tone: attention ? "warning" : "success", attention });
  }
  if (data.daemon === null) cards.push({ title: "Synchronisation", value: "État local non observé", detail: "La synchronisation des autres postes n'est pas observable depuis ce navigateur. Consultez l'application sur le poste concerné.", href: "#/configuration/application", action: "Voir l'état de l'application", tone: "neutral", attention: false });
  else if (data.daemon.error !== undefined) cards.push(unavailable("Synchronisation", data.daemon.error, "#/configuration/application", "Diagnostiquer l'application"));
  else {
    const daemon = data.daemon.data;
    const health = daemon.kind === "state" ? daemon.health : null;
    const healthy = daemon.kind === "state" && daemon.state === "running" && health?.outboxReplay === "healthy";
    cards.push({ title: "Synchronisation", value: health ? conditionLabel(health.outboxReplay) : daemonLabel(daemon), detail: `Ce poste uniquement.${health ? ` Observation locale : ${fmtTime(health.observedAt)}.` : " Le rejeu de la file n'a pas été observé."}`, href: "#/configuration/application", action: "Diagnostiquer l'application", tone: healthy ? "success" : "warning", attention: !healthy });
  }
  if (data.queue.error !== undefined) cards.push(unavailable("Validations", data.queue.error, "#/decisions", "Ouvrir la file À valider"));
  else {
    const keys = new Set(data.queue.data.items.filter((item) => ["ai_work_review", "decision_proposal", "roadmap_proposal"].includes(item.kind)).map((item) => item.kind === "roadmap_proposal" ? `roadmap:${item.project_id}:${item.roadmap_id}` : `${item.kind}:${item.id}`));
    cards.push({ title: "Validations", value: `${keys.size} en attente`, detail: `Travaux IA, décisions et plans de vos projets accessibles. File générée le ${fmtTime(data.queue.data.generated_at)}.`, href: "#/decisions", action: "Ouvrir la file À valider", tone: keys.size > 0 ? "warning" : "success", attention: keys.size > 0 });
  }
  if (data.storage.error !== undefined) cards.push(unavailable("Stockage", data.storage.error, "#/transfers", "Gérer les transferts"));
  else {
    const storage = data.storage.data;
    cards.push({ title: "Stockage", value: `${humanBytes(storage.consumed_bytes)} utilisés`, detail: `Quota de transfert de votre compte : ${humanBytes(storage.quota_bytes)}. ${humanBytes(storage.remaining_bytes)} disponibles.`, href: "#/transfers", action: "Gérer les transferts", tone: storage.remaining_bytes <= 0 ? "warning" : "neutral", attention: storage.remaining_bytes <= 0 });
  }
  return cards;
}

export function adminOverviewHtml(data?: AdminOverviewData, loading = false): string {
  const indicators = data === undefined ? [] : adminIndicators(data);
  const attention = indicators.filter((item) => item.attention);
  const next = attention[0];
  const hero = dsHeroCard({
    eyebrow: "Administration",
    title: data === undefined ? "Vérifier l'état du système" : attention.length > 0 ? `${attention.length} point(s) à vérifier` : "Aucun problème détecté dans les données consultées",
    body: "Les indicateurs concernent les ressources accessibles à votre compte. La synchronisation locale décrit uniquement le poste qui exécute l'application.",
    primary: { label: next?.action ?? "Voir les postes", href: next?.href ?? "#/machines" },
  });
  const families = `<section class="ds-panel admin-families" aria-label="Familles"><header><h2>Familles</h2><span class="ds-list-sub">chaque surface en 1 clic</span></header><div class="body"><ul class="admin-fams">${ADMIN_FAMILIES.map(familyCardHtml).join("")}</ul></div></section>`;
  const context = `<section class="admin-indicators" aria-label="Points de contrôle" aria-busy="${loading ? "true" : "false"}">` +
    (data === undefined ? dsSkeleton(5) : indicators.map((item) => `<article class="ds-card admin-indicator"><div class="admin-indicator-head"><h2>${esc(item.title)}</h2>${dsBadge(item.value, item.tone)}</div><p class="ds-list-sub">${esc(item.detail)}</p><a class="ds-btn ds-btn--sm" href="${esc(item.href)}">${esc(item.action)}</a></article>`).join("")) + `</section>`;
  return (
    `<div class="admin">` +
    `${dsPageHeader("Administration", "État et actions sur les ressources de votre compte.")}` +
    `<div class="admin-main">${hero}<div class="admin-refresh"><p class="ds-list-sub" role="status">${data === undefined ? "Chargement des indicateurs…" : `Consulté le ${esc(fmtTime(data.checkedAt))}. Actualisation manuelle.`}</p><button class="ds-btn" type="button" data-admin-refresh${loading ? " disabled" : ""}>Actualiser</button></div>${context}${families}</div>` +
    `</div>`
  );
}

export interface AdminContext { client: StudioClient; authed: boolean; now?: () => Date }

export async function loadAdminOverview(ctx: AdminContext): Promise<AdminOverviewData> {
  const settle = async <T>(promise: Promise<T>): Promise<AdminResult<T>> => {
    try { return { data: await promise }; } catch (error) { return { error: describeError(error) }; }
  };
  const machines = async (): Promise<Machine[]> => {
    const rows = await fetchCanonicalMachines(apiBaseUrl(), getToken() ?? "");
    if (rows === null) throw new Error("Présence des postes indisponible sur ce serveur.");
    return rows;
  };
  const queue = async (): Promise<components["schemas"]["ReviewQueue"]> => {
    const result = await ctx.client.GET("/api/v1/review-queue");
    if (result.response.ok && result.data !== undefined) return result.data;
    throw new ApiError(parseErrorBody(result.response.status, result.error));
  };
  const [machineResult, runtimes, bindings, review, storage, daemon] = await Promise.all([
    settle(machines()), settle(listRuntimes(ctx.client)), settle(listRuntimeBindings(ctx.client)), settle(queue()), settle(getConsumption(ctx.client)), getDesktopShell() === null ? Promise.resolve(null) : settle(refreshDaemon()),
  ]);
  return { checkedAt: (ctx.now?.() ?? new Date()).toISOString(), machines: machineResult, runtimes, bindings, queue: review, storage, daemon };
}

export async function renderAdmin(root: HTMLElement, ctx?: AdminContext): Promise<void> {
  if (ctx === undefined || !ctx.authed) {
    root.innerHTML = dsPageHeader("Administration") + dsEmptyState("Connectez-vous", "Connectez-vous pour consulter les indicateurs et les outils d'administration.");
    return;
  }
  let data: AdminOverviewData | undefined;
  const load = async (): Promise<void> => {
    root.innerHTML = adminOverviewHtml(data, true);
    data = await loadAdminOverview(ctx);
    root.innerHTML = adminOverviewHtml(data);
    root.querySelector("[data-admin-refresh]")?.addEventListener("click", () => { void load(); });
  };
  await load();
}
