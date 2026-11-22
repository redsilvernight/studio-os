/**
 * Fiche N5 — Studio suspendu (docs/maquettes-atelier/nouveaux.html).
 *
 * Un studio suspendu passe en lecture seule : on explique pourquoi, ce qui
 * reste possible et comment en sortir. Bandeau persistant en tête de page,
 * jamais de suppression de données (DEC-0385). L'entrée « Exporter mes
 * données » reste toujours accessible (fiche N7 : export permis même suspendu).
 *
 * L'API n'expose que `status: "suspended"`, sans motif (S3b) : le motif et le
 * contact sont rendus en texte fixe, tels que la fiche les montre — variant
 * « propriétaire » (impayé) pour le propriétaire, « membre » (explication sans
 * reproche) pour les autres rôles. Le variant « suspendu par l'administration »
 * et les états erreur/limite restent disponibles (builders + tests) pour le
 * jour où le motif sera exposé côté API.
 */
import { describeError, esc } from "../ui";
import { dsBadge, dsEmptyState, dsErrorState, dsNotify, dsSkeleton } from "../ds/ds";
import { dsIcon } from "../ds/lot1";
import { getStudio, type Studio } from "../studioLifecycleApi";
import "./studioLifecycle.css";

export interface StudioSuspendedContext {
  baseUrl: string;
  authed: boolean;
}

/** Ligne de contenu en lecture seule (fiche : projet + dernière activité). */
export interface SuspendedContentRow {
  name: string;
  lastActivity: string;
}

/** Texte fixe (S3b) : motif du propriétaire, tel que la fiche le montre. */
export const SUSPENDED_OWNER_REASON =
  "Motif : paiement non régularisé depuis 21 jours. Régularisez-le pour rouvrir l'écriture immédiatement.";

const READ_ONLY_SUB =
  "Lecture seule : vous pouvez consulter et exporter, mais plus rien ne peut être modifié ni envoyé.";

/** Bandeau danger persistant : titre gras + corps (actions incluses, fiche N5). */
function dangerBanner(title: string, bodyHtml: string): string {
  return (
    `<div class="ds-banner ds-banner--danger" role="alert">${dsIcon("alert-triangle", 20)}` +
    `<div class="ds-banner-body"><strong>${esc(title)}</strong><span>${bodyHtml}</span></div></div>`
  );
}

function contentRowsHtml(rows: SuspendedContentRow[]): string {
  if (rows.length === 0) return "";
  const items = rows
    .map(
      (row) =>
        `<li class="ds-list-item"><div class="grow"><div class="ds-list-title">${esc(row.name)}</div>` +
        `<div class="ds-list-sub">${esc(row.lastActivity)}</div></div>${dsBadge("Lecture seule", "neutral")}</li>`,
    )
    .join("");
  return `<section class="ds-card" aria-label="Contenu du studio"><ul class="ds-list">${items}</ul></section>`;
}

function suspendedPage(banner: string, studioName: string, rows: SuspendedContentRow[]): string {
  return (
    banner +
    `<div class="studio-sections"><div><h1>${esc(studioName)}</h1>` +
    `<p class="ds-list-sub">${esc(READ_ONLY_SUB)}</p></div>` +
    contentRowsHtml(rows) +
    `</div>`
  );
}

/** Variant « Propriétaire · impayé » : régulariser rouvre l'écriture. */
export function studioSuspendedOwnerHtml(
  studioName: string,
  rows: SuspendedContentRow[] = [],
  exportHref = "#/studios",
): string {
  return suspendedPage(
    dangerBanner(
      "Ce studio est suspendu",
      `${esc(SUSPENDED_OWNER_REASON)}` +
        `<div class="studio-banner-actions"><a class="ds-btn" href="${esc(exportHref)}">Exporter mes données</a>` +
        `<button type="button" class="ds-btn ds-btn--primary" data-regularize-payment>Régulariser le paiement</button></div>`,
    ),
    studioName,
    rows,
  );
}

/** Variant « Membre · explication sans reproche ». */
export function studioSuspendedMemberHtml(
  studioName: string,
  ownerName = "Flo",
  rows: SuspendedContentRow[] = [],
  exportHref = "#/studios",
): string {
  return suspendedPage(
    dangerBanner(
      "Ce studio est suspendu",
      `Le propriétaire (${esc(ownerName)}) a été prévenu. En attendant, vous gardez la lecture et l'export de vos contributions.` +
        `<div class="studio-banner-actions"><a class="ds-btn ds-btn--primary" href="${esc(exportHref)}">Exporter mes données</a>` +
        `<button type="button" class="ds-btn ds-btn--primary" data-notify-owner>Prévenir ${esc(ownerName)}</button></div>`,
    ),
    studioName,
    rows,
  );
}

/** Variant « Suspendu par l'administration » (motif non exposé par l'API). */
export function studioSuspendedAdminHtml(
  studioName: string,
  rows: SuspendedContentRow[] = [],
  exportHref = "#/studios",
): string {
  return suspendedPage(
    dangerBanner(
      "Ce studio est suspendu",
      `Votre studio a été suspendu par l'équipe Studi'OS. Écrivez-nous pour en comprendre la raison ; aucun contenu n'a été supprimé.` +
        `<div class="studio-banner-actions"><a class="ds-btn ds-btn--primary" href="${esc(exportHref)}">Exporter mes données</a>` +
        `<button type="button" class="ds-btn" data-contact-support>Contacter le support</button></div>`,
    ),
    studioName,
    rows,
  );
}

/** État « Chargement · levée de suspension ». */
export function studioSuspendedLoadingHtml(): string {
  return `<h1>Réouverture du studio…</h1><section class="ds-card" aria-label="Chargement">${dsSkeleton(3)}</section>`;
}

/** État « Erreur · paiement refusé » (aucune donnée perdue). */
export function studioSuspendedPaymentErrorHtml(): string {
  return dangerBanner(
    "Le paiement n'a pas abouti",
    `Votre banque a refusé la transaction. Aucune donnée n'est perdue ; le studio reste en lecture seule.` +
      `<div class="studio-banner-actions"><button type="button" class="ds-btn ds-btn--primary" data-regularize-payment>Réessayer</button>` +
      `<button type="button" class="ds-btn" data-change-card>Changer de carte</button></div>`,
  );
}

/** État « Vide · rien à exporter ». */
export function studioSuspendedEmptyHtml(): string {
  return (
    dangerBanner("Ce studio est suspendu", "Lecture seule.") +
    `<div class="studio-sections"><section class="ds-card"><div class="ds-empty ds-empty--illustrated" role="status">` +
    `<span class="ds-empty-art" aria-hidden="true">${dsIcon("inbox", 40)}</span>` +
    `<h3>Rien à consulter pour l'instant</h3><p>Ce studio ne contient encore aucun projet.</p></div></section></div>`
  );
}

/** État « Limite · suspendu = toutes les écritures refusées ». */
export function studioSuspendedBlockedHtml(studioName: string): string {
  return (
    dangerBanner(
      "Action indisponible : studio suspendu",
      `Créer, envoyer et inviter sont désactivés. Consulter et exporter restent possibles.` +
        `<div class="studio-banner-actions"><button type="button" class="ds-btn ds-btn--primary" data-see-reopen>Voir comment rouvrir</button></div>`,
    ) +
    `<div class="studio-sections"><div><h1>${esc(studioName)}</h1></div>` +
    `<button type="button" class="ds-btn ds-btn--primary" disabled aria-disabled="true">Nouvelle tâche</button></div>`
  );
}

/**
 * Rendu de l'écran « studio suspendu » : lecture du statut (GET /studios/{id})
 * puis variant selon le rôle. Un studio actif n'a rien à faire ici : message
 * explicite, sans bandeau.
 */
export async function renderStudioSuspended(
  root: HTMLElement,
  ctx: StudioSuspendedContext,
  studioId: string,
): Promise<void> {
  if (!ctx.authed) {
    root.innerHTML = dsErrorState("Session requise", "Ouvrez une session pour voir l'état de ce studio.");
    return;
  }
  root.innerHTML = studioSuspendedLoadingHtml();
  let studio: Studio;
  try {
    studio = await getStudio(ctx.baseUrl, studioId);
  } catch (error) {
    root.innerHTML = dsErrorState("État du studio indisponible", describeError(error), {
      label: "Réessayer",
      id: "studio-suspended-retry",
    });
    root.querySelector("#studio-suspended-retry")?.addEventListener("click", () => {
      void renderStudioSuspended(root, ctx, studioId);
    });
    return;
  }
  if (studio.status !== "suspended") {
    root.innerHTML = dsEmptyState("Ce studio n'est pas suspendu", "Tout est ouvert : vous pouvez continuer à y travailler.", {
      label: "Ouvrir le studio",
      href: "#/",
    });
    return;
  }
  const exportHref = `#/studios/${encodeURIComponent(studio.id)}/data`;
  root.innerHTML =
    studio.role === "owner"
      ? studioSuspendedOwnerHtml(studio.name, [], exportHref)
      : studioSuspendedMemberHtml(studio.name, "Flo", [], exportHref);
  // Le paiement en ligne (fiche N3) et la messagerie ne font pas de ce lot :
  // on le dit honnêtement plutôt que de simuler une régularisation.
  root.querySelectorAll<HTMLElement>("[data-regularize-payment]").forEach((button) => {
    button.addEventListener("click", () => {
      dsNotify("Le paiement en ligne n'est pas encore disponible depuis cette page.", "info");
    });
  });
  root.querySelector("[data-notify-owner]")?.addEventListener("click", () => {
    dsNotify("Le propriétaire a déjà été prévenu par e-mail.", "info");
  });
  root.querySelector("[data-contact-support]")?.addEventListener("click", () => {
    dsNotify("Écrivez à support@studio-os.test depuis votre messagerie.", "info");
  });
}
