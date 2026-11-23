/**
 * Facturation Stripe (S4-stripe, fiche N3) — client des deux routes fusionnées.
 *
 * - POST /studios/{id}/billing/checkout {interval} -> {url} ; propriétaire seul,
 *   409 `already_subscribed`, 503 `billing_unavailable`.
 * - POST /studios/{id}/billing/portal -> {url} ; 409 `no_subscription`.
 *
 * Le paiement se fait chez Stripe (page hébergée) ; le plan ne change que par
 * webhook signé, jamais au retour : aucune logique de statut ici.
 */
import { ApiError } from "./api";
import { request } from "./studioLifecycleApi";

export type BillingInterval = "month" | "year";

/** Tarifs affichés (décision S4 : 9 €/mois, 90 €/an, Stripe Tax désactivé). */
export const BILLING_PRICES: Record<BillingInterval, string> = { month: "9 € / mois", year: "90 € / an" };

interface BillingSession {
  url: string;
}

const billingPath = (studioId: string, leaf: "checkout" | "portal"): string =>
  `/studios/${encodeURIComponent(studioId)}/billing/${leaf}`;

export function createCheckout(baseUrl: string, studioId: string, interval: BillingInterval): Promise<BillingSession> {
  return request<BillingSession>(baseUrl, billingPath(studioId, "checkout"), "POST", { interval });
}

export function createPortal(baseUrl: string, studioId: string): Promise<BillingSession> {
  return request<BillingSession>(baseUrl, billingPath(studioId, "portal"), "POST");
}

/** Message utilisateur d'une erreur de facturation (jamais un code brut). */
export function billingErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.errorCode === "billing_unavailable" || error.status === 503)
      return "Le paiement n'est pas disponible pour le moment. Réessayez plus tard.";
    if (error.errorCode === "already_subscribed")
      return "Ce studio est déjà abonné à Pro. Utilisez « Gérer l'abonnement » pour modifier ou résilier.";
    if (error.errorCode === "no_subscription")
      return "Aucun abonnement à gérer : ce studio n'a pas encore souscrit à Pro.";
    if (error.status === 403) return "Seul le propriétaire du studio peut gérer l'abonnement.";
  }
  return "Impossible de joindre le service de paiement. Réessayez dans un instant.";
}

/** Retour de Stripe : `?checkout=success|cancel|portal` (dans la recherche ou le hash). */
export type CheckoutReturn = "success" | "cancel" | "portal";

export function parseCheckoutReturn(search: string, hash: string): CheckoutReturn | null {
  const fromHash = hash.includes("?") ? hash.slice(hash.indexOf("?")) : "";
  for (const source of [search, fromHash]) {
    const value = new URLSearchParams(source).get("checkout");
    if (value === "success" || value === "cancel" || value === "portal") return value;
  }
  return null;
}
