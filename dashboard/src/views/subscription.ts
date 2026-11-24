/**
 * Abonnement (fiche N3, S4-stripe) — route `#/abonnement`.
 *
 * Visible dans la barre uniquement pour le propriétaire ; l'écran reste
 * atteignable en lien direct par les autres rôles mais explique que la
 * gestion de l'abonnement est réservée au propriétaire (jamais un 403 brut).
 *
 * Le paiement se fait chez Stripe (page hébergée) : « Passer à Pro » ouvre une
 * modale de confirmation (jamais de popup native) puis redirige ; « Gérer »
 * ouvre le portail. Le plan ne change que par webhook signé : au retour
 * (`?checkout=success|portal`) on affiche « en attente de confirmation » tant
 * que le plan n'a pas changé, sans rien modifier localement.
 *
 * `GET /studios/{id}/billing` (S4b) donne l'état Stripe : essai en cours (fin
 * de l'essai), impayé (fin du délai de grâce avant retour au plan gratuit,
 * données conservées). L'onglet « Usage » montre les compteurs du plan
 * (`GET /studios/{id}/entitlements`), lisibles par tout membre.
 */
import { dsBadge, dsModalHtml, dsProgress, dsTabsHtml, initDsTabs, dsPageHeader, dsStateHtml, closeDsDialog, focusDsErrorBox, openDsDialog } from "../ds/ds";
import { formatNumber, formatVolume } from "../format";
import { esc } from "../ui";
import { getActiveStudio } from "../studioStore";
import type { StudioRole } from "../studiosApi";
import {
  BILLING_PRICES,
  billingErrorMessage,
  createCheckout,
  createPortal,
  getBillingStatus,
  getEntitlements,
  parseCheckoutReturn,
  type BillingInterval,
  type BillingStatus,
  type CheckoutReturn,
  type StudioEntitlements,
} from "../billingApi";

export interface SubscriptionOptions {
  baseUrl: string;
  /** Retour de Stripe, déjà extrait de l'URL. */
  checkoutReturn?: CheckoutReturn | null;
  /** Redirection vers l'URL Stripe (injectable pour les tests). */
  redirect?: (url: string) => void;
}

function planTone(plan: string): "success" | "info" | "neutral" {
  const folded = plan.trim().toLowerCase();
  if (folded.startsWith("gratuit") || folded.startsWith("free")) return "neutral";
  if (folded.startsWith("pro")) return "info";
  return "success";
}

const isPro = (plan: string): boolean => plan.trim().toLowerCase().startsWith("pro");

function returnNotice(checkoutReturn: CheckoutReturn | null | undefined, pro: boolean): string {
  if (checkoutReturn === "cancel")
    return `<div class="ds-notice ds-notice--info" role="status"><strong>Paiement annulé.</strong> Rien n'a été facturé ; le plan reste inchangé.</div>`;
  if ((checkoutReturn === "success" || checkoutReturn === "portal") && !pro)
    return `<div class="ds-notice ds-notice--info" role="status"><strong>En attente de confirmation.</strong> Stripe confirme votre abonnement ; le plan se met à jour dès sa confirmation, rechargez la page dans un instant.</div>`;
  if (checkoutReturn === "portal")
    return `<div class="ds-notice ds-notice--info" role="status"><strong>Retour du portail.</strong> Les changements faits chez Stripe apparaîtront ici après confirmation.</div>`;
  return "";
}

const dayLabel = (iso: string): string => new Date(iso).toLocaleDateString("fr-FR");

/** Essai en cours ou impayé : seuls états de `GET .../billing` qui demandent un avis. */
export function billingNoticeHtml(status: BillingStatus): string {
  if (status.past_due_since !== null && status.grace_ends_at !== null)
    return `<div class="ds-notice ds-notice--danger"><strong>Paiement en échec.</strong> Mettez à jour votre moyen de paiement avant le ${esc(dayLabel(status.grace_ends_at))} (${status.grace_days} jours de grâce) : passé ce délai, le studio repasse au plan gratuit. Vos données sont conservées.</div>`;
  if (status.status === "trialing" && status.trial_ends_at !== null)
    return `<div class="ds-notice ds-notice--info"><strong>Essai gratuit en cours.</strong> Il se termine le ${esc(dayLabel(status.trial_ends_at))} ; le premier paiement a lieu à cette date, résiliable avant depuis le portail.</div>`;
  return "";
}

const USAGE_LABELS: Record<string, string> = {
  storage_bytes: "Stockage",
  projects: "Projets",
  members: "Membres",
  machines: "Appareils",
};

/** Compteurs du plan face à leurs plafonds ; seules les clés connues sont listées. */
export function usageHtml(entitlements: StudioEntitlements): string {
  const rows = Object.entries(USAGE_LABELS).flatMap(([key, label]) => {
    const counter = entitlements.counters.find((item) => item.key === key);
    if (counter === undefined) return [];
    const max = entitlements.limits.find((item) => item.key === key)?.max_value ?? null;
    const fmt = (value: number): string => (key === "storage_bytes" ? formatVolume(value) : formatNumber(value));
    const text = max === null ? `${fmt(counter.value)} · illimité` : `${fmt(counter.value)} sur ${fmt(max)}`;
    return [`<li><strong>${esc(label)}</strong>${max === null ? `<span>${esc(text)}</span>` : dsProgress(counter.value, max, `${label} : ${text}`)}</li>`];
  });
  return rows.length === 0
    ? `<p>Aucun compteur disponible pour le moment.</p>`
    : `<ul class="sub-usage">${rows.join("")}</ul>`;
}

function freeCard(): string {
  return (
    `<section class="app-card" aria-labelledby="sub-pro"><div class="app-card-text">` +
    `<h2 id="sub-pro">Passer à Pro</h2>` +
    `<p>100 Gio · 25 places · appareils illimités. Essai gratuit de 14 jours, sans engagement.</p>` +
    `<fieldset class="ds-field"><legend>Facturation</legend>` +
    `<label><input type="radio" name="sub-interval" value="month" checked> Mensuelle · ${esc(BILLING_PRICES.month)}</label> ` +
    `<label><input type="radio" name="sub-interval" value="year"> Annuelle · ${esc(BILLING_PRICES.year)}</label></fieldset>` +
    `<p>Le paiement se fait chez Stripe ; Studi'OS ne voit jamais votre carte.</p>` +
    `</div><div class="settings-actions"><button class="ds-btn ds-btn--primary" type="button" id="sub-upgrade">Passer à Pro</button></div></section>`
  );
}

function proCard(): string {
  return (
    `<section class="app-card" aria-labelledby="sub-manage"><div class="app-card-text">` +
    `<h2 id="sub-manage">Gérer l'abonnement et les factures</h2>` +
    `<p>« Gérer » ouvre le portail Stripe : moyen de paiement, factures, résiliation.</p>` +
    `</div><div class="settings-actions"><button class="ds-btn ds-btn--primary" type="button" id="sub-manage-btn">Gérer l'abonnement</button></div></section>`
  );
}

export function subscriptionHtml(role: StudioRole, checkoutReturn?: CheckoutReturn | null): string {
  const studio = getActiveStudio();
  const header = dsPageHeader("Abonnement", "Formule et facturation du studio actif.");
  if (role !== "owner") {
    return (
      `${header}` +
      dsStateHtml("empty", {
        title: "Réservé au propriétaire",
        message: `La gestion de l'abonnement${studio === null ? "" : ` de « ${studio.name} »`} est réservée au propriétaire du studio. Demandez-lui de modifier la formule.`,
        action: { label: "Retour à Aujourd'hui", href: "#/" },
      })
    );
  }
  if (studio === null) {
    return `${header}` + dsStateHtml("empty", { title: "Aucun studio", message: "Aucun studio n'est disponible pour le moment." });
  }
  const pro = isPro(studio.plan);
  const status = studio.status === "suspended" ? dsBadge("Suspendu", "danger") : dsBadge("Actif", "success");
  const current =
    `<section class="app-card" aria-labelledby="subscription-plan"><div class="app-card-text">` +
    `<h2 id="subscription-plan">Studio ${esc(studio.name)}</h2>` +
    `<p>Formule ${dsBadge(studio.plan, planTone(studio.plan))} · État ${status}</p>` +
    (studio.status === "suspended"
      ? `<p>Ce studio est suspendu : la lecture reste possible, les nouveaux envois sont refusés. Contactez le support pour régulariser.</p>`
      : "") +
    `</div><div class="settings-actions"><a class="ds-btn" href="#/aide">Comprendre les formules</a></div></section>`;
  const modal = dsModalHtml({
    id: "sub-confirm",
    title: "Continuer vers Stripe",
    body: `<p id="sub-confirm-text">Vous allez être redirigé vers la page de paiement sécurisée de Stripe.</p>`,
    actions: [
      { label: "Annuler", id: "sub-confirm-cancel" },
      { label: "Continuer", id: "sub-confirm-ok", variant: "primary" },
    ],
  });
  const plan = current + (pro ? proCard() : freeCard());
  const usage = `<div id="sub-usage" aria-live="polite"><p>Chargement de l'usage…</p></div>`;
  return (
    `${header}<div id="sub-feedback">${returnNotice(checkoutReturn, pro)}</div><div id="sub-billing" role="status"></div>` +
    dsTabsHtml(
      "sub",
      [
        { id: "plan", label: "Abonnement", panel: plan },
        { id: "usage", label: "Usage", panel: usage },
      ],
      "plan",
      "Abonnement et usage",
    ) +
    modal
  );
}

export function renderSubscription(view: HTMLElement, role: StudioRole, options?: SubscriptionOptions): void {
  const checkoutReturn =
    options?.checkoutReturn !== undefined ? options.checkoutReturn : parseCheckoutReturn(window.location.search, window.location.hash);
  view.innerHTML = subscriptionHtml(role, checkoutReturn);
  const studio = getActiveStudio();
  if (options === undefined || studio === null || role !== "owner") return;
  initDsTabs(view, "sub");
  const billing = view.querySelector<HTMLElement>("#sub-billing");
  const usage = view.querySelector<HTMLElement>("#sub-usage");
  getBillingStatus(options.baseUrl, studio.id).then(
    (status) => {
      if (billing !== null) billing.innerHTML = billingNoticeHtml(status);
    },
    () => undefined,
  );
  getEntitlements(options.baseUrl, studio.id).then(
    (entitlements) => {
      if (usage !== null) usage.innerHTML = usageHtml(entitlements);
    },
    (error: unknown) => {
      if (usage !== null) usage.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert">${esc(billingErrorMessage(error))}</div>`;
    },
  );
  const redirect = options.redirect ?? ((url: string) => window.location.assign(url));
  const feedback = view.querySelector<HTMLElement>("#sub-feedback");
  const ok = view.querySelector<HTMLButtonElement>("#sub-confirm-ok");
  const confirmText = view.querySelector<HTMLElement>("#sub-confirm-text");
  let pending: "checkout" | "portal" = "checkout";
  const fail = (error: unknown): void => {
    if (feedback !== null) {
      feedback.innerHTML = `<div class="ds-notice ds-notice--danger" role="alert"><strong>Action impossible.</strong> ${esc(billingErrorMessage(error))}</div>`;
      const box = feedback.firstElementChild;
      if (box instanceof HTMLElement) focusDsErrorBox(box);
    }
    setBusy(false);
  };
  const triggers = view.querySelectorAll<HTMLButtonElement>("#sub-upgrade, #sub-manage-btn");
  const setBusy = (busy: boolean): void => triggers.forEach((button) => (button.disabled = busy));
  const go = (call: Promise<{ url: string }>): void => {
    setBusy(true);
    if (feedback !== null) feedback.innerHTML = `<div class="ds-notice ds-notice--info" role="status">Redirection vers Stripe…</div>`;
    call.then(({ url }) => redirect(url), fail);
  };
  const upgrade = view.querySelector<HTMLButtonElement>("#sub-upgrade");
  upgrade?.addEventListener("click", () => {
    pending = "checkout";
    if (confirmText !== null) confirmText.textContent = "Vous allez être redirigé vers la page de paiement sécurisée de Stripe.";
    openDsDialog(view, "sub-confirm", upgrade);
  });
  const manage = view.querySelector<HTMLButtonElement>("#sub-manage-btn");
  manage?.addEventListener("click", () => {
    pending = "portal";
    if (confirmText !== null) confirmText.textContent = "Vous allez être redirigé vers le portail Stripe pour gérer votre abonnement.";
    openDsDialog(view, "sub-confirm", manage);
  });
  ok?.addEventListener("click", () => {
    closeDsDialog(view, "sub-confirm");
    if (pending === "portal") return go(createPortal(options.baseUrl, studio.id));
    const interval = view.querySelector<HTMLInputElement>('input[name="sub-interval"]:checked')?.value;
    go(createCheckout(options.baseUrl, studio.id, (interval === "year" ? "year" : "month") satisfies BillingInterval));
  });
}
