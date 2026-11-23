/**
 * Abonnement (R2-coque, fiche E1) — route minimale `#/abonnement`.
 *
 * Visible dans la barre uniquement pour le propriétaire ; l'écran reste
 * atteignable en lien direct par les autres rôles mais explique que la
 * gestion de l'abonnement est réservée au propriétaire (jamais un 403 brut).
 * Contenu volontairement minimal : formule et état du studio actif (N3
 * détaillera l'usage et la facturation).
 */
import { dsBadge, dsPageHeader, dsStateHtml } from "../ds/ds";
import { esc } from "../ui";
import { getActiveStudio } from "../studioStore";
import type { StudioRole } from "../studiosApi";

function planTone(plan: string): "success" | "info" | "neutral" {
  const folded = plan.trim().toLowerCase();
  if (folded.startsWith("gratuit") || folded.startsWith("free")) return "neutral";
  if (folded.startsWith("pro")) return "info";
  return "success";
}

export function subscriptionHtml(role: StudioRole): string {
  const studio = getActiveStudio();
  const header = dsPageHeader("Abonnement", "Formule et état du studio actif.");
  if (role !== "owner") {
    return (
      `${header}` +
      dsStateHtml("empty", {
        title: "Réservé au propriétaire",
        message: `La gestion de l'abonnement${studio === null ? "" : ` de « ${studio.name} »`} est réservée au propriétaire du studio. Demandez-lui de modifier la formule.`,
        action: { label: "Retour à l'Accueil", href: "#/" },
      })
    );
  }
  if (studio === null) {
    return `${header}` + dsStateHtml("empty", { title: "Aucun studio", message: "Aucun studio n'est disponible pour le moment." });
  }
  const status = studio.status === "suspended" ? dsBadge("Suspendu", "danger") : dsBadge("Actif", "success");
  return (
    `${header}` +
    `<section class="app-card" aria-labelledby="subscription-plan"><div class="app-card-text">` +
    `<h2 id="subscription-plan">Studio ${esc(studio.name)}</h2>` +
    `<p>Formule ${esc(studio.plan)} ${dsBadge(esc(studio.plan), planTone(studio.plan))} · État ${status}</p>` +
    (studio.status === "suspended"
      ? `<p>Ce studio est suspendu : la lecture reste possible, les nouveaux envois sont refusés. Contactez le support pour régulariser.</p>`
      : `<p>Le détail de l'usage et la facturation arriveront dans un prochain écran ; cette page affiche la formule du studio actif.</p>`) +
    `</div><div class="settings-actions"><a class="ds-btn" href="#/aide">Comprendre les formules</a></div></section>`
  );
}

export function renderSubscription(view: HTMLElement, role: StudioRole): void {
  view.innerHTML = subscriptionHtml(role);
}
